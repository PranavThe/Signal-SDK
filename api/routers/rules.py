from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import AuthContext, require_api_key
from api.background_tasks import safe_background_task
from api.database import get_session
from api.models import ConsolidationSuggestion, Escalation, PolicyCheckLog, Rule, RuleComment, RuleConflict, RuleVersion
from api.schemas import RuleDeleteRequest, RuleStatusUpdate
from api.services.conflict_service import ConflictService
from api.services.context_schema_service import ContextSchemaService
from api.services.duplicate_rule_service import DuplicateRuleService
from api.services.guard_decision_service import validate_rule_outcome_for_activation
from api.services.lifecycle_service import run_consolidation
from api.services.rule_analytics_service import RuleAnalyticsService
from api.services.rule_import_export_service import RuleImportExportService
from api.services.rule_testing_service import RuleTestingService


router = APIRouter(prefix="/v1/rules", tags=["rules"])


async def _delete_org_rules(
    session: AsyncSession,
    rule_ids: list[UUID],
    org_id: UUID,
) -> list[UUID]:
    rules = (
        await session.execute(
            select(Rule.id).where(
                Rule.id.in_(rule_ids),
                Rule.org_id == org_id,
            )
        )
    ).scalars().all()
    found_ids = list(rules)
    if not found_ids:
        return []

    await session.execute(
        update(Escalation)
        .where(Escalation.rule_id.in_(found_ids), Escalation.org_id == org_id)
        .values(rule_id=None)
    )
    await session.execute(
        update(PolicyCheckLog)
        .where(PolicyCheckLog.rule_id.in_(found_ids), PolicyCheckLog.org_id == org_id)
        .values(rule_id=None)
    )
    await session.execute(
        delete(RuleConflict).where(
            or_(
                RuleConflict.rule_a_id.in_(found_ids),
                RuleConflict.rule_b_id.in_(found_ids),
            )
        )
    )
    await session.execute(
        delete(ConsolidationSuggestion).where(
            ConsolidationSuggestion.org_id == org_id,
            or_(
                ConsolidationSuggestion.rule_a_id.in_(found_ids),
                ConsolidationSuggestion.rule_b_id.in_(found_ids),
            ),
        )
    )
    await session.execute(delete(Rule).where(Rule.id.in_(found_ids), Rule.org_id == org_id))
    await session.commit()
    return found_ids


