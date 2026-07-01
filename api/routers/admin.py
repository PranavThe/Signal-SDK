from __future__ import annotations

import asyncio
import hashlib
import secrets
import string
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.templating import Jinja2Templates

from api.auth import AuthContext, hash_api_key
from api.config import settings
from api.dashboard_auth import (
    DASHBOARD_ACCESS_COOKIE,
    DASHBOARD_API_KEY_HASH_COOKIE,
    DASHBOARD_ORG_ID_COOKIE,
    DashboardOrgContext,
    DashboardUser,
    dashboard_auth_configured,
    ensure_dashboard_membership,
    get_dashboard_org_from_request,
    get_dashboard_user_from_request,
    require_dashboard_org_auth,
    require_dashboard_user,
    select_dashboard_org,
    validate_dashboard_token,
)
from api.database import get_session
from api.models import ApiKey, ConsolidationSuggestion, Escalation, Organization, PolicyCheckLog, Rule, RuleConflict
from api.schemas import RuleDeleteRequest, RuleStatusUpdate
from api.services.billing_service import (
    apply_stripe_event,
    billing_configured,
    billing_is_active,
    construct_webhook_event,
    create_checkout_session,
)
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


class DashboardOrgSelectRequest(BaseModel):
    api_key: str = Field(min_length=1)


class ApiKeyGenerateRequest(BaseModel):
    name: str = Field(default="Dashboard Generated", min_length=1, max_length=100)


class OrganizationSetupRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=200)


def _app_tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def _as_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_app_tz())


def _generate_api_key() -> str:
    """Generate a new API key with the standard prefix and random suffix."""
    KEY_PREFIX = "sk_live_"
    KEY_RANDOM_LENGTH = 32
    alphabet = string.ascii_letters + string.digits
    return KEY_PREFIX + "".join(secrets.choice(alphabet) for _ in range(KEY_RANDOM_LENGTH))


