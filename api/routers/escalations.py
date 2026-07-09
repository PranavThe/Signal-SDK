from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import AuthContext, require_api_key
from api.database import get_session
from api.models import Escalation, PolicyCheckLog, Rule
from api.rate_limit import limiter
from api.rule_engine import conflicting_actions, matching_rules_for_context, most_specific_rules, rule_precedence_key
from api.schemas import EscalationCreate, EscalationCreateResponse, EscalationStateResponse
from api.services.context_schema_service import ContextSchemaService, context_from_escalation_text
from api.services.context_service import ContextValidator
from api.services.embedding_service import embed
from api.services.escalation_pipeline import prepare_escalation_semantics, prepare_escalation_slack_card
from api.services.redis_service import publish_escalation_created, publish_escalation_response, subscribe_escalation_events
from api.services.semantic_service import find_semantic_rule_match, semantic_policy_text
from api.services.webhook_service import send_webhook_event_by_org_id


router = APIRouter(prefix="/v1/escalations", tags=["escalations"])


async def _get_org_escalation(
    session: AsyncSession,
    escalation_id: UUID,
    org_id: UUID,
) -> Escalation:
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


def _state_payload(escalation: Escalation) -> dict[str, object]:
    return {
        "escalation_id": str(escalation.id),
        "status": escalation.status,
        "human_decision": escalation.human_decision,
        "rule_id": str(escalation.rule_id) if escalation.rule_id else None,
        "auto_resolved": escalation.auto_resolved,
        "finalized": escalation.finalized_at is not None,
        "finalization_reason": escalation.finalization_reason,
    }


def _payload_action(payload: EscalationCreate) -> str | None:
    if payload.action:
        return payload.action
    for key in ("action", "attempted_action", "agent_action"):
        value = payload.metadata.get(key)
        if value:
            return str(value)
    return None


def _action_to_human_decision(action: str) -> str:
    """Convert structured action to human decision (approve/reject)."""
    normalized = action.lower()
    if normalized in {"block", "reject", "deny", "skip"}:
        return "reject"
    return "approve"