@router.patch("/{rule_id}")
async def update_rule_status(
    rule_id: UUID,
    request: RuleStatusUpdate,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, str]:
    rule = (
        await session.execute(select(Rule).where(Rule.id == rule_id, Rule.org_id == auth.org_id))
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    if request.status == "active":
        outcome_errors = validate_rule_outcome_for_activation(rule)
        if outcome_errors:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Activating this rule would violate the guard outcome contract.",
                    "errors": outcome_errors,
                },
            )
        conflict_warnings = await ConflictService().detect_activation_conflicts(session, rule)
        if conflict_warnings:
            await session.flush()
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Activating this rule would conflict with an existing active rule.",
                    "conflicts": [
                        {
                            "existing_rule_id": warning.existing_rule_id,
                            "existing_condition": warning.existing_condition,
                            "existing_action": warning.existing_action,
                            "explanation": warning.explanation,
                        }
                        for warning in conflict_warnings
                    ],
                },
            )

    rule.status = request.status
    rule.updated_at = datetime.now(UTC)
    await session.commit()
    if request.status == "active":
        safe_background_task(run_consolidation(org_id=auth.org_id, max_pairs_per_org=50), "run_consolidation")

    return {"rule_id": str(rule.id), "status": rule.status}


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, object]:
    deleted = await _delete_org_rules(session, [rule_id], auth.org_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return {"deleted": [str(rule_id) for rule_id in deleted], "count": len(deleted)}


@router.post("/delete")
async def delete_rules(
    request: RuleDeleteRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, object]:
    deleted = await _delete_org_rules(session, request.rule_ids, auth.org_id)
    return {"deleted": [str(rule_id) for rule_id in deleted], "count": len(deleted)}


# New endpoints for product improvements


class RuleTestRequest(BaseModel):
    test_context: dict[str, Any]


class BulkRuleStatusUpdate(BaseModel):
    rule_ids: list[UUID]
    status: str


class RuleImportRequest(BaseModel):
    json_data: str
    skip_duplicates: bool = True


class AddCommentRequest(BaseModel):
    comment_text: str
    created_by_user_id: str
    created_by_email: str


@router.get("/analytics/org")
async def get_org_analytics(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Get analytics for all rules in the organization."""
    analytics_service = RuleAnalyticsService()
    analytics = await analytics_service.get_org_analytics(session, auth.org_id)

    return {
        "total_rules": analytics.total_rules,
        "active_rules": analytics.active_rules,
        "stale_rules": analytics.stale_rules,
        "most_used_rules": [
            {
                "rule_id": r.rule_id,
                "condition_description": r.condition_description,
                "trigger_count": r.trigger_count,
                "triggers_last_30_days": r.triggers_last_30_days,
            }
            for r in analytics.most_used_rules
        ],
        "least_used_rules": [
            {
                "rule_id": r.rule_id,
                "condition_description": r.condition_description,
                "trigger_count": r.trigger_count,
                "days_since_last_trigger": r.days_since_last_trigger,
            }
            for r in analytics.least_used_rules
        ],
    }


@router.get("/{rule_id}/analytics")
async def get_rule_analytics(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Get detailed analytics for a specific rule."""
    # Verify rule belongs to org
    rule = await session.get(Rule, rule_id)
    if rule is None or rule.org_id != auth.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    analytics_service = RuleAnalyticsService()
    stats = await analytics_service.get_rule_usage_stats(session, rule_id)

    if stats is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    return {
        "rule_id": stats.rule_id,
        "trigger_count": stats.trigger_count,
        "override_count": stats.override_count,
        "last_triggered_at": stats.last_triggered_at.isoformat() if stats.last_triggered_at else None,
        "days_since_last_trigger": stats.days_since_last_trigger,
        "triggers_last_7_days": stats.triggers_last_7_days,
        "triggers_last_30_days": stats.triggers_last_30_days,
        "triggers_last_90_days": stats.triggers_last_90_days,
        "is_stale": stats.is_stale,
    }


@router.get("/analytics/stale")
async def get_stale_rules(
    days_threshold: int = 90,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Get all rules that haven't been triggered in the specified number of days."""
    analytics_service = RuleAnalyticsService()
    stale_rules = await analytics_service.get_stale_rules(session, auth.org_id, days_threshold)

    return {
        "stale_rules": [
            {
                "rule_id": r.rule_id,
                "condition_description": r.condition_description,
                "action_description": r.action_description,
                "days_since_last_trigger": r.days_since_last_trigger,
                "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in stale_rules
        ],
        "count": len(stale_rules),
    }


@router.post("/{rule_id}/test")
async def test_rule(
    rule_id: UUID,
    request: RuleTestRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Test a rule against a sample context."""
    # Verify rule belongs to org
    rule = await session.get(Rule, rule_id)
    if rule is None or rule.org_id != auth.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    testing_service = RuleTestingService()
    result = await testing_service.test_rule(session, rule_id, request.test_context)

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    return {
        "rule_id": result.rule_id,
        "matched": result.matched,
        "action": result.action,
        "reasoning": result.reasoning,
        "matched_conditions": result.matched_conditions,
        "unmatched_conditions": result.unmatched_conditions,
        "guard_decision": result.guard_decision,
    }


@router.post("/{rule_id}/check-duplicates")
async def check_rule_duplicates(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Check if a rule is a duplicate of existing rules."""
    rule = await session.get(Rule, rule_id)
    if rule is None or rule.org_id != auth.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    duplicate_service = DuplicateRuleService()
    warnings = await duplicate_service.check_for_duplicates(
        session,
        rule,
        rule.condition_embedding,
    )

    return {
        "has_duplicates": len(warnings) > 0,
        "duplicates": [
            {
                "existing_rule_id": w.existing_rule_id,
                "existing_condition": w.existing_condition,
                "existing_action": w.existing_action,
                "similarity": w.similarity,
                "is_exact_match": w.is_exact_match,
                "explanation": w.explanation,
            }
            for w in warnings
        ],
    }


@router.post("/bulk/status")
async def bulk_update_rule_status(
    request: BulkRuleStatusUpdate,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Update status for multiple rules at once."""
    # Verify all rules belong to org
    rules_result = await session.execute(
        select(Rule).where(
            Rule.id.in_(request.rule_ids),
            Rule.org_id == auth.org_id,
        )
    )
    rules = rules_result.scalars().all()

    if len(rules) != len(request.rule_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Some rules not found or don't belong to this organization",
        )

    # Check for conflicts if activating
    if request.status == "active":
        conflict_service = ConflictService()
        for rule in rules:
            if rule.status != "active":
                outcome_errors = validate_rule_outcome_for_activation(rule)
                if outcome_errors:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "message": f"Rule {rule.id} would violate the guard outcome contract",
                            "rule_id": str(rule.id),
                            "errors": outcome_errors,
                        },
                    )
                conflict_warnings = await conflict_service.detect_activation_conflicts(session, rule)
                if conflict_warnings:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "message": f"Rule {rule.id} would conflict with existing active rules",
                            "rule_id": str(rule.id),
                        },
                    )

    # Update all rules
    updated_ids = []
    for rule in rules:
        rule.status = request.status
        rule.updated_at = datetime.now(UTC)
        updated_ids.append(str(rule.id))

    await session.commit()

    if request.status == "active":
        safe_background_task(run_consolidation(org_id=auth.org_id, max_pairs_per_org=50), "run_consolidation")

    return {
        "updated": updated_ids,
        "count": len(updated_ids),
        "status": request.status,
    }


@router.get("/export/json")
async def export_rules_json(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> Response:
    """Export all rules to JSON format."""
    export_service = RuleImportExportService()
    json_data = await export_service.export_rules_json(session, auth.org_id)

    return Response(
        content=json_data,
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=rules_{auth.org_id}_{datetime.now(UTC).isoformat()}.json"
        },
    )


@router.get("/export/csv")
async def export_rules_csv(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> Response:
    """Export all rules to CSV format."""
    export_service = RuleImportExportService()
    csv_data = await export_service.export_rules_csv(session, auth.org_id)

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=rules_{auth.org_id}_{datetime.now(UTC).isoformat()}.csv"
        },
    )


@router.post("/import")
async def import_rules(
    request: RuleImportRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Import rules from JSON format."""
    export_service = RuleImportExportService()
    result = await export_service.import_rules_json(
        session,
        auth.org_id,
        request.json_data,
        request.skip_duplicates,
    )
    if result.imported_rule_ids:
        imported_rules = (
            await session.execute(
                select(Rule).where(Rule.id.in_([UUID(rule_id) for rule_id in result.imported_rule_ids]))
            )
        ).scalars().all()
        context_schema = ContextSchemaService()
        for rule in imported_rules:
            rule.structured_conditions, _ = await context_schema.canonicalize_conditions(
                session,
                auth.org_id,
                rule.structured_conditions,
                learn=True,
                source="rule_import",
            )
        await session.commit()

    return {
        "success": result.success,
        "imported_count": result.imported_count,
        "skipped_count": result.skipped_count,
        "error_count": result.error_count,
        "errors": result.errors,
        "imported_rule_ids": result.imported_rule_ids,
    }


@router.post("/{rule_id}/comments")
async def add_rule_comment(
    rule_id: UUID,
    request: AddCommentRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Add a comment to a rule."""
    # Verify rule belongs to org
    rule = await session.get(Rule, rule_id)
    if rule is None or rule.org_id != auth.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    comment = RuleComment(
        rule_id=rule_id,
        comment_text=request.comment_text,
        created_by_user_id=request.created_by_user_id,
        created_by_email=request.created_by_email,
    )
    session.add(comment)
    await session.commit()

    return {
        "comment_id": str(comment.id),
        "rule_id": str(rule_id),
        "comment_text": comment.comment_text,
        "created_by": comment.created_by_email,
        "created_at": comment.created_at.isoformat(),
    }


@router.get("/{rule_id}/comments")
async def get_rule_comments(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Get all comments for a rule."""
    # Verify rule belongs to org
    rule = await session.get(Rule, rule_id)
    if rule is None or rule.org_id != auth.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    result = await session.execute(
        select(RuleComment)
        .where(RuleComment.rule_id == rule_id)
        .order_by(RuleComment.created_at.desc())
    )
    comments = result.scalars().all()

    return {
        "comments": [
            {
                "comment_id": str(c.id),
                "comment_text": c.comment_text,
                "created_by": c.created_by_email,
                "created_at": c.created_at.isoformat(),
            }
            for c in comments
        ],
        "count": len(comments),
    }


@router.get("/{rule_id}/versions")
async def get_rule_versions(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Get version history for a rule."""
    # Verify rule belongs to org
    rule = await session.get(Rule, rule_id)
    if rule is None or rule.org_id != auth.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    result = await session.execute(
        select(RuleVersion)
        .where(RuleVersion.rule_id == rule_id)
        .order_by(RuleVersion.version_number.desc())
    )
    versions = result.scalars().all()

    return {
        "versions": [
            {
                "version_id": str(v.id),
                "version_number": v.version_number,
                "condition_description": v.condition_description,
                "action_description": v.action_description,
                "exceptions_note": v.exceptions_note,
                "changed_by": v.changed_by_email,
                "change_description": v.change_description,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ],
        "current_version": len(versions) + 1,
        "count": len(versions),
    }
