from __future__ import annotations

import asyncio
import hashlib
import logging
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
from sqlalchemy.exc import SQLAlchemyError
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
    clear_dashboard_cookies,
    dashboard_auth_configured,
    ensure_dashboard_account,
    ensure_dashboard_membership,
    get_dashboard_org_from_request,
    get_dashboard_user_from_request,
    require_dashboard_org_auth,
    require_dashboard_user,
    select_dashboard_org,
    select_dashboard_org_by_id,
    validate_dashboard_token,
)
from api.database import get_session
from api.models import (
    Account,
    ApiKey,
    ConsolidationSuggestion,
    ContextField,
    ContextFieldAlias,
    DashboardOrgMembership,
    Escalation,
    Feedback,
    HistoricalDecisionImport,
    HistoricalRuleProposal,
    Organization,
    PolicyCheckLog,
    Rule,
    RuleComment,
    RuleConflict,
    RuleVersion,
)
from api.plans import PLANS, effective_plan, normalize_tier, plan_for_tier, plan_payload
from api.schemas import RuleDeleteRequest, RuleStatusUpdate
from api.services.billing_service import (
    apply_stripe_event,
    billing_configured,
    billing_is_active,
    construct_webhook_event,
    create_checkout_session,
)
from api.services.conflict_service import ConflictService, ConflictWarning
from api.services.context_schema_service import ContextSchemaService
from api.services.escalation_pipeline import slack_delivery_available
from api.services.lifecycle_service import run_consolidation
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
from api.services.rule_analytics_service import RuleAnalyticsService
from api.services.rule_import_export_service import RuleImportExportService
from api.services.rule_testing_service import RuleTestingService
from api.services.semantic_service import find_similar_escalations
from api.background_tasks import safe_background_task


router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="api/templates")
logger = logging.getLogger(__name__)



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
    org_id: UUID | None = None
    api_key: str | None = None


class ApiKeyGenerateRequest(BaseModel):
    name: str = Field(default="Dashboard Generated", min_length=1, max_length=100)


class DashboardBulkRuleStatusUpdate(BaseModel):
    rule_ids: list[UUID]
    status: Literal["active", "paused", "archived"]


class DashboardRuleImportRequest(BaseModel):
    json_data: str
    skip_duplicates: bool = True


class DashboardAddCommentRequest(BaseModel):
    comment_text: str = Field(min_length=1, max_length=5000)


class DashboardRuleTestRequest(BaseModel):
    test_context: dict[str, Any]


class DashboardEscalationQuickDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]


class DashboardEscalationTagsRequest(BaseModel):
    tags: list[str]


class OrganizationSetupRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=200)


class BillingCheckoutRequest(BaseModel):
    tier: Literal["pro", "scale"] = "pro"


class FeedbackSubmitRequest(BaseModel):
    feedback_text: str = Field(min_length=1, max_length=5000)
    category: Literal["bug", "feature", "general", "billing"] = "general"
    page_url: str | None = None


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
        login_url = "/login?session_expired=1" if request.cookies.get(DASHBOARD_ACCESS_COOKIE) else "/login"
        response = RedirectResponse(url=login_url, status_code=status.HTTP_303_SEE_OTHER)
        clear_dashboard_cookies(response)
        return response
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
        "normalized_context": escalation.normalized_context,
        "question": escalation.question,
        "metadata": escalation.metadata_,
        "normalized_context": escalation.normalized_context,
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