@router.post("", response_model=EscalationCreateResponse)
@limiter.limit("100/minute")
async def create_escalation(
    request: Request,
    response: Response,
    payload: EscalationCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> EscalationCreateResponse:
    # Sync user-defined schema if provided in metadata
    schema_service = ContextSchemaService()
    user_schema = payload.metadata.get("_signal_schema") if payload.metadata else None
    if user_schema and isinstance(user_schema, list):
        await schema_service.sync_user_schema(session, auth.org_id, user_schema)
        await session.flush()

    # Normalize context using ContextSchemaService
    context_result = await schema_service.normalize(
        session,
        auth.org_id,
        context_from_escalation_text(payload.context, payload.metadata),
        learn=True,
        source="escalation",
    )

    # Additional validation using ContextValidator
    all_warnings = list(context_result.warnings)
    validator = ContextValidator(session, auth.org_id)
    _, validation_warnings = await validator.validate_context(
        context_result.normalized,
        normalize=False,  # Already normalized
    )
    all_warnings.extend(validation_warnings)

    # CRITICAL FIX: Check existing rules before creating escalation
    # This enables auto-resolution as documented in the SDK
    rules = (
        await session.execute(
            select(Rule).where(
                Rule.status == "active",
                Rule.org_id == auth.org_id,
            )
        )
    ).scalars().all()

    # Normalize rule condition values to match current schema types
    # This prevents type mismatches (e.g., string vs array) that cause rules to fail matching
    schema_service = ContextSchemaService()
    normalized_rules = []
    for rule in rules:
        normalized_rule = await schema_service.normalize_rule_for_matching(session, auth.org_id, rule)
        normalized_rules.append(normalized_rule)

    exact_candidates = most_specific_rules(
        matching_rules_for_context(normalized_rules, context_result.normalized, payload.agent_id)
    )
    has_rule_conflict = conflicting_actions(exact_candidates)
    matched_rule = None
    semantic_similarity: float | None = None

    if exact_candidates and not has_rule_conflict:
        matched_rule = max(exact_candidates, key=rule_precedence_key)

    # Try semantic matching if no exact match found
    if matched_rule is None and not has_rule_conflict:
        action = _payload_action(payload)
        if action:
            try:
                semantic_text = semantic_policy_text(action, context_result.normalized)
                semantic_match = await find_semantic_rule_match(
                    session,
                    await embed(semantic_text),
                    str(auth.org_id),
                    payload.agent_id,
                    query_text=semantic_text,
                )
                if semantic_match is not None:
                    matched_rule, semantic_similarity = semantic_match
            except Exception as e:
                # Don't fail escalation creation if semantic matching fails
                import logging
                logging.getLogger(__name__).exception("Semantic rule match failed during escalation")

    # Create escalation
    now = datetime.now(UTC)
    escalation = Escalation(
        context=payload.context,
        question=payload.question,
        metadata_=payload.metadata,
        normalized_context=context_result.normalized,
        agent_id=payload.agent_id,
        org_id=auth.org_id,
    )

    # If a rule matches, auto-resolve immediately
    if matched_rule is not None:
        action = matched_rule.structured_action or {}
        escalation.status = "responded"
        escalation.human_decision = _action_to_human_decision(str(action.get("action", "proceed")))
        escalation.rule_id = matched_rule.id
        escalation.auto_resolved = True

        # Include semantic similarity in reasoning if applicable
        if semantic_similarity is not None:
            escalation.human_reasoning = (
                f"Auto-resolved by semantically matched rule ({semantic_similarity * 100:.0f}%): "
                f"{matched_rule.condition_description}"
            )
        else:
            escalation.human_reasoning = f"Auto-resolved by rule: {matched_rule.condition_description}"

        escalation.responded_at = now
        escalation.finalized_at = now
        escalation.finalization_reason = "auto_resolved"

        # Update rule trigger stats
        await session.execute(
            update(Rule)
            .where(Rule.id == matched_rule.id)
            .values(
                trigger_count=Rule.trigger_count + 1,
                last_triggered_at=now,
            )
        )

    session.add(escalation)
    await session.flush()

    # Track override count if applicable
    action = _payload_action(payload)
    if action and not matched_rule:  # Only track overrides if no rule matched
        recent_check = (
            await session.execute(
                select(PolicyCheckLog)
                .where(
                    PolicyCheckLog.org_id == auth.org_id,
                    PolicyCheckLog.agent_id == payload.agent_id,
                    PolicyCheckLog.action == action,
                    PolicyCheckLog.rule_id.is_not(None),
                    PolicyCheckLog.created_at >= datetime.now(UTC) - timedelta(seconds=60),
                )
                .order_by(PolicyCheckLog.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if recent_check and recent_check.rule_id:
            # Atomic update to prevent race condition on override_count
            await session.execute(
                update(Rule)
                .where(Rule.id == recent_check.rule_id, Rule.org_id == auth.org_id)
                .values(override_count=Rule.override_count + 1)
            )

    await session.commit()

    # Only prepare semantics for pending escalations
    if escalation.status == "pending":
        await prepare_escalation_semantics(str(escalation.id))
        background_tasks.add_task(publish_escalation_created, escalation)
        background_tasks.add_task(prepare_escalation_slack_card, str(escalation.id))
    else:
        # For auto-resolved escalations, publish response immediately
        background_tasks.add_task(publish_escalation_response, escalation)

    # Always send webhook
    event_type = "escalation.resolved" if escalation.finalized_at else "escalation.created"
    webhook_data = {
        "id": str(escalation.id),
        "org_id": str(auth.org_id),
        "agent_id": escalation.agent_id,
        "context": escalation.context,
        "question": escalation.question,
        "action": action,
        "metadata": escalation.metadata_,
        "status": escalation.status,
        "created_at": escalation.created_at,
    }

    if escalation.finalized_at:
        webhook_data.update({
            "human_decision": escalation.human_decision,
            "rule_id": str(escalation.rule_id) if escalation.rule_id else None,
            "auto_resolved": escalation.auto_resolved,
            "finalized": True,
            "finalization_reason": escalation.finalization_reason,
            "reasoning": escalation.human_reasoning,
            "responded_at": escalation.responded_at,
            "finalized_at": escalation.finalized_at,
        })

    background_tasks.add_task(
        send_webhook_event_by_org_id,
        auth.org_id,
        event_type,
        webhook_data,
    )

    return EscalationCreateResponse(
        escalation_id=escalation.id,
        status=escalation.status,
        context_warnings=all_warnings,
    )


@router.get("/{escalation_id}", response_model=EscalationStateResponse)
async def get_escalation(
    escalation_id: UUID,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> EscalationStateResponse:
    escalation = await _get_org_escalation(session, escalation_id, auth.org_id)

    return EscalationStateResponse(
        escalation_id=escalation.id,
        status=escalation.status,
        human_decision=escalation.human_decision,
        rule_id=escalation.rule_id,
        auto_resolved=escalation.auto_resolved,
        finalized=escalation.finalized_at is not None,
        finalization_reason=escalation.finalization_reason,
    )


@router.get("/{escalation_id}/stream")
async def stream_escalation(
    escalation_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> EventSourceResponse:
    escalation = await _get_org_escalation(session, escalation_id, auth.org_id)
    initial_state = _state_payload(escalation)

    async def event_generator():
        if initial_state["finalized"]:
            yield {"event": "response", "data": json.dumps(initial_state)}
            return

        async for event in subscribe_escalation_events(str(escalation_id)):
            if await request.is_disconnected():
                break
            if event.get("event") == "created":
                continue
            yield {"event": str(event.get("event") or "message"), "data": json.dumps(event)}
            if event.get("finalized") or event.get("status") == "timed_out":
                break

    return EventSourceResponse(event_generator())


# New endpoints for product improvements


class QuickDecisionRequest(BaseModel):
    decision: str  # 'approve' or 'reject'


class UpdateTagsRequest(BaseModel):
    tags: list[str]


@router.post("/{escalation_id}/quick-decision")
async def make_quick_decision(
    escalation_id: UUID,
    request: QuickDecisionRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Make a quick approve/reject decision on an escalation from the list view."""
    escalation = await _get_org_escalation(session, escalation_id, auth.org_id)

    if escalation.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Escalation has already been responded to",
        )

    if request.decision not in ["approve", "reject"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Decision must be 'approve' or 'reject'",
        )

    # Update escalation
    escalation.status = "responded"
    escalation.human_decision = request.decision
    escalation.auto_resolved = False
    escalation.responded_at = datetime.now(UTC)
    escalation.finalized_at = datetime.now(UTC)
    escalation.finalization_reason = "quick_decision"
    escalation.apply_broadly = False

    await session.commit()

    # Publish result
    await publish_escalation_response(escalation)
    await send_webhook_event_by_org_id(
        auth.org_id,
        "escalation.resolved",
        {
            "id": str(escalation.id),
            "org_id": str(auth.org_id),
            "agent_id": escalation.agent_id,
            "status": escalation.status,
            "human_decision": escalation.human_decision,
            "auto_resolved": escalation.auto_resolved,
            "finalized": True,
            "finalization_reason": escalation.finalization_reason,
            "responded_at": escalation.responded_at,
            "finalized_at": escalation.finalized_at,
        },
    )

    return {
        "escalation_id": str(escalation.id),
        "status": escalation.status,
        "human_decision": escalation.human_decision,
        "finalized": True,
    }


@router.patch("/{escalation_id}/tags")
async def update_escalation_tags(
    escalation_id: UUID,
    request: UpdateTagsRequest,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Update tags for an escalation."""
    escalation = await _get_org_escalation(session, escalation_id, auth.org_id)

    escalation.tags = request.tags
    await session.commit()

    return {
        "escalation_id": str(escalation.id),
        "tags": escalation.tags,
    }


@router.get("/sla/overdue")
async def get_overdue_escalations(
    hours_threshold: int = 24,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Get escalations that are overdue based on SLA threshold."""
    threshold_time = datetime.now(UTC) - timedelta(hours=hours_threshold)

    result = await session.execute(
        select(Escalation)
        .where(
            Escalation.org_id == auth.org_id,
            Escalation.status == "pending",
            Escalation.created_at < threshold_time,
        )
        .order_by(Escalation.created_at.asc())
    )
    overdue_escalations = result.scalars().all()

    return {
        "overdue_escalations": [
            {
                "escalation_id": str(e.id),
                "agent_id": e.agent_id,
                "question": e.question,
                "context_preview": e.context[:100] + "..." if len(e.context) > 100 else e.context,
                "created_at": e.created_at.isoformat(),
                "hours_overdue": int((datetime.now(UTC) - e.created_at).total_seconds() / 3600),
                "tags": e.tags,
            }
            for e in overdue_escalations
        ],
        "count": len(overdue_escalations),
        "threshold_hours": hours_threshold,
    }
