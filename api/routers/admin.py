from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.templating import Jinja2Templates

from api.auth import AuthContext, require_api_key
from api.config import settings
from api.database import get_session
from api.models import ConsolidationSuggestion, Escalation, Organization, PolicyCheckLog, Rule, RuleConflict
from api.services.conflict_service import ConflictService, ConflictWarning
from api.services.escalation_pipeline import slack_delivery_available
from api.services.review_service import (
    approve_rule,
    create_rule_from_escalation,
    discard_rule,
    mark_one_time,
    publish_final_escalation_result,
    publish_rule_created,
    record_escalation_decision,
    revise_rule,
)
from api.services.resolution_propagator import propagate_rule
from api.services.semantic_service import find_similar_escalations


router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="api/templates")


class DashboardDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]


class DashboardApplyBroadlyRequest(BaseModel):
    apply_broadly: bool


class DashboardRuleEditRequest(BaseModel):
    edit_text: str = Field(min_length=1)


class DashboardSettingsUpdate(BaseModel):
    slack_notifications_enabled: bool | None = None
    slack_channel_id: str | None = None


def _app_tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def _as_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_app_tz())


def _today_start_utc() -> datetime:
    now_local = datetime.now(_app_tz())
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(UTC)


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return _as_local(value).isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _rule_payload(rule: Rule) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "condition_description": rule.condition_description,
        "action_description": rule.action_description,
        "exceptions_note": rule.exceptions_note,
        "structured_conditions": rule.structured_conditions,
        "structured_action": rule.structured_action,
        "agent_scope": rule.agent_scope,
        "extraction_confidence": rule.extraction_confidence,
        "status": rule.status,
        "source_escalation_id": _serialize(rule.source_escalation_id),
        "trigger_count": rule.trigger_count,
        "last_triggered_at": _serialize(rule.last_triggered_at),
        "created_at": _serialize(rule.created_at),
        "updated_at": _serialize(rule.updated_at),
    }


def _escalation_payload(escalation: Escalation) -> dict[str, Any]:
    return {
        "id": str(escalation.id),
        "context": escalation.context,
        "question": escalation.question,
        "metadata": escalation.metadata_,
        "agent_id": escalation.agent_id,
        "status": escalation.status,
        "human_decision": escalation.human_decision,
        "apply_broadly": escalation.apply_broadly,
        "auto_resolved": escalation.auto_resolved,
        "rule_id": _serialize(escalation.rule_id),
        "created_at": _serialize(escalation.created_at),
        "responded_at": _serialize(escalation.responded_at),
    }


def _check_log_payload(log: PolicyCheckLog) -> dict[str, Any]:
    return {
        "id": str(log.id),
        "agent_id": log.agent_id,
        "action": log.action,
        "context": log.context,
        "result": log.result,
        "rule_id": _serialize(log.rule_id),
        "reasoning": log.reasoning,
        "cache_hit": log.cache_hit,
        "created_at": _serialize(log.created_at),
    }


def _conflict_payload(warning: ConflictWarning) -> dict[str, Any]:
    return {
        "existing_rule_id": warning.existing_rule_id,
        "existing_condition": warning.existing_condition,
        "existing_action": warning.existing_action,
        "explanation": warning.explanation,
        "similarity": warning.similarity,
    }


async def _count(session: AsyncSession, statement) -> int:
    return int(await session.scalar(statement) or 0)


def _truncate(value: str | None, length: int) -> str:
    text_value = value or ""
    if len(text_value) <= length:
        return text_value
    return text_value[: length - 1].rstrip() + "..."


def _time_ago(value: datetime | None) -> str:
    if value is None:
        return "-"
    seconds = max(int((datetime.now(_app_tz()) - _as_local(value)).total_seconds()), 0)
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _rule_action(rule: Rule) -> str:
    action = rule.structured_action or {}
    return str(action.get("action") or "proceed")


async def _get_org(session: AsyncSession, org_id: UUID) -> Organization:
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


