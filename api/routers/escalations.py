from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import AuthContext, require_api_key
from api.database import get_session
from api.models import Escalation, PolicyCheckLog, Rule
from api.rate_limit import limiter
from api.schemas import EscalationCreate, EscalationCreateResponse, EscalationStateResponse
from api.services.escalation_pipeline import prepare_escalation_semantics, prepare_escalation_slack_card
from api.services.redis_service import publish_escalation_created, subscribe_escalation_events
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
    escalation = Escalation(
        context=payload.context,
        question=payload.question,
        metadata_=payload.metadata,
        agent_id=payload.agent_id,
        org_id=auth.org_id,
    )
    session.add(escalation)
    await session.flush()
    action = _payload_action(payload)
    if action:
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
            overridden_rule = await session.get(Rule, recent_check.rule_id)
            if overridden_rule and overridden_rule.org_id == auth.org_id:
                overridden_rule.override_count += 1

    await session.commit()

    await prepare_escalation_semantics(str(escalation.id))

    background_tasks.add_task(publish_escalation_created, escalation)
    background_tasks.add_task(prepare_escalation_slack_card, str(escalation.id))
    background_tasks.add_task(
        send_webhook_event_by_org_id,
        auth.org_id,
        "escalation.created",
        {
            "id": str(escalation.id),
            "org_id": str(auth.org_id),
            "agent_id": escalation.agent_id,
            "context": escalation.context,
            "question": escalation.question,
            "action": action,
            "metadata": escalation.metadata_,
            "status": escalation.status,
            "created_at": escalation.created_at,
        },
    )

    return EscalationCreateResponse(escalation_id=escalation.id, status=escalation.status)


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