def _activity_item_payload(kind: str, item: Any, rule: Rule | None = None) -> dict[str, Any]:
    if kind == "check":
        matched = item.rule_id is not None
        return {
            "id": str(item.id),
            "kind": "Auto-handled" if matched else "Checked",
            "tone": "success" if matched else "neutral",
            "title": f"{item.action} by {item.agent_id}",
            "summary": item.reasoning,
            "time": _time_ago(item.created_at),
            "created_at": _serialize(item.created_at),
            "rule": {
                "id": str(rule.id),
                "condition": rule.condition_description,
                "action": rule.action_description,
            }
            if rule
            else None,
            "context": item.context,
        }
    if kind == "escalation":
        return {
            "id": str(item.id),
            "kind": "Escalated" if item.finalized_at is None else "Resolved",
            "tone": "warning" if item.finalized_at is None else "neutral",
            "title": item.question,
            "summary": item.context,
            "time": _time_ago(item.created_at),
            "created_at": _serialize(item.created_at),
            "agent_id": item.agent_id,
            "status": item.status,
            "human_decision": item.human_decision,
            "rule_id": _serialize(item.rule_id),
            "context": item.metadata_,
        }
    return {
        "id": str(item.id),
        "kind": "Rule created" if item.status == "active" else "Rule updated",
        "tone": "success" if item.status == "active" else "neutral",
        "title": item.condition_description,
        "summary": item.action_description,
        "time": _time_ago(item.created_at),
        "created_at": _serialize(item.created_at),
        "status": item.status,
        "rule": {
            "id": str(item.id),
            "condition": item.condition_description,
            "action": item.action_description,
        },
        "context": item.structured_conditions,
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


def _dashboard_rule_payload(rule: Rule) -> dict[str, Any]:
    return {
        **_rule_payload(rule),
        "condition": rule.condition_description,
        "action": rule.action_description,
        "confidence": f"{rule.extraction_confidence * 100:.0f}%",
        "trigger_count": rule.trigger_count,
        "last_triggered": _time_ago(rule.last_triggered_at),
        "created": _time_ago(rule.created_at),
        "updated": _time_ago(rule.updated_at),
    }


async def _rule_conflict_counts(session: AsyncSession, rules: list[Rule]) -> dict[UUID, int]:
    rule_ids = {rule.id for rule in rules}
    if not rule_ids:
        return {}
    conflicts = (
        await session.execute(
            select(RuleConflict).where(
                RuleConflict.resolved.is_(False),
                or_(
                    RuleConflict.rule_a_id.in_(rule_ids),
                    RuleConflict.rule_b_id.in_(rule_ids),
                ),
            )
        )
    ).scalars().all()
    counts = {rule_id: 0 for rule_id in rule_ids}
    for conflict in conflicts:
        if conflict.rule_a_id in counts:
            counts[conflict.rule_a_id] += 1
        if conflict.rule_b_id in counts:
            counts[conflict.rule_b_id] += 1
    return counts


def _dashboard_escalation_payload(escalation: Escalation, rule: Rule | None = None) -> dict[str, Any]:
    decision = escalation.human_decision or "-"
    if escalation.auto_resolved and escalation.human_decision:
        decision = f"{escalation.human_decision} (auto)"
    return {
        **_escalation_payload(escalation),
        "time": _time_ago(escalation.created_at),
        "context_short": _truncate(escalation.context, 100),
        "human_decision": decision,
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


def _source_escalation_payload(escalation: Escalation | None) -> dict[str, Any] | None:
    if escalation is None:
        return None
    return {
        "id": str(escalation.id),
        "context": escalation.context,
        "question": escalation.question,
        "metadata": escalation.metadata_,
        "agent_id": escalation.agent_id,
        "decision": escalation.human_decision or "-",
        "time": _time_ago(escalation.created_at),
    }


async def _get_org(session: AsyncSession, org_id: UUID) -> Organization:
    org = await session.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


async def _get_account_for_user(session: AsyncSession, dashboard_user: DashboardUser) -> Account:
    account = await ensure_dashboard_account(session, dashboard_user)
    await session.flush()
    return account


async def _organizations_for_account(session: AsyncSession, account: Account) -> list[Organization]:
    return (
        await session.execute(
            select(Organization)
            .where(Organization.account_id == account.id)
            .order_by(Organization.created_at.asc(), Organization.name.asc())
        )
    ).scalars().all()


async def _api_key_count(session: AsyncSession, org_id: UUID) -> int:
    return await _count(
        session,
        select(func.count()).select_from(ApiKey).where(ApiKey.org_id == org_id),
    )


async def _delete_organization_data(session: AsyncSession, org_id: UUID) -> None:
    rule_ids = list((await session.execute(select(Rule.id).where(Rule.org_id == org_id))).scalars().all())

    if rule_ids:
        await session.execute(update(Escalation).where(Escalation.rule_id.in_(rule_ids)).values(rule_id=None))
        await session.execute(update(Rule).where(Rule.id.in_(rule_ids)).values(source_escalation_id=None))
        await session.execute(delete(RuleComment).where(RuleComment.rule_id.in_(rule_ids)))
        await session.execute(delete(RuleVersion).where(RuleVersion.rule_id.in_(rule_ids)))
        await session.execute(
            delete(RuleConflict).where(
                or_(
                    RuleConflict.rule_a_id.in_(rule_ids),
                    RuleConflict.rule_b_id.in_(rule_ids),
                )
            )
        )
        await session.execute(
            delete(ConsolidationSuggestion).where(
                or_(
                    ConsolidationSuggestion.org_id == org_id,
                    ConsolidationSuggestion.rule_a_id.in_(rule_ids),
                    ConsolidationSuggestion.rule_b_id.in_(rule_ids),
                )
            )
        )
    else:
        await session.execute(delete(ConsolidationSuggestion).where(ConsolidationSuggestion.org_id == org_id))

    await session.execute(delete(PolicyCheckLog).where(PolicyCheckLog.org_id == org_id))
    await session.execute(delete(Escalation).where(Escalation.org_id == org_id))
    await session.execute(delete(Rule).where(Rule.org_id == org_id))
    await session.execute(delete(HistoricalRuleProposal).where(HistoricalRuleProposal.org_id == org_id))
    await session.execute(delete(HistoricalDecisionImport).where(HistoricalDecisionImport.org_id == org_id))
    await session.execute(delete(ContextFieldAlias).where(ContextFieldAlias.org_id == org_id))
    await session.execute(delete(ContextField).where(ContextField.org_id == org_id))
    await session.execute(delete(Feedback).where(Feedback.org_id == org_id))
    await session.execute(delete(ApiKey).where(ApiKey.org_id == org_id))
    await session.execute(delete(DashboardOrgMembership).where(DashboardOrgMembership.org_id == org_id))
    await session.execute(delete(Organization).where(Organization.id == org_id))


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
        "source_escalation": _source_escalation_payload(escalation),
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


async def _rule_detail_payload(session: AsyncSession, rule: Rule, org_id: UUID) -> dict[str, Any]:
    checks = (
        await session.execute(
            select(PolicyCheckLog)
            .where(PolicyCheckLog.rule_id == rule.id, PolicyCheckLog.org_id == org_id)
            .order_by(PolicyCheckLog.created_at.desc())
        )
    ).scalars().all()
    source_escalation = (
        await session.get(Escalation, rule.source_escalation_id) if rule.source_escalation_id else None
    )

    return {
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
        "source_escalation": _source_escalation_payload(source_escalation)
        if source_escalation and source_escalation.org_id == org_id
        else None,
    }


async def _settings_payload(
    session: AsyncSession,
    account: Account,
    org: Organization | None,
) -> dict[str, Any]:
    organizations = await _organizations_for_account(session, account)
    selected_org = org
    current_plan = plan_for_tier(account.plan_tier)
    active_plan = effective_plan(account.plan_tier, account.billing_status)
    org_count = len(organizations)
    api_key_count = await _api_key_count(session, selected_org.id) if selected_org else 0
    api_key_limit = active_plan.api_keys_per_org

    return {
        "account": {
            "id": str(account.id),
            "name": account.name,
            "owner_email": account.owner_email or "",
            "plan_tier": normalize_tier(account.plan_tier),
            "effective_tier": active_plan.tier,
        },
        "plans": [
            plan_payload(
                plan,
                current=plan.tier == normalize_tier(account.plan_tier),
                effective=plan.tier == active_plan.tier,
            )
            for plan in PLANS.values()
        ],
        "plan": {
            **plan_payload(active_plan, current=active_plan.tier == current_plan.tier, effective=True),
            "configured_tier": current_plan.tier,
            "organizations_used": org_count,
            "can_create_organization": org_count < active_plan.org_limit,
        },
        "organizations": [
            {
                "id": str(item.id),
                "name": item.name,
                "selected": bool(selected_org and item.id == selected_org.id),
                "slack_notifications_enabled": item.slack_notifications_enabled,
                "slack_configured": slack_delivery_available(item),
                "created_at": _serialize(item.created_at),
            }
            for item in organizations
        ],
        "organization": {
            "id": str(selected_org.id),
            "name": selected_org.name,
            "slack_channel_id": selected_org.slack_channel_id or "",
            "slack_notifications_enabled": selected_org.slack_notifications_enabled,
            "slack_configured": slack_delivery_available(selected_org),
            "webhook_url": selected_org.webhook_url or "",
        }
        if selected_org
        else None,
        "api_key_limits": {
            "count": api_key_count,
            "limit": api_key_limit,
            "can_create": selected_org is not None and api_key_count < api_key_limit,
        },
        "billing": {
            "status": account.billing_status,
            "active": billing_is_active(account),
            "configured": billing_configured(),
            "stripe_customer_id": account.stripe_customer_id or "",
            "current_period_end": _serialize(account.billing_current_period_end),
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
            "pending_review": 0,
            "pending_rules": 0,
            "week_total_decisions": 0,
            "week_auto_handled": 0,
            "week_escalations": 0,
            "week_autonomy_score": "0.0%",
        },
        "health_summary": "No agent decisions have been recorded yet.",
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

    # Count normal auto-handled (rules matched during policy checks)
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

    # Count retroactively auto-resolved escalations (escalations resolved when a new rule was created)
    retroactive_auto_handled_today = await _count(
        session,
        select(func.count())
        .select_from(Escalation)
        .where(
            Escalation.created_at >= today_start,
            Escalation.org_id == org_id,
            Escalation.auto_resolved == True,
        ),
    )

    # Count manual escalations (escalations that required human decision)
    manual_escalations_today = await _count(
        session,
        select(func.count())
        .select_from(Escalation)
        .where(
            Escalation.created_at >= today_start,
            Escalation.org_id == org_id,
            (Escalation.auto_resolved == False) | (Escalation.auto_resolved.is_(None)),
        ),
    )

    # Combine both types of auto-handling
    total_auto_handled_today = auto_handled_today + retroactive_auto_handled_today

    # Total decisions = auto-handled (both types) + manual escalations
    total_decisions_today = total_auto_handled_today + manual_escalations_today
    autonomy_score = (total_auto_handled_today / total_decisions_today * 100) if total_decisions_today else 0

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
                    SELECT
                        timezone(:timezone, created_at)::date AS day,
                        COUNT(*) FILTER (WHERE auto_resolved = true) AS retroactive_auto_handled,
                        COUNT(*) FILTER (WHERE auto_resolved = false OR auto_resolved IS NULL) AS manual_escalations
                    FROM escalations
                    WHERE created_at >= :trend_start
                      AND org_id = CAST(:org_id AS uuid)
                    GROUP BY timezone(:timezone, created_at)::date
                )
                SELECT
                    days.day,
                    COALESCE(checks.total_decisions, 0) AS total_decisions,
                    COALESCE(checks.auto_handled, 0) AS auto_handled,
                    COALESCE(escalations_by_day.retroactive_auto_handled, 0) AS retroactive_auto_handled,
                    COALESCE(escalations_by_day.manual_escalations, 0) AS manual_escalations
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
        auto = int(row["auto_handled"])
        retroactive_auto = int(row["retroactive_auto_handled"])
        manual_escalations = int(row["manual_escalations"])
        # Combine both types of auto-handling
        total_auto_handled = auto + retroactive_auto
        # Total decisions = auto-handled (both types) + manual escalations
        total = total_auto_handled + manual_escalations
        trend.append(
            {
                "date": row["day"].strftime("%b %-d"),
                "total_decisions": total,
                "auto_handled": total_auto_handled,
                "escalations": manual_escalations,
                "autonomy": f"{(total_auto_handled / total * 100) if total else 0:.1f}%",
                "autonomy_value": round((total_auto_handled / total * 100) if total else 0, 1),
            }
        )

    week_total_decisions = sum(int(day["total_decisions"]) for day in trend)
    week_auto_handled = sum(int(day["auto_handled"]) for day in trend)
    week_escalations = sum(int(day["escalations"]) for day in trend)
    week_autonomy_score = (week_auto_handled / week_total_decisions * 100) if week_total_decisions else 0

    pending_review = await _count(
        session,
        select(func.count())
        .select_from(Escalation)
        .where(Escalation.finalized_at.is_(None), Escalation.org_id == org_id),
    )
    pending_rules = await _count(
        session,
        select(func.count())
        .select_from(Rule)
        .where(Rule.status.in_(["pending_approval", "pending_edit"]), Rule.org_id == org_id),
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

    # Batch fetch rules to avoid N+1 queries
    rule_ids = []
    for suggestion in suggestions:
        if suggestion.rule_a_id:
            rule_ids.append(suggestion.rule_a_id)
        if suggestion.rule_b_id:
            rule_ids.append(suggestion.rule_b_id)

    rules_by_id = {}
    if rule_ids:
        rules = (
            await session.execute(select(Rule).where(Rule.id.in_(rule_ids)))
        ).scalars().all()
        rules_by_id = {rule.id: rule for rule in rules}

    suggestion_items = []
    for suggestion in suggestions:
        rule_a = rules_by_id.get(suggestion.rule_a_id)
        rule_b = rules_by_id.get(suggestion.rule_b_id)
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

    result = {
        "stats": {
            "total_decisions_today": total_decisions_today,
            "auto_handled_today": total_auto_handled_today,
            "escalations_today": manual_escalations_today,
            "autonomy_score": f"{autonomy_score:.1f}%",
            "pending_review": pending_review,
            "pending_rules": pending_rules,
            "week_total_decisions": week_total_decisions,
            "week_auto_handled": week_auto_handled,
            "week_escalations": week_escalations,
            "week_autonomy_score": f"{week_autonomy_score:.1f}%",
        },
        "health_summary": (
            f"Your agent auto-handled {week_autonomy_score:.1f}% of decisions this week, "
            f"escalated {week_escalations}, and has {pending_review + pending_rules} item"
            f"{'' if pending_review + pending_rules == 1 else 's'} waiting for review."
        ),
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

    return result


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
    clear_dashboard_cookies(response)
    return {"ok": True}


@router.post("/dashboard/org-session")
async def select_dashboard_organization(
    request: Request,
    response: Response,
    payload: DashboardOrgSelectRequest,
    session: AsyncSession = Depends(get_session),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    if payload.org_id is not None:
        org = await select_dashboard_org_by_id(session, payload.org_id, dashboard_user)
    elif payload.api_key:
        org = await select_dashboard_org(session, payload.api_key, dashboard_user)
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose an organization.",
        )
    await session.commit()
    response.delete_cookie(DASHBOARD_API_KEY_HASH_COOKIE)
    if payload.api_key:
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
    account = await _get_account_for_user(session, template_context["dashboard_user"])
    current_org = template_context["current_org"]
    org = await session.get(Organization, current_org.org_id) if current_org else None
    data = await _settings_payload(session, account, org)
    return templates.TemplateResponse(
        request,
        "account_dashboard.html",
        {
            "active_nav": "organizations",
            "nav_scope": "account",
            **template_context,
            "account_data": data,
        },
    )


@router.get("/dashboard/account")
async def dashboard_account_settings(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    template_context = await _dashboard_template_context(request, session)
    if isinstance(template_context, RedirectResponse):
        return template_context
    account = await _get_account_for_user(session, template_context["dashboard_user"])
    current_org = template_context["current_org"]
    org = await session.get(Organization, current_org.org_id) if current_org else None
    data = await _settings_payload(session, account, org)
    return templates.TemplateResponse(
        request,
        "account_settings.html",
        {
            "active_nav": "account_settings",
            "nav_scope": "account",
            **template_context,
            "account_data": data,
        },
    )


@router.get("/dashboard/overview")
async def dashboard_overview(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    template_context = await _dashboard_template_context(request, session)
    if isinstance(template_context, RedirectResponse):
        return template_context
    current_org = template_context["current_org"]
    if current_org is None:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    data = await _overview_data(session, current_org.org_id if current_org else None)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_nav": "overview",
            "nav_scope": "org",
            **template_context,
            **data,
            "overview": data,
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
            "nav_scope": "org",
            **template_context,
        },
    )


@router.get("/dashboard/activity")
async def dashboard_activity(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    template_context = await _dashboard_template_context(request, session)
    if isinstance(template_context, RedirectResponse):
        return template_context
    return templates.TemplateResponse(
        request,
        "activity.html",
        {
            "active_nav": "activity",
            "nav_scope": "org",
            **template_context,
        },
    )


@router.get("/dashboard/context")
async def dashboard_context(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    template_context = await _dashboard_template_context(request, session)
    if isinstance(template_context, RedirectResponse):
        return template_context
    return templates.TemplateResponse(
        request,
        "context.html",
        {
            "active_nav": "context",
            "nav_scope": "org",
            **template_context,
        },
    )


@router.get("/dashboard/training")
async def dashboard_training(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    template_context = await _dashboard_template_context(request, session)
    if isinstance(template_context, RedirectResponse):
        return template_context
    return templates.TemplateResponse(
        request,
        "training.html",
        {
            "active_nav": "training",
            "nav_scope": "org",
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
    conflict_counts = await _rule_conflict_counts(session, rules)
    return templates.TemplateResponse(
        request,
        "rules.html",
        {
            "active_nav": "rules",
            "nav_scope": "org",
            **template_context,
            "rules": [
                {
                    **_dashboard_rule_payload(rule),
                    "conflict_count": conflict_counts.get(rule.id, 0),
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
            "nav_scope": "org",
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
                .limit(100)  # Limit to prevent OOM on orgs with many escalations
            )
        ).scalars().all()

    # Batch fetch rules to avoid N+1 queries
    rule_ids = [e.rule_id for e in escalations if e.rule_id]
    rules_by_id = {}
    if rule_ids:
        rules = (await session.execute(select(Rule).where(Rule.id.in_(rule_ids)))).scalars().all()
        rules_by_id = {rule.id: rule for rule in rules}

    items = []
    for escalation in escalations:
        rule = rules_by_id.get(escalation.rule_id) if escalation.rule_id else None
        items.append(_dashboard_escalation_payload(escalation, rule))

    return templates.TemplateResponse(
        request,
        "escalations.html",
        {
            "active_nav": "escalations",
            "nav_scope": "org",
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

    detail = await _rule_detail_payload(session, rule, current_org.org_id)

    return templates.TemplateResponse(
        request,
        "rule_detail.html",
        {
            "active_nav": "rules",
            "nav_scope": "org",
            **template_context,
            **detail,
            "detail": detail,
        },
    )


@router.get("/admin/overview")
async def get_overview(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    return await _overview_data(session, auth.org_id)


@router.post("/admin/consolidation/run")
async def run_dashboard_consolidation(
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, int]:
    _ = dashboard_user
    return await run_consolidation(org_id=auth.org_id, max_pairs_per_org=50)


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
    safe_background_task(propagate_rule(rule.id, rule.org_id), "propagate_rule")
    safe_background_task(run_consolidation(org_id=auth.org_id, max_pairs_per_org=50), "run_consolidation")
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
        await session.refresh(escalation)
        await publish_final_escalation_result(escalation)
        return {
            "item": await _review_escalation_payload(session, escalation),
        }
    return {"item": None}


@router.get("/admin/settings")
async def get_settings(
    request: Request,
    session: AsyncSession = Depends(get_session),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    account = await _get_account_for_user(session, dashboard_user)
    await session.commit()
    org_context = await get_dashboard_org_from_request(request, session, dashboard_user)
    org = await session.get(Organization, org_context.org_id) if org_context else None
    return await _settings_payload(session, account, org)


@router.patch("/admin/settings")
async def update_settings(
    request: DashboardSettingsUpdate,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    account = await _get_account_for_user(session, dashboard_user)
    org = await _get_org(session, auth.org_id)
    if request.slack_notifications_enabled is not None:
        org.slack_notifications_enabled = request.slack_notifications_enabled
    if request.slack_channel_id is not None:
        org.slack_channel_id = request.slack_channel_id.strip() or None

    await session.commit()
    return await _settings_payload(session, account, org)


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

    account = await _get_account_for_user(session, dashboard_user)
    organizations = await _organizations_for_account(session, account)
    active_plan = effective_plan(account.plan_tier, account.billing_status)
    if len(organizations) >= active_plan.org_limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": f"Your {active_plan.name} plan includes {active_plan.org_limit} organization"
                f"{'' if active_plan.org_limit == 1 else 's'}. Upgrade to create more.",
                "plan_tier": active_plan.tier,
                "org_limit": active_plan.org_limit,
            },
        )

    org = Organization(name=organization_name, account_id=account.id)
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
        "settings": await _settings_payload(session, account, org),
        "message": "Organization created. You can create API keys for it below.",
    }


@router.delete("/admin/organizations/{org_id}")
async def delete_organization(
    org_id: UUID,
    http_request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    account = await _get_account_for_user(session, dashboard_user)
    org = await session.get(Organization, org_id)
    if org is None or org.account_id != account.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    org_name = org.name

    try:
        await _delete_organization_data(session, org_id)
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.exception("Failed to delete organization %s", org_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not delete organization because related data could not be fully removed. Please try again.",
        ) from exc

    selected_org_id = http_request.cookies.get(DASHBOARD_ORG_ID_COOKIE)
    if selected_org_id == str(org_id):
        response.delete_cookie(DASHBOARD_ORG_ID_COOKIE)
        response.delete_cookie(DASHBOARD_API_KEY_HASH_COOKIE)

    return {
        "settings": await _settings_payload(session, account, None),
        "message": f"Deleted {org_name}.",
    }


@router.post("/admin/api-keys/generate")
async def generate_api_key(
    request: ApiKeyGenerateRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    """Generate a new API key for the authenticated organization."""
    account = await _get_account_for_user(session, dashboard_user)
    org = await _get_org(session, auth.org_id)
    if org.account_id != account.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    active_plan = effective_plan(account.plan_tier, account.billing_status)
    current_key_count = await _api_key_count(session, org.id)
    if current_key_count >= active_plan.api_keys_per_org:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": f"Your {active_plan.name} plan includes {active_plan.api_keys_per_org} API key"
                f"{'' if active_plan.api_keys_per_org == 1 else 's'} per organization. Upgrade to create more.",
                "plan_tier": active_plan.tier,
                "api_keys_per_org": active_plan.api_keys_per_org,
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
    new_count = current_key_count + 1

    return {
        "api_key": api_key,
        "key_prefix": api_key[:8],
        "name": request.name,
        "created_at": _serialize(record.created_at),
        "count": new_count,
        "limit": active_plan.api_keys_per_org,
        "message": "API key generated successfully. This is the only time you will see the full key. Save it securely.",
    }


@router.get("/admin/api-keys")
async def list_api_keys(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    """List all API keys for the authenticated organization (without the actual keys)."""
    account = await _get_account_for_user(session, dashboard_user)
    org = await _get_org(session, auth.org_id)
    active_plan = effective_plan(account.plan_tier, account.billing_status)
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
        ],
        "limit": active_plan.api_keys_per_org,
        "count": len(api_keys),
        "can_create": len(api_keys) < active_plan.api_keys_per_org,
    }


@router.delete("/admin/api-keys/{key_id}")
async def delete_api_key(
    key_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    """Revoke an API key for the selected dashboard organization."""
    account = await _get_account_for_user(session, dashboard_user)
    org = await _get_org(session, auth.org_id)
    if org.account_id != account.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    api_key = (
        await session.execute(
            select(ApiKey).where(
                ApiKey.id == key_id,
                ApiKey.org_id == auth.org_id,
            )
        )
    ).scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    await session.delete(api_key)
    await session.commit()

    active_plan = effective_plan(account.plan_tier, account.billing_status)
    new_count = await _api_key_count(session, auth.org_id)
    return {
        "message": "API key revoked.",
        "count": new_count,
        "limit": active_plan.api_keys_per_org,
        "can_create": new_count < active_plan.api_keys_per_org,
    }


@router.post("/admin/billing/checkout")
async def start_billing_checkout(
    request: BillingCheckoutRequest,
    session: AsyncSession = Depends(get_session),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, str]:
    account = await _get_account_for_user(session, dashboard_user)
    await session.commit()
    url = await create_checkout_session(account, dashboard_user.email, request.tier)
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
    offset: int = 0,
) -> dict[str, Any]:
    _ = dashboard_user
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)
    rules = (
        await session.execute(
            select(Rule)
            .where(Rule.org_id == auth.org_id)
            .order_by(
                case(
                    (Rule.status == "active", 0),
                    (Rule.status == "paused", 1),
                    (Rule.status.in_(["pending_approval", "pending_edit"]), 2),
                    (Rule.status == "archived", 3),
                    else_=4,
                ),
                Rule.trigger_count.desc(),
                Rule.updated_at.desc(),
            )
            .limit(safe_limit)
            .offset(safe_offset)
        )
    ).scalars().all()
    conflict_counts = await _rule_conflict_counts(session, rules)
    return {
        "items": [
            {
                **_dashboard_rule_payload(rule),
                "conflict_count": conflict_counts.get(rule.id, 0),
            }
            for rule in rules
        ]
    }


@router.get("/admin/rules/{rule_id}/detail")
async def get_rule_detail(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    rule = await _get_org_rule(session, rule_id, auth.org_id)
    return await _rule_detail_payload(session, rule, auth.org_id)


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
    if request.status == "active":
        safe_background_task(run_consolidation(org_id=auth.org_id, max_pairs_per_org=50), "run_consolidation")
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


@router.post("/admin/rules/bulk/status")
async def bulk_update_dashboard_rule_status(
    request: DashboardBulkRuleStatusUpdate,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    if not request.rule_ids:
        return {"updated": [], "count": 0, "status": request.status}

    rules = (
        await session.execute(
            select(Rule).where(
                Rule.id.in_(request.rule_ids),
                Rule.org_id == auth.org_id,
            )
        )
    ).scalars().all()
    if len(rules) != len(set(request.rule_ids)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Some selected rules were not found.",
        )

    if request.status == "active":
        conflict_service = ConflictService()
        for rule in rules:
            if rule.status == "active":
                continue
            conflict_warnings = await conflict_service.detect_activation_conflicts(session, rule)
            if conflict_warnings:
                await session.flush()
                await session.commit()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": "One selected rule would conflict with an existing active rule.",
                        "rule_id": str(rule.id),
                        "conflicts": [_conflict_payload(warning) for warning in conflict_warnings],
                    },
                )

    updated_ids = []
    now = datetime.now(UTC)
    for rule in rules:
        rule.status = request.status
        rule.updated_at = now
        updated_ids.append(str(rule.id))

    await session.commit()
    if request.status == "active":
        safe_background_task(run_consolidation(org_id=auth.org_id, max_pairs_per_org=50), "run_consolidation")

    return {
        "updated": updated_ids,
        "count": len(updated_ids),
        "status": request.status,
    }


@router.get("/admin/rules/export/json")
async def export_dashboard_rules_json(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> Response:
    _ = dashboard_user
    json_data = await RuleImportExportService().export_rules_json(session, auth.org_id)
    return Response(
        content=json_data,
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=rules_{auth.org_id}_{datetime.now(UTC).isoformat()}.json"
        },
    )


@router.get("/admin/rules/export/csv")
async def export_dashboard_rules_csv(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> Response:
    _ = dashboard_user
    csv_data = await RuleImportExportService().export_rules_csv(session, auth.org_id)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=rules_{auth.org_id}_{datetime.now(UTC).isoformat()}.csv"
        },
    )


@router.post("/admin/rules/import")
async def import_dashboard_rules(
    request: DashboardRuleImportRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    result = await RuleImportExportService().import_rules_json(
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
    if result.imported_count:
        safe_background_task(run_consolidation(org_id=auth.org_id, max_pairs_per_org=50), "run_consolidation")

    return {
        "success": result.success,
        "imported_count": result.imported_count,
        "skipped_count": result.skipped_count,
        "error_count": result.error_count,
        "errors": result.errors,
        "imported_rule_ids": result.imported_rule_ids,
        "imported": result.imported_count,
        "skipped": result.skipped_count,
    }


@router.get("/admin/rules/{rule_id}/analytics")
async def get_dashboard_rule_analytics(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    await _get_org_rule(session, rule_id, auth.org_id)
    stats = await RuleAnalyticsService().get_rule_usage_stats(session, rule_id)
    if stats is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return {
        "rule_id": stats.rule_id,
        "trigger_count": stats.trigger_count,
        "override_count": stats.override_count,
        "last_triggered_at": _serialize(stats.last_triggered_at),
        "days_since_last_trigger": stats.days_since_last_trigger,
        "triggers_last_7_days": stats.triggers_last_7_days,
        "triggers_last_30_days": stats.triggers_last_30_days,
        "triggers_last_90_days": stats.triggers_last_90_days,
        "is_stale": stats.is_stale,
    }


@router.get("/admin/rules/{rule_id}/versions")
async def get_dashboard_rule_versions(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    await _get_org_rule(session, rule_id, auth.org_id)
    versions = (
        await session.execute(
            select(RuleVersion)
            .where(RuleVersion.rule_id == rule_id)
            .order_by(RuleVersion.version_number.desc())
        )
    ).scalars().all()
    return {
        "versions": [
            {
                "id": str(version.id),
                "version_id": str(version.id),
                "version_number": version.version_number,
                "condition_description": version.condition_description,
                "action_description": version.action_description,
                "exceptions_note": version.exceptions_note,
                "changed_by": version.changed_by_email,
                "change_description": version.change_description,
                "created_at": _serialize(version.created_at),
            }
            for version in versions
        ],
        "current_version": len(versions) + 1,
        "count": len(versions),
    }


@router.get("/admin/rules/{rule_id}/comments")
async def get_dashboard_rule_comments(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    await _get_org_rule(session, rule_id, auth.org_id)
    comments = (
        await session.execute(
            select(RuleComment)
            .where(RuleComment.rule_id == rule_id)
            .order_by(RuleComment.created_at.desc())
        )
    ).scalars().all()
    return {
        "comments": [
            {
                "id": str(comment.id),
                "comment_id": str(comment.id),
                "comment_text": comment.comment_text,
                "created_by": comment.created_by_email,
                "created_at": _serialize(comment.created_at),
            }
            for comment in comments
        ],
        "count": len(comments),
    }


@router.post("/admin/rules/{rule_id}/comments")
async def add_dashboard_rule_comment(
    rule_id: UUID,
    request: DashboardAddCommentRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    await _get_org_rule(session, rule_id, auth.org_id)
    comment = RuleComment(
        rule_id=rule_id,
        comment_text=request.comment_text.strip(),
        created_by_user_id=dashboard_user.user_id,
        created_by_email=dashboard_user.email,
    )
    session.add(comment)
    await session.commit()
    return {
        "id": str(comment.id),
        "comment_id": str(comment.id),
        "rule_id": str(rule_id),
        "comment_text": comment.comment_text,
        "created_by": comment.created_by_email,
        "created_at": _serialize(comment.created_at),
    }


@router.post("/admin/rules/{rule_id}/test")
async def test_dashboard_rule(
    rule_id: UUID,
    request: DashboardRuleTestRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    await _get_org_rule(session, rule_id, auth.org_id)
    result = await RuleTestingService().test_rule(session, rule_id, request.test_context)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return {
        "rule_id": result.rule_id,
        "matched": result.matched,
        "action": result.action,
        "reasoning": result.reasoning,
        "matched_conditions": result.matched_conditions,
        "unmatched_conditions": result.unmatched_conditions,
    }


@router.get("/admin/escalations")
async def get_escalations(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    _ = dashboard_user
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)
    escalations = (
        await session.execute(
            select(Escalation)
            .where(Escalation.org_id == auth.org_id)
            .order_by(Escalation.created_at.desc())
            .limit(safe_limit)
            .offset(safe_offset)
        )
    ).scalars().all()

    # Batch fetch rules to avoid N+1 queries
    rule_ids = [e.rule_id for e in escalations if e.rule_id]
    rules_by_id = {}
    if rule_ids:
        rules = (await session.execute(select(Rule).where(Rule.id.in_(rule_ids)))).scalars().all()
        rules_by_id = {rule.id: rule for rule in rules}

    items = []
    for escalation in escalations:
        rule = rules_by_id.get(escalation.rule_id) if escalation.rule_id else None
        items.append(_dashboard_escalation_payload(escalation, rule))
    return {"items": items}


@router.post("/admin/escalations/{escalation_id}/quick-decision")
async def make_dashboard_quick_decision(
    escalation_id: UUID,
    request: DashboardEscalationQuickDecisionRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    escalation = await _get_org_escalation(session, escalation_id, auth.org_id)
    if escalation.status != "pending" or escalation.finalized_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Escalation has already been responded to",
        )

    now = datetime.now(UTC)
    escalation.status = "responded"
    escalation.human_decision = request.decision
    escalation.auto_resolved = False
    escalation.responded_at = now
    escalation.finalized_at = now
    escalation.finalization_reason = "quick_decision"
    escalation.apply_broadly = False

    await session.commit()
    await publish_final_escalation_result(escalation)

    return {
        "escalation_id": str(escalation.id),
        "status": escalation.status,
        "human_decision": escalation.human_decision,
        "finalized": True,
    }


@router.patch("/admin/escalations/{escalation_id}/tags")
async def update_dashboard_escalation_tags(
    escalation_id: UUID,
    request: DashboardEscalationTagsRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    _ = dashboard_user
    escalation = await _get_org_escalation(session, escalation_id, auth.org_id)
    normalized_tags = []
    for tag in request.tags:
        cleaned = tag.strip()
        if cleaned and cleaned not in normalized_tags:
            normalized_tags.append(cleaned)
    escalation.tags = normalized_tags
    await session.commit()
    return {
        "escalation_id": str(escalation.id),
        "tags": escalation.tags,
    }


@router.get("/admin/check-logs")
async def get_check_logs(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    _ = dashboard_user
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)
    logs = (
        await session.execute(
            select(PolicyCheckLog)
            .where(PolicyCheckLog.org_id == auth.org_id)
            .order_by(PolicyCheckLog.created_at.desc())
            .limit(safe_limit)
            .offset(safe_offset)
        )
    ).scalars().all()
    return {"items": [_check_log_payload(log) for log in logs]}


@router.get("/admin/activity")
async def get_activity(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
    limit: int = 75,
) -> dict[str, Any]:
    _ = dashboard_user
    safe_limit = min(max(limit, 1), 150)
    checks = (
        await session.execute(
            select(PolicyCheckLog)
            .where(PolicyCheckLog.org_id == auth.org_id)
            .order_by(PolicyCheckLog.created_at.desc())
            .limit(safe_limit)
        )
    ).scalars().all()
    escalations = (
        await session.execute(
            select(Escalation)
            .where(Escalation.org_id == auth.org_id)
            .order_by(Escalation.created_at.desc())
            .limit(safe_limit)
        )
    ).scalars().all()
    rules = (
        await session.execute(
            select(Rule)
            .where(Rule.org_id == auth.org_id)
            .order_by(Rule.created_at.desc())
            .limit(safe_limit)
        )
    ).scalars().all()

    rule_ids = {log.rule_id for log in checks if log.rule_id}
    rules_by_id = {}
    if rule_ids:
        matched_rules = (await session.execute(select(Rule).where(Rule.id.in_(rule_ids)))).scalars().all()
        rules_by_id = {rule.id: rule for rule in matched_rules}

    events = []
    for check in checks:
        events.append((check.created_at, _activity_item_payload("check", check, rules_by_id.get(check.rule_id))))
    for escalation in escalations:
        events.append((escalation.created_at, _activity_item_payload("escalation", escalation)))
    for rule in rules:
        events.append((rule.created_at, _activity_item_payload("rule", rule)))

    events.sort(key=lambda event: event[0], reverse=True)
    return {"items": [payload for _, payload in events[:safe_limit]]}


@router.post("/admin/feedback")
async def submit_feedback(
    request: FeedbackSubmitRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    """Submit user feedback from the dashboard."""
    # Get current org context if available
    org_context = await get_dashboard_org_from_request(http_request, session, dashboard_user)
    org_id = org_context.org_id if org_context else None

    # Get account ID if available
    account_id = None
    if dashboard_user:
        account = await _get_account_for_user(session, dashboard_user)
        if account:
            account_id = account.id

    # Get user agent from request headers
    user_agent = http_request.headers.get("user-agent")

    # Create feedback record
    feedback = Feedback(
        user_id=dashboard_user.user_id,
        email=dashboard_user.email,
        feedback_text=request.feedback_text,
        category=request.category,
        org_id=org_id,
        account_id=account_id,
        page_url=request.page_url,
        user_agent=user_agent,
    )

    session.add(feedback)
    await session.commit()

    return {
        "message": "Feedback submitted successfully. Thank you for helping us improve Signal!",
        "feedback_id": str(feedback.id),
    }


@router.get("/admin/health")
async def get_org_health(
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    """Get detailed health metrics for the current organization."""
    _ = dashboard_user

    # Count rules by status
    rule_counts = (
        await session.execute(
            select(Rule.status, func.count(Rule.id))
            .where(Rule.org_id == auth.org_id)
            .group_by(Rule.status)
        )
    ).all()
    rules_by_status = {status: count for status, count in rule_counts}

    # Count pending escalations
    pending_escalations = (
        await session.execute(
            select(func.count(Escalation.id))
            .where(
                Escalation.org_id == auth.org_id,
                Escalation.status == "pending",
            )
        )
    ).scalar_one()

    # Get stale rules (not triggered in 30 days)
    thirty_days_ago = datetime.now(UTC) - timedelta(days=30)
    stale_rules = (
        await session.execute(
            select(func.count(Rule.id))
            .where(
                Rule.org_id == auth.org_id,
                Rule.status == "active",
                or_(
                    Rule.last_triggered_at.is_(None),
                    Rule.last_triggered_at < thirty_days_ago,
                ),
            )
        )
    ).scalar_one()

    # Get average response time for recent checks
    recent_checks = (
        await session.execute(
            select(PolicyCheckLog.created_at)
            .where(PolicyCheckLog.org_id == auth.org_id)
            .order_by(PolicyCheckLog.created_at.desc())
            .limit(100)
        )
    ).scalars().all()

    avg_response_time = 0
    if len(recent_checks) >= 2:
        # Calculate average time between checks as a proxy for response time
        time_diffs = []
        for i in range(len(recent_checks) - 1):
            diff = (recent_checks[i] - recent_checks[i + 1]).total_seconds() * 1000
            if diff < 10000:  # Ignore gaps > 10 seconds
                time_diffs.append(diff)
        if time_diffs:
            avg_response_time = int(sum(time_diffs) / len(time_diffs))

    # Compile warnings
    warnings = []
    if stale_rules > 0:
        warnings.append(f"{stale_rules} active rule{'s' if stale_rules != 1 else ''} haven't triggered in 30 days")
    if pending_escalations > 5:
        warnings.append(f"{pending_escalations} escalations waiting for human decision")
    if rules_by_status.get("pending_approval", 0) > 0:
        warnings.append(f"{rules_by_status['pending_approval']} rule{'s' if rules_by_status['pending_approval'] != 1 else ''} pending approval")

    return {
        "api_reachable": True,
        "rule_count": sum(rules_by_status.values()),
        "active_rules": rules_by_status.get("active", 0),
        "pending_rules": rules_by_status.get("pending_approval", 0) + rules_by_status.get("pending_edit", 0),
        "avg_response_time_ms": avg_response_time,
        "pending_escalations": pending_escalations,
        "stale_rules": stale_rules,
        "warnings": warnings,
        "rules_by_status": rules_by_status,
    }


@router.post("/admin/rules/{rule_id}/validate")
async def validate_rule_quality(
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_dashboard_org_auth),
    dashboard_user: DashboardUser = Depends(require_dashboard_user),
) -> dict[str, Any]:
    """Validate rule quality and return confidence score with recommendations."""
    _ = dashboard_user
    rule = await _get_org_rule(session, rule_id, auth.org_id)

    issues = []
    recommendations = []
    confidence_score = 1.0

    # Check if rule has been triggered
    if rule.trigger_count == 0:
        issues.append("Rule has never been triggered")
        recommendations.append("Test the rule with sample context to ensure it works as expected")
        confidence_score -= 0.3

    # Check if rule is too broad (matches everything)
    if not rule.structured_conditions or len(rule.structured_conditions) == 0:
        issues.append("Rule has no conditions - will match everything")
        recommendations.append("Add specific conditions to make the rule more targeted")
        confidence_score -= 0.5

    # Check extraction confidence
    if rule.extraction_confidence < 0.7:
        issues.append(f"Low extraction confidence ({rule.extraction_confidence:.0%})")
        recommendations.append("Consider manually reviewing and editing the rule conditions")
        confidence_score -= 0.2

    # Check for conflicts with other active rules
    conflicts = (
        await session.execute(
            select(RuleConflict)
            .where(
                or_(
                    RuleConflict.rule_a_id == rule_id,
                    RuleConflict.rule_b_id == rule_id,
                ),
                RuleConflict.resolved == False,  # noqa: E712
            )
        )
    ).scalars().all()

    if conflicts:
        issues.append(f"{len(conflicts)} unresolved conflict{'s' if len(conflicts) > 1 else ''}")
        recommendations.append("Review and resolve conflicts with other rules")
        confidence_score -= 0.2 * min(len(conflicts), 3)

    # Check staleness
    if rule.last_triggered_at:
        days_since = (datetime.now(UTC) - rule.last_triggered_at).days
        if days_since > 30:
            issues.append(f"Not triggered in {days_since} days")
            recommendations.append("Consider archiving if no longer needed")
            confidence_score -= 0.1

    confidence_score = max(0.0, min(1.0, confidence_score))

    return {
        "rule_id": str(rule_id),
        "confident": confidence_score >= 0.7,
        "confidence_score": round(confidence_score, 2),
        "issues": issues,
        "recommendations": recommendations,
        "summary": (
            "Rule looks good!" if confidence_score >= 0.8
            else "Rule has some issues that should be addressed" if confidence_score >= 0.5
            else "Rule has significant quality issues"
        ),
    }