def _hash_api_key(api_key: str) -> str:
    """Hash an API key for secure storage."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


async def _dashboard_template_context(
    request: Request,
    session: AsyncSession,
) -> dict[str, Any] | RedirectResponse:
    user = await get_dashboard_user_from_request(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    current_org = await get_dashboard_org_from_request(request, session, user)
    return {
        "dashboard_user": user,
        "current_org": current_org,
    }


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


async def _delete_org_rules(session: AsyncSession, rule_ids: list[UUID], org_id: UUID) -> list[UUID]:
    found_ids = list(
        (
            await session.execute(
                select(Rule.id).where(
                    Rule.id.in_(rule_ids),
                    Rule.org_id == org_id,
                )
            )
        ).scalars().all()
    )
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


def _settings_payload(org: Organization) -> dict[str, Any]:
    return {
        "organization": {
            "id": str(org.id),
            "name": org.name,
            "slack_channel_id": org.slack_channel_id or "",
            "slack_notifications_enabled": org.slack_notifications_enabled,
            "slack_configured": slack_delivery_available(org),
            "webhook_url": org.webhook_url or "",
        },
        "billing": {
            "status": org.billing_status,
            "active": billing_is_active(org),
            "configured": billing_configured(),
            "stripe_customer_id": org.stripe_customer_id or "",
            "current_period_end": _serialize(org.billing_current_period_end),
        },
        "global_slack_configured": bool(settings.slack_bot_token and settings.slack_channel_id),
    }


async def _empty_overview_data() -> dict[str, Any]:
    return {
        "stats": {
            "total_decisions_today": 0,
            "auto_handled_today": 0,
            "escalations_today": 0,
            "autonomy_score": "0.0%",
        },
        "trend": [],
        "active_rules": [],
        "recent_escalations": [],
        "suggestions": [],
    }


async def _overview_data(session: AsyncSession, org_id: UUID | None) -> dict[str, Any]:
    if org_id is None:
        return await _empty_overview_data()

    today_start = _today_start_utc()
    trend_start = today_start - timedelta(days=6)
    total_decisions_today = await _count(
        session,
        select(func.count())
        .select_from(PolicyCheckLog)
        .where(PolicyCheckLog.created_at >= today_start, PolicyCheckLog.org_id == org_id),
    )
    auto_handled_today = await _count(
        session,
        select(func.count())
        .select_from(PolicyCheckLog)
        .where(
            PolicyCheckLog.created_at >= today_start,
            PolicyCheckLog.rule_id.is_not(None),
            PolicyCheckLog.org_id == org_id,
        ),
    )
    escalations_today = await _count(
        session,
        select(func.count())
        .select_from(Escalation)
        .where(Escalation.created_at >= today_start, Escalation.org_id == org_id),
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
                      AND org_id = CAST(:org_id AS uuid)
                    GROUP BY timezone(:timezone, created_at)::date
                ),
                escalations_by_day AS (
                    SELECT timezone(:timezone, created_at)::date AS day, COUNT(*) AS escalations
                    FROM escalations
                    WHERE created_at >= :trend_start
                      AND org_id = CAST(:org_id AS uuid)
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
            {"timezone": settings.app_timezone, "trend_start": trend_start, "org_id": str(org_id)},
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
            .where(Rule.status == "active", Rule.org_id == org_id)
            .order_by(Rule.trigger_count.desc(), Rule.updated_at.desc())
            .limit(5)
        )
    ).scalars().all()
    recent_escalations = (
        await session.execute(
            select(Escalation)
            .where(Escalation.org_id == org_id)
            .order_by(Escalation.created_at.desc())
            .limit(5)
        )
    ).scalars().all()
    suggestions = (
        await session.execute(
            select(ConsolidationSuggestion)
            .where(ConsolidationSuggestion.status == "pending", ConsolidationSuggestion.org_id == org_id)
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


@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "supabase_configured": dashboard_auth_configured(),
        },
    )


@router.get("/dashboard/auth/config")
async def dashboard_auth_config() -> dict[str, Any]:
    return {
        "configured": dashboard_auth_configured(),
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
    }


@router.post("/dashboard/session")
async def create_dashboard_session(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing dashboard token")

    user = await validate_dashboard_token(token)
    response.set_cookie(
        DASHBOARD_ACCESS_COOKIE,
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return {"email": user.email, "user_id": user.user_id}


@router.post("/dashboard/logout")
async def logout_dashboard(response: Response) -> dict[str, bool]:
    response.delete_cookie(DASHBOARD_ACCESS_COOKIE)
    response.delete_cookie(DASHBOARD_API_KEY_HASH_COOKIE)
    response.delete_cookie(DASHBOARD_ORG_ID_COOKIE)
    return {"ok": True}


@router.post("/dashboard/org-session")
async def select_dashboard_organization(
    request: Request,
    response: Response,
    payload: DashboardOrgSelectRequest,
    session: AsyncSession = Depends(get_session),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    org = await select_dashboard_org(session, payload.api_key, dashboard_user)
    await session.commit()
    response.set_cookie(
        DASHBOARD_API_KEY_HASH_COOKIE,
        hash_api_key(payload.api_key.strip()),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    response.set_cookie(
        DASHBOARD_ORG_ID_COOKIE,
        str(org.org_id),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return {
        "organization": {
            "id": str(org.org_id),
            "name": org.org_name,
            "key_prefix": org.key_prefix,
        }
    }


@router.get("/dashboard")
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    template_context = await _dashboard_template_context(request, session)
    if isinstance(template_context, RedirectResponse):
        return template_context
    current_org = template_context["current_org"]
    data = await _overview_data(session, current_org.org_id if current_org else None)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_nav": "overview",
            **template_context,
            **data,
        },
    )


@router.get("/dashboard/review")
async def dashboard_review(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    template_context = await _dashboard_template_context(request, session)
    if isinstance(template_context, RedirectResponse):
        return template_context
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "active_nav": "review",
            **template_context,
        },
    )


@router.get("/dashboard/rules")
async def dashboard_rules(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    template_context = await _dashboard_template_context(request, session)
    if isinstance(template_context, RedirectResponse):
        return template_context
    current_org = template_context["current_org"]
    status_order = case(
        (Rule.status == "active", 0),
        (Rule.status == "paused", 1),
        (Rule.status.in_(["pending_approval", "pending_edit"]), 2),
        (Rule.status == "archived", 3),
        else_=4,
    )
    rules = []
    if current_org:
        rules = (
            await session.execute(
                select(Rule)
                .where(Rule.org_id == current_org.org_id)
                .order_by(status_order, Rule.trigger_count.desc(), Rule.created_at.desc())
            )
        ).scalars().all()
    return templates.TemplateResponse(
        request,
        "rules.html",
        {
            "active_nav": "rules",
            **template_context,
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
async def dashboard_settings(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    template_context = await _dashboard_template_context(request, session)
    if isinstance(template_context, RedirectResponse):
        return template_context
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active_nav": "settings",
            **template_context,
        },
    )


@router.get("/dashboard/escalations")
async def dashboard_escalations(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    template_context = await _dashboard_template_context(request, session)
    if isinstance(template_context, RedirectResponse):
        return template_context
    current_org = template_context["current_org"]
    escalations = []
    if current_org:
        escalations = (
            await session.execute(
                select(Escalation)
                .where(Escalation.org_id == current_org.org_id)
                .order_by(Escalation.created_at.desc())
            )
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
            **template_context,
            "escalations": items,
        },
    )


@router.get("/dashboard/rules/{rule_id}")
async def dashboard_rule_detail(
    rule_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    template_context = await _dashboard_template_context(request, session)
    if isinstance(template_context, RedirectResponse):
        return template_context
    current_org = template_context["current_org"]
    if current_org is None:
        return RedirectResponse(url="/dashboard/rules", status_code=status.HTTP_303_SEE_OTHER)

    rule = (
        await session.execute(select(Rule).where(Rule.id == rule_id, Rule.org_id == current_org.org_id))
    ).scalar_one_or_none()
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
            **template_context,
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
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
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
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    return await _review_queue_payload(session, auth.org_id)


@router.post("/admin/review/escalations/{escalation_id}/decision")
async def dashboard_decide_escalation(
    escalation_id: UUID,
    request: DashboardDecisionRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
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
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
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
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
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
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
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
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
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
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    org = await _get_org(session, auth.org_id)
    return _settings_payload(org)


@router.patch("/admin/settings")
async def update_settings(
    request: DashboardSettingsUpdate,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    org = await _get_org(session, auth.org_id)
    if request.slack_notifications_enabled is not None:
        org.slack_notifications_enabled = request.slack_notifications_enabled
    if request.slack_channel_id is not None:
        org.slack_channel_id = request.slack_channel_id.strip() or None

    await session.commit()
    return _settings_payload(org)


@router.post("/admin/setup")
async def setup_organization(
    request: OrganizationSetupRequest,
    http_request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    organization_name = request.organization_name.strip()
    if not organization_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Organization name is required.")

    org = Organization(name=organization_name)
    session.add(org)
    await session.flush()
    await ensure_dashboard_membership(session, dashboard_user, org, role="owner")
    await session.commit()

    response.delete_cookie(DASHBOARD_API_KEY_HASH_COOKIE)
    response.set_cookie(
        DASHBOARD_ORG_ID_COOKIE,
        str(org.id),
        httponly=True,
        secure=http_request.url.scheme == "https",
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return {
        "organization": {
            "id": str(org.id),
            "name": org.name,
        },
        "settings": _settings_payload(org),
        "message": "Workspace created. Start your subscription to create your first API key.",
    }


@router.post("/admin/api-keys/generate")
async def generate_api_key(
    request: ApiKeyGenerateRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    """Generate a new API key for the authenticated organization."""
    _ = dashboard_user
    org = await _get_org(session, auth.org_id)
    if not billing_is_active(org):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": "Start your subscription before creating API keys.",
                "billing_status": org.billing_status,
            },
        )

    api_key = _generate_api_key()
    record = ApiKey(
        org_id=auth.org_id,
        key_hash=_hash_api_key(api_key),
        key_prefix=api_key[:8],
        name=request.name,
    )
    session.add(record)
    await session.commit()

    return {
        "api_key": api_key,
        "key_prefix": api_key[:8],
        "name": request.name,
        "created_at": _serialize(record.created_at),
        "message": "API key generated successfully. This is the only time you will see the full key. Save it securely.",
    }


@router.get("/admin/api-keys")
async def list_api_keys(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    """List all API keys for the authenticated organization (without the actual keys)."""
    _ = dashboard_user
    api_keys = (
        await session.execute(
            select(ApiKey)
            .where(ApiKey.org_id == auth.org_id)
            .order_by(ApiKey.created_at.desc())
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(key.id),
                "name": key.name,
                "key_prefix": key.key_prefix,
                "created_at": _serialize(key.created_at),
                "last_used_at": _serialize(key.last_used_at),
            }
            for key in api_keys
        ]
    }


@router.post("/admin/billing/checkout")
async def start_billing_checkout(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, str]:
    org = await _get_org(session, auth.org_id)
    url = await create_checkout_session(org, dashboard_user.email)
    return {"url": url}


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    body = await request.body()
    event = construct_webhook_event(body, stripe_signature)
    updated = await apply_stripe_event(session, event)
    if updated:
        await session.commit()
    return {"received": True}


@router.get("/admin/rules")
async def get_rules(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
    limit: int = 50,
) -> dict[str, Any]:
    _ = dashboard_user
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


@router.patch("/admin/rules/{rule_id}")
async def update_dashboard_rule_status(
    rule_id: UUID,
    request: RuleStatusUpdate,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, str]:
    _ = dashboard_user
    rule = await _get_org_rule(session, rule_id, auth.org_id)

    if request.status == "active":
        conflict_warnings = await ConflictService().detect_activation_conflicts(session, rule)
        if conflict_warnings:
            await session.flush()
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Activating this rule would conflict with an existing active rule.",
                    "conflicts": [_conflict_payload(warning) for warning in conflict_warnings],
                },
            )

    rule.status = request.status
    rule.updated_at = datetime.now(UTC)
    await session.commit()
    return {"rule_id": str(rule.id), "status": rule.status}


@router.post("/admin/rules/delete")
async def delete_dashboard_rules(
    request: RuleDeleteRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, object]:
    _ = dashboard_user
    deleted = await _delete_org_rules(session, request.rule_ids, auth.org_id)
    return {"deleted": [str(rule_id) for rule_id in deleted], "count": len(deleted)}


@router.get("/admin/escalations")
async def get_escalations(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
    limit: int = 50,
) -> dict[str, Any]:
    _ = dashboard_user
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
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
    limit: int = 50,
) -> dict[str, Any]:
    _ = dashboard_user
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
