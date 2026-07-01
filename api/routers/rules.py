from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import AuthContext, require_api_key
from api.database import get_session
from api.models import ConsolidationSuggestion, Escalation, PolicyCheckLog, Rule, RuleConflict
from api.schemas import RuleDeleteRequest, RuleStatusUpdate
from api.services.conflict_service import ConflictService


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