async def _get_org_escalation(session: AsyncSession, escalation_id: UUID, org_id: UUID) -> Escalation:
    escalation = (
        await session.execute(
            select(Escalation).where(
                Escalation.id == escalation_id,
                Escalation.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if escalation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escalation not found")
    return escalation


async def _get_org_rule(session: AsyncSession, rule_id: UUID, org_id: UUID) -> Rule:
    rule = (
        await session.execute(
            select(Rule).where(
                Rule.id == rule_id,
                Rule.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


async def _similar_decision_payload(session: AsyncSession, escalation: Escalation) -> list[dict[str, Any]]:
    if escalation.context_embedding is None:
        return []
    try:
        decisions = await find_similar_escalations(
            session,
            list(escalation.context_embedding),
            str(escalation.id),
            str(escalation.org_id) if escalation.org_id else None,
        )
    except Exception:
        return []
    return [
        {
            "context": _truncate(str(decision.get("context") or ""), 120),
            "human_decision": decision.get("human_decision") or "responded",
            "time_ago": _time_ago(decision.get("responded_at")),
            "similarity": f"{float(decision.get('similarity') or 0) * 100:.0f}%",
        }
        for decision in decisions
    ]


async def _review_rule_payload(session: AsyncSession, rule: Rule) -> dict[str, Any]:
    warnings = await ConflictService().load_warnings(session, rule)
    return {
        "id": str(rule.id),
        "condition": rule.condition_description,
        "action": rule.action_description,
        "exceptions_note": rule.exceptions_note,
        "structured_conditions": rule.structured_conditions,
        "structured_action": rule.structured_action,
        "confidence": f"{rule.extraction_confidence * 100:.0f}%",
        "status": rule.status,
        "created": _time_ago(rule.created_at),
        "updated": _time_ago(rule.updated_at),
        "conflicts": [_conflict_payload(warning) for warning in warnings],
    }


async def _review_escalation_payload(session: AsyncSession, escalation: Escalation) -> dict[str, Any]:
    rule = await session.get(Rule, escalation.rule_id) if escalation.rule_id else None
    if escalation.finalized_at is not None:
        stage = "finalized"
    elif escalation.status == "pending":
        stage = "decision"
    elif escalation.human_decision and escalation.apply_broadly is None and rule is None:
        stage = "scope"
    elif rule is not None:
        stage = "rule"
    else:
        stage = "decision"

    return {
        "id": str(escalation.id),
        "stage": stage,
        "context": escalation.context,
        "question": escalation.question,
        "metadata": escalation.metadata_,
        "agent_id": escalation.agent_id,
        "status": escalation.status,
        "human_decision": escalation.human_decision,
        "apply_broadly": escalation.apply_broadly,
        "auto_resolved": escalation.auto_resolved,
        "finalized": escalation.finalized_at is not None,
        "finalization_reason": escalation.finalization_reason,
        "created": _time_ago(escalation.created_at),
        "responded": _time_ago(escalation.responded_at),
        "similar_decisions": await _similar_decision_payload(session, escalation),
        "rule": await _review_rule_payload(session, rule) if rule else None,
    }


async def _review_queue_payload(session: AsyncSession, org_id: UUID) -> dict[str, Any]:
    escalations = (
        await session.execute(
            select(Escalation)
            .where(
                Escalation.org_id == org_id,
                Escalation.finalized_at.is_(None),
            )
            .order_by(Escalation.created_at.asc())
            .limit(50)
        )
    ).scalars().all()

    return {
        "items": [await _review_escalation_payload(session, escalation) for escalation in escalations],
    }


async def _overview_data(session: AsyncSession) -> dict[str, Any]:
    today_start = _today_start_utc()
    trend_start = today_start - timedelta(days=6)
    total_decisions_today = await _count(
        session,
        select(func.count())
        .select_from(PolicyCheckLog)
        .where(PolicyCheckLog.created_at >= today_start),
    )
    auto_handled_today = await _count(
        session,
        select(func.count())
        .select_from(PolicyCheckLog)
        .where(
            PolicyCheckLog.created_at >= today_start,
            PolicyCheckLog.rule_id.is_not(None),
        ),
    )
    escalations_today = await _count(
        session,
        select(func.count())
        .select_from(Escalation)
        .where(Escalation.created_at >= today_start),
    )
    autonomy_score = (auto_handled_today / total_decisions_today * 100) if total_decisions_today else 0

    trend_rows = (
        await session.execute(
            text(
                """
                WITH days AS (
                    SELECT generate_series(
                        timezone(:timezone, now())::date - interval '6 days',
                        timezone(:timezone, now())::date,
                        interval '1 day'
                    )::date AS day
                ),
                checks AS (
                    SELECT
                        timezone(:timezone, created_at)::date AS day,
                        COUNT(*) AS total_decisions,
                        COUNT(rule_id) AS auto_handled
                    FROM policy_check_log
                    WHERE created_at >= :trend_start
                    GROUP BY timezone(:timezone, created_at)::date
                ),
                escalations_by_day AS (
                    SELECT timezone(:timezone, created_at)::date AS day, COUNT(*) AS escalations
                    FROM escalations
                    WHERE created_at >= :trend_start
                    GROUP BY timezone(:timezone, created_at)::date
                )
                SELECT
                    days.day,
                    COALESCE(checks.total_decisions, 0) AS total_decisions,
                    COALESCE(checks.auto_handled, 0) AS auto_handled,
                    COALESCE(escalations_by_day.escalations, 0) AS escalations
                FROM days
                LEFT JOIN checks ON checks.day = days.day
                LEFT JOIN escalations_by_day ON escalations_by_day.day = days.day
                ORDER BY days.day DESC
                """
            ),
            {"timezone": settings.app_timezone, "trend_start": trend_start},
        )
    ).mappings().all()
    trend = []
    for row in trend_rows:
        total = int(row["total_decisions"])
        auto = int(row["auto_handled"])
        trend.append(
            {
                "date": row["day"].strftime("%b %-d"),
                "total_decisions": total,
                "auto_handled": auto,
                "escalations": int(row["escalations"]),
                "autonomy": f"{(auto / total * 100) if total else 0:.1f}%",
            }
        )

    active_rules = (
        await session.execute(
            select(Rule)
            .where(Rule.status == "active")
            .order_by(Rule.trigger_count.desc(), Rule.updated_at.desc())
            .limit(5)
        )
    ).scalars().all()
    recent_escalations = (
        await session.execute(select(Escalation).order_by(Escalation.created_at.desc()).limit(5))
    ).scalars().all()
    suggestions = (
        await session.execute(
            select(ConsolidationSuggestion)
            .where(ConsolidationSuggestion.status == "pending")
            .order_by(ConsolidationSuggestion.created_at.desc())
            .limit(5)
        )
    ).scalars().all()
    suggestion_items = []
    for suggestion in suggestions:
        rule_a = await session.get(Rule, suggestion.rule_a_id)
        rule_b = await session.get(Rule, suggestion.rule_b_id)
        suggestion_items.append(
            {
                "id": str(suggestion.id),
                "merged_condition": suggestion.merged_condition,
                "merged_action": suggestion.merged_action,
                "reason": suggestion.reason,
                "created": _time_ago(suggestion.created_at),
                "rule_a": _truncate(rule_a.condition_description, 80) if rule_a else "Rule A",
                "rule_b": _truncate(rule_b.condition_description, 80) if rule_b else "Rule B",
            }
        )

    return {
        "stats": {
            "total_decisions_today": total_decisions_today,
            "auto_handled_today": auto_handled_today,
            "escalations_today": escalations_today,
            "autonomy_score": f"{autonomy_score:.1f}%",
        },
        "trend": trend,
        "active_rules": [
            {
                "id": str(rule.id),
                "condition": _truncate(rule.condition_description, 80),
                "action": _rule_action(rule),
                "trigger_count": rule.trigger_count,
                "last_triggered": _time_ago(rule.last_triggered_at),
            }
            for rule in active_rules
        ],
        "recent_escalations": [
            {
                "id": str(escalation.id),
                "context": _truncate(escalation.context, 100),
                "status": escalation.status,
                "human_decision": escalation.human_decision or "-",
                "time_ago": _time_ago(escalation.created_at),
            }
            for escalation in recent_escalations
        ],
        "suggestions": suggestion_items,
    }


@router.get("/dashboard")
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    data = await _overview_data(session)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_nav": "overview",
            **data,
        },
    )


@router.get("/dashboard/review")
async def dashboard_review(request: Request):
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "active_nav": "review",
        },
    )


@router.get("/dashboard/rules")
async def dashboard_rules(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    status_order = case(
        (Rule.status == "active", 0),
        (Rule.status == "paused", 1),
        (Rule.status.in_(["pending_approval", "pending_edit"]), 2),
        (Rule.status == "archived", 3),
        else_=4,
    )
    rules = (
        await session.execute(select(Rule).order_by(status_order, Rule.trigger_count.desc(), Rule.created_at.desc()))
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "rules.html",
        {
            "active_nav": "rules",
            "rules": [
                {
                    "id": str(rule.id),
                    "condition": rule.condition_description,
                    "action": rule.action_description,
                    "status": rule.status,
                    "confidence": f"{rule.extraction_confidence * 100:.0f}%",
                    "trigger_count": rule.trigger_count,
                    "last_triggered": _time_ago(rule.last_triggered_at),
                    "created": _time_ago(rule.created_at),
                }
                for rule in rules
            ],
        },
    )


@router.get("/dashboard/settings")
async def dashboard_settings(request: Request):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active_nav": "settings",
        },
    )


@router.get("/dashboard/escalations")
async def dashboard_escalations(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    escalations = (
        await session.execute(select(Escalation).order_by(Escalation.created_at.desc()))
    ).scalars().all()
    items = []
    for escalation in escalations:
        rule = await session.get(Rule, escalation.rule_id) if escalation.rule_id else None
        items.append(
            {
                "id": str(escalation.id),
                "time": _time_ago(escalation.created_at),
                "agent_id": escalation.agent_id,
                "context": escalation.context,
                "context_short": _truncate(escalation.context, 100),
                "metadata": escalation.metadata_,
                "status": escalation.status,
                "human_decision": (
                    f"{escalation.human_decision} (auto)" if escalation.auto_resolved and escalation.human_decision else escalation.human_decision or "-"
                ),
                "auto_resolved": escalation.auto_resolved,
                "rule_created": "Yes" if escalation.rule_id else "No",
                "rule": {
                    "id": str(rule.id),
                    "condition": rule.condition_description,
                    "action": rule.action_description,
                    "status": rule.status,
                }
                if rule
                else None,
            }
        )

    return templates.TemplateResponse(
        request,
        "escalations.html",
        {
            "active_nav": "escalations",
            "escalations": items,
        },
    )


@router.get("/dashboard/rules/{rule_id}")
async def dashboard_rule_detail(
    rule_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    rule = await session.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    checks = (
        await session.execute(
            select(PolicyCheckLog)
            .where(PolicyCheckLog.rule_id == rule.id)
            .order_by(PolicyCheckLog.created_at.desc())
        )
    ).scalars().all()
    source_escalation = (
        await session.get(Escalation, rule.source_escalation_id) if rule.source_escalation_id else None
    )

    return templates.TemplateResponse(
        request,
        "rule_detail.html",
        {
            "active_nav": "rules",
            "rule": {
                "id": str(rule.id),
                "condition": rule.condition_description,
                "action": rule.action_description,
                "exceptions_note": rule.exceptions_note,
                "structured_conditions": rule.structured_conditions,
                "structured_action": rule.structured_action,
                "confidence": f"{rule.extraction_confidence * 100:.0f}%",
                "status": rule.status,
                "trigger_count": rule.trigger_count,
                "created": _time_ago(rule.created_at),
                "last_triggered": _time_ago(rule.last_triggered_at),
            },
            "checks": [
                {
                    "id": str(check.id),
                    "time": _time_ago(check.created_at),
                    "agent_id": check.agent_id,
                    "action": check.action,
                    "result": check.result,
                    "reasoning": check.reasoning,
                    "context": check.context,
                }
                for check in checks
            ],
            "source_escalation": {
                "id": str(source_escalation.id),
                "context": source_escalation.context,
                "question": source_escalation.question,
                "metadata": source_escalation.metadata_,
                "agent_id": source_escalation.agent_id,
                "decision": source_escalation.human_decision or "-",
                "time": _time_ago(source_escalation.created_at),
            }
            if source_escalation
            else None,
        },
    )


@router.get("/admin/summary")
async def get_summary(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    total_rules = await _count(session, select(func.count()).select_from(Rule).where(Rule.org_id == auth.org_id))
    active_rules = await _count(
        session,
        select(func.count()).select_from(Rule).where(Rule.status == "active", Rule.org_id == auth.org_id),
    )
    pending_rules = await _count(
        session,
        select(func.count())
        .select_from(Rule)
        .where(Rule.status.in_(["pending_approval", "pending_edit"]), Rule.org_id == auth.org_id),
    )
    total_escalations = await _count(
        session,
        select(func.count()).select_from(Escalation).where(Escalation.org_id == auth.org_id),
    )
    pending_escalations = await _count(
        session,
        select(func.count())
        .select_from(Escalation)
        .where(Escalation.status == "pending", Escalation.org_id == auth.org_id),
    )
    total_checks = await _count(
        session,
        select(func.count()).select_from(PolicyCheckLog).where(PolicyCheckLog.org_id == auth.org_id),
    )
    matched_checks = await _count(
        session,
        select(func.count())
        .select_from(PolicyCheckLog)
        .where(PolicyCheckLog.rule_id.is_not(None), PolicyCheckLog.org_id == auth.org_id),
    )
    unresolved_conflicts = await _count(
        session,
        select(func.count())
        .select_from(RuleConflict)
        .join(Rule, Rule.id == RuleConflict.rule_a_id)
        .where(RuleConflict.resolved.is_(False), Rule.org_id == auth.org_id),
    )
    pending_suggestions = await _count(
        session,
        select(func.count())
        .select_from(ConsolidationSuggestion)
        .where(ConsolidationSuggestion.org_id == auth.org_id, ConsolidationSuggestion.status == "pending"),
    )

    latest_rule = (
        await session.execute(
            select(Rule).where(Rule.org_id == auth.org_id).order_by(Rule.updated_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    latest_escalation = (
        await session.execute(
            select(Escalation).where(Escalation.org_id == auth.org_id).order_by(Escalation.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    latest_check = (
        await session.execute(
            select(PolicyCheckLog)
            .where(PolicyCheckLog.org_id == auth.org_id)
            .order_by(PolicyCheckLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return {
        "totals": {
            "rules": total_rules,
            "active_rules": active_rules,
            "pending_rules": pending_rules,
            "escalations": total_escalations,
            "pending_escalations": pending_escalations,
            "checks": total_checks,
            "matched_checks": matched_checks,
            "unresolved_conflicts": unresolved_conflicts,
            "pending_suggestions": pending_suggestions,
        },
        "latest": {
            "rule_updated_at": _serialize(latest_rule.updated_at) if latest_rule else None,
            "escalation_created_at": _serialize(latest_escalation.created_at) if latest_escalation else None,
            "check_created_at": _serialize(latest_check.created_at) if latest_check else None,
        },
    }


@router.get("/admin/review")
async def get_review_queue(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    return await _review_queue_payload(session, auth.org_id)


@router.post("/admin/review/escalations/{escalation_id}/decision")
async def dashboard_decide_escalation(
    escalation_id: UUID,
    request: DashboardDecisionRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    escalation = await _get_org_escalation(session, escalation_id, auth.org_id)
    try:
        await record_escalation_decision(session, escalation, request.decision)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await session.commit()
    return {"item": await _review_escalation_payload(session, escalation)}


@router.post("/admin/review/escalations/{escalation_id}/apply-broadly")
async def dashboard_apply_broadly(
    escalation_id: UUID,
    request: DashboardApplyBroadlyRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    escalation = await _get_org_escalation(session, escalation_id, auth.org_id)
    try:
        if request.apply_broadly:
            await create_rule_from_escalation(session, escalation)
            await session.commit()
            return {"item": await _review_escalation_payload(session, escalation)}

        await mark_one_time(session, escalation)
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await publish_final_escalation_result(escalation)
    return {"item": await _review_escalation_payload(session, escalation)}


@router.post("/admin/review/rules/{rule_id}/approve")
async def dashboard_approve_rule(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    rule = await _get_org_rule(session, rule_id, auth.org_id)
    approved, warnings, escalation = await approve_rule(session, rule)
    if not approved:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Approving this rule would conflict with an existing active rule.",
                "conflicts": [_conflict_payload(warning) for warning in warnings],
            },
        )

    await session.commit()
    if escalation is not None:
        await publish_final_escalation_result(escalation)
    await publish_rule_created(rule)
    asyncio.create_task(propagate_rule(rule.id, rule.org_id))
    return {
        "rule": await _review_rule_payload(session, rule),
        "item": await _review_escalation_payload(session, escalation) if escalation else None,
    }


@router.post("/admin/review/rules/{rule_id}/edit")
async def dashboard_edit_rule(
    rule_id: UUID,
    request: DashboardRuleEditRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    rule = await _get_org_rule(session, rule_id, auth.org_id)
    try:
        await revise_rule(session, rule, request.edit_text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await session.commit()
    escalation = await session.get(Escalation, rule.source_escalation_id) if rule.source_escalation_id else None
    return {
        "rule": await _review_rule_payload(session, rule),
        "item": await _review_escalation_payload(session, escalation) if escalation else None,
    }


@router.post("/admin/review/rules/{rule_id}/discard")
async def dashboard_discard_rule(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    rule = await _get_org_rule(session, rule_id, auth.org_id)
    escalation = await discard_rule(session, rule)
    await session.commit()
    if escalation is not None:
        await publish_final_escalation_result(escalation)
    return {
        "item": await _review_escalation_payload(session, escalation) if escalation else None,
    }


@router.get("/admin/settings")
async def get_settings(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    org = await _get_org(session, auth.org_id)
    return {
        "organization": {
            "id": str(org.id),
            "name": org.name,
            "slack_channel_id": org.slack_channel_id or "",
            "slack_notifications_enabled": org.slack_notifications_enabled,
            "slack_configured": slack_delivery_available(org),
            "webhook_url": org.webhook_url or "",
        },
        "global_slack_configured": bool(settings.slack_bot_token and settings.slack_channel_id),
    }


@router.patch("/admin/settings")
async def update_settings(
    request: DashboardSettingsUpdate,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    org = await _get_org(session, auth.org_id)
    if request.slack_notifications_enabled is not None:
        org.slack_notifications_enabled = request.slack_notifications_enabled
    if request.slack_channel_id is not None:
        org.slack_channel_id = request.slack_channel_id.strip() or None

    await session.commit()
    return await get_settings(session=session, auth=auth)


@router.get("/admin/rules")
async def get_rules(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
    limit: int = 50,
) -> dict[str, Any]:
    safe_limit = min(max(limit, 1), 100)
    rules = (
        await session.execute(
            select(Rule)
            .where(Rule.org_id == auth.org_id)
            .order_by(Rule.updated_at.desc())
            .limit(safe_limit)
        )
    ).scalars().all()
    return {"items": [_rule_payload(rule) for rule in rules]}


@router.get("/admin/escalations")
async def get_escalations(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
    limit: int = 50,
) -> dict[str, Any]:
    safe_limit = min(max(limit, 1), 100)
    escalations = (
        await session.execute(
            select(Escalation)
            .where(Escalation.org_id == auth.org_id)
            .order_by(Escalation.created_at.desc())
            .limit(safe_limit)
        )
    ).scalars().all()
    return {"items": [_escalation_payload(escalation) for escalation in escalations]}


@router.get("/admin/check-logs")
async def get_check_logs(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
    limit: int = 50,
) -> dict[str, Any]:
    safe_limit = min(max(limit, 1), 100)
    logs = (
        await session.execute(
            select(PolicyCheckLog)
            .where(PolicyCheckLog.org_id == auth.org_id)
            .order_by(PolicyCheckLog.created_at.desc())
            .limit(safe_limit)
        )
    ).scalars().all()
    return {"items": [_check_log_payload(log) for log in logs]}
