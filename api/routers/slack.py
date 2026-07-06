from __future__ import annotations

import hashlib
import hmac
import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.background_tasks import safe_background_task
from api.config import settings
from api.database import AsyncSessionLocal
from api.models import ConsolidationSuggestion, Escalation, Rule, RuleConflict, RuleVersion
from api.services.conflict_service import ConflictService
from api.services.embedding_service import embed, save_rule_embedding
from api.services.extraction_service import ExtractionService
from api.services.lifecycle_service import run_consolidation
from api.services.redis_service import publish_escalation_response
from api.services.resolution_propagator import propagate_rule
from api.services.slack_service import SlackService
from api.services.webhook_service import send_webhook_event_by_org_id


router = APIRouter(prefix="/slack", tags=["slack"])
logger = logging.getLogger(__name__)


def _verify_slack_signature(body: bytes, timestamp: str | None, signature: str | None) -> None:
    if not settings.slack_signing_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Slack is not configured")

    if not timestamp or not signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Slack signature")

    try:
        request_time = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Slack timestamp") from exc

    if abs(time.time() - request_time) > 60 * 5:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expired Slack request")

    basestring = f"v0:{timestamp}:{body.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(
        settings.slack_signing_secret.encode("utf-8"),
        basestring,
        hashlib.sha256,
    ).hexdigest()
    expected_signature = f"v0={digest}"

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Slack signature")


def _parse_payload(body: bytes) -> dict:
    parsed = parse_qs(body.decode("utf-8"))
    payload_values = parsed.get("payload")
    if not payload_values:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Slack payload")
    return json.loads(payload_values[0])


def _extract_rule_edit_text(payload: dict) -> str:
    values = payload.get("view", {}).get("state", {}).get("values", {})
    edit_block = values.get("rule_edit", {})
    edit_action = edit_block.get("edit_text", {})
    return str(edit_action.get("value") or "").strip()


async def _get_escalation(session: AsyncSession, escalation_id: str) -> Escalation:
    escalation = await session.get(Escalation, UUID(escalation_id))
    if escalation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escalation not found")
    return escalation


async def _get_rule(session: AsyncSession, rule_id: str) -> Rule:
    rule = await session.get(Rule, UUID(rule_id))
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


async def _prepare_rule_semantics(session: AsyncSession, rule: Rule):
    conflict_service = ConflictService()
    embedding = None
    try:
        embedding = await embed(rule.condition_description)
        await save_rule_embedding(session, str(rule.id), embedding)
        await session.flush()
    except Exception:
        logger.exception("Could not generate embedding for rule %s", rule.id)

    try:
        warnings = await conflict_service.detect_conflicts(session, rule, embedding)
        await session.flush()
        stored_warnings = await conflict_service.load_warnings(session, rule)
        return stored_warnings or warnings
    except Exception:
        logger.exception("Could not prepare semantic checks for rule %s", rule.id)
        try:
            return await conflict_service.load_warnings(session, rule)
        except Exception:
            return []


def _mark_escalation_finalized(escalation: Escalation, reason: str) -> None:
    now = datetime.now(UTC)
    escalation.status = "responded"
    escalation.finalized_at = now
    escalation.finalization_reason = reason
    if escalation.responded_at is None:
        escalation.responded_at = now


async def _publish_final_escalation_result(escalation: Escalation) -> None:
    await publish_escalation_response(escalation)
    await send_webhook_event_by_org_id(
        escalation.org_id,
        "escalation.resolved",
        {
            "id": str(escalation.id),
            "org_id": str(escalation.org_id) if escalation.org_id else None,
            "agent_id": escalation.agent_id,
            "status": escalation.status,
            "human_decision": escalation.human_decision,
            "rule_id": str(escalation.rule_id) if escalation.rule_id else None,
            "auto_resolved": escalation.auto_resolved,
            "finalized": escalation.finalized_at is not None,
            "finalization_reason": escalation.finalization_reason,
            "responded_at": escalation.responded_at,
            "finalized_at": escalation.finalized_at,
        },
    )


async def _save_rule_version(session: AsyncSession, rule: Rule, change_description: str | None = None) -> None:
    """Save a snapshot of the rule's current state before modifying it."""
    # Get current version count
    result = await session.execute(
        select(RuleVersion)
        .where(RuleVersion.rule_id == rule.id)
        .order_by(RuleVersion.version_number.desc())
        .limit(1)
    )
    latest_version = result.scalar_one_or_none()
    next_version_number = (latest_version.version_number + 1) if latest_version else 1

    # Save current state as a version
    version = RuleVersion(
        rule_id=rule.id,
        version_number=next_version_number,
        condition_description=rule.condition_description,
        action_description=rule.action_description,
        exceptions_note=rule.exceptions_note,
        structured_conditions=rule.structured_conditions,
        structured_action=rule.structured_action,
        changed_by_user_id=None,  # Could be enhanced to track Slack user
        changed_by_email=None,
        change_description=change_description,
    )
    session.add(version)


@router.post("/interactions", response_model=None)
async def handle_slack_interaction(
    request: Request,
    background_tasks: BackgroundTasks,
):
    body = await request.body()
    _verify_slack_signature(
        body=body,
        timestamp=request.headers.get("X-Slack-Request-Timestamp"),
        signature=request.headers.get("X-Slack-Signature"),
    )
    payload = _parse_payload(body)

    if payload.get("type") == "view_submission":
        callback_id = payload.get("view", {}).get("callback_id")
        if callback_id != "rule_edit_submission":
            return {"ok": True}

        rule_id = payload.get("view", {}).get("private_metadata")
        edit_text = _extract_rule_edit_text(payload)
        if not rule_id or not edit_text:
            return {
                "response_action": "errors",
                "errors": {"rule_edit": "Tell me what should change before submitting."},
            }

        background_tasks.add_task(process_rule_edit_submission, rule_id, edit_text)
        return {"response_action": "clear"}

    action = payload.get("actions", [{}])[0]
    action_id = action.get("action_id")
    value = action.get("value")
    if not action_id or not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Slack action")

    supported_actions = {
        "escalation_approve",
        "escalation_reject",
        "escalation_apply_broadly_yes",
        "escalation_apply_broadly_no",
        "rule_approve",
        "rule_edit",
        "rule_discard",
    }
    if action_id not in supported_actions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported action: {action_id}")

    if action_id == "rule_edit":
        trigger_id = payload.get("trigger_id")
        if not trigger_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Slack trigger")
        await SlackService().open_rule_edit_modal(trigger_id, value)

    background_tasks.add_task(process_slack_action, action_id, value)
    return {"ok": True}


async def process_slack_action(action_id: str, value: str) -> None:
    slack = SlackService()

    try:
        async with AsyncSessionLocal() as session:
            if action_id in {"escalation_approve", "escalation_reject"}:
                escalation = await _get_escalation(session, value)
                escalation.status = "responded"
                escalation.human_decision = "approve" if action_id == "escalation_approve" else "reject"
                escalation.auto_resolved = False
                escalation.responded_at = datetime.now(UTC)
                await slack.update_escalation_with_decision(escalation)
                escalation.slack_followup_ts = await slack.send_apply_broadly_followup(escalation)
                await session.commit()
                return

            if action_id == "escalation_apply_broadly_no":
                escalation = await _get_escalation(session, value)
                escalation.apply_broadly = False
                escalation.rule_id = None
                _mark_escalation_finalized(escalation, "one_time")
                await slack.acknowledge_one_time_decision(escalation)
                await session.commit()
                await _publish_final_escalation_result(escalation)
                return

            if action_id == "escalation_apply_broadly_yes":
                escalation = await _get_escalation(session, value)
                escalation.apply_broadly = True
                extracted = await ExtractionService().extract_rule(escalation)
                rule = Rule(
                    condition_description=extracted.condition_description,
                    action_description=extracted.action_description,
                    exceptions_note=extracted.exceptions_note,
                    structured_conditions=extracted.structured_conditions,
                    structured_action=extracted.structured_action,
                    agent_scope=[],
                    extraction_confidence=extracted.confidence,
                    status="pending_approval",
                    source_escalation_id=escalation.id,
                    org_id=escalation.org_id,
                )
                session.add(rule)
                await session.flush()
                escalation.rule_id = rule.id
                conflict_warnings = await _prepare_rule_semantics(session, rule)
                escalation.slack_rule_proposal_ts = await slack.send_rule_proposal(
                    escalation,
                    rule,
                    conflict_warnings=conflict_warnings,
                )
                await session.commit()
                return

            if action_id == "rule_approve":
                rule = await _get_rule(session, value)
                conflict_warnings = await _prepare_rule_semantics(session, rule)
                if conflict_warnings:
                    rule.status = "pending_approval"
                    rule.updated_at = datetime.now(UTC)
                    escalation = (
                        await session.get(Escalation, rule.source_escalation_id)
                        if rule.source_escalation_id
                        else None
                    )
                    if escalation is not None:
                        await slack.update_rule_proposal(
                            escalation,
                            rule,
                            "blocked by conflict",
                            conflict_warnings=conflict_warnings,
                            include_buttons=True,
                        )
                    await session.commit()
                    return
                rule.status = "active"
                rule.updated_at = datetime.now(UTC)
                escalation = await session.get(Escalation, rule.source_escalation_id) if rule.source_escalation_id else None
                if escalation is not None:
                    escalation.rule_id = rule.id
                    _mark_escalation_finalized(escalation, "rule_approved")
                    await slack.update_rule_proposal(escalation, rule, "approved")
                await session.commit()
                if escalation is not None:
                    await _publish_final_escalation_result(escalation)
                safe_background_task(propagate_rule(rule.id, rule.org_id), "propagate_rule")
                safe_background_task(run_consolidation(org_id=rule.org_id, max_pairs_per_org=50), "run_consolidation")
                await send_webhook_event_by_org_id(
                    rule.org_id,
                    "rule.created",
                    {
                        "id": str(rule.id),
                        "org_id": str(rule.org_id) if rule.org_id else None,
                        "condition_description": rule.condition_description,
                        "action_description": rule.action_description,
                        "status": rule.status,
                        "source_escalation_id": str(rule.source_escalation_id) if rule.source_escalation_id else None,
                        "created_at": rule.created_at,
                    },
                )
                return

            if action_id == "rule_edit":
                rule = await _get_rule(session, value)
                # Allow editing rules in any status (pending_approval, pending_edit, or active)
                rule.status = "pending_edit"
                rule.updated_at = datetime.now(UTC)
                await session.commit()
                return

            if action_id == "rule_discard":
                rule = await _get_rule(session, value)
                escalation = await session.get(Escalation, rule.source_escalation_id) if rule.source_escalation_id else None
                if escalation is not None:
                    escalation.rule_id = None
                    _mark_escalation_finalized(escalation, "rule_discarded")
                    await slack.update_rule_proposal(escalation, rule, "discarded")

                # Clean up all references before deleting the rule
                await session.execute(
                    delete(RuleConflict).where(
                        or_(
                            RuleConflict.rule_a_id == rule.id,
                            RuleConflict.rule_b_id == rule.id,
                        )
                    )
                )
                await session.execute(
                    delete(ConsolidationSuggestion).where(
                        or_(
                            ConsolidationSuggestion.rule_a_id == rule.id,
                            ConsolidationSuggestion.rule_b_id == rule.id,
                        )
                    )
                )

                await session.delete(rule)
                await session.commit()
                if escalation is not None:
                    await _publish_final_escalation_result(escalation)
    except Exception:
        logger.exception("Failed to process Slack action %s", action_id)


async def process_rule_edit_submission(rule_id: str, edit_text: str) -> None:
    slack = SlackService()

    try:
        async with AsyncSessionLocal() as session:
            rule = await session.get(Rule, UUID(rule_id))
            # Allow editing rules in any status (pending_edit, pending_approval, or active)
            if rule is None or rule.status not in {"pending_edit", "pending_approval", "active"}:
                return

            escalation = await session.get(Escalation, rule.source_escalation_id) if rule.source_escalation_id else None
            if escalation is None:
                return

            # Save version before editing
            await _save_rule_version(session, rule, f"Edited via Slack modal: {edit_text[:100]}")

            revised = await ExtractionService().revise_rule(escalation, rule, edit_text)
            rule.condition_description = revised.condition_description
            rule.action_description = revised.action_description
            rule.exceptions_note = revised.exceptions_note
            rule.structured_conditions = revised.structured_conditions
            rule.structured_action = revised.structured_action
            rule.extraction_confidence = revised.confidence
            # Set to pending_approval to require re-approval (even if it was previously active)
            rule.status = "pending_approval"
            rule.updated_at = datetime.now(UTC)
            await session.flush()
            # Re-run conflict detection after edits
            conflict_warnings = await _prepare_rule_semantics(session, rule)
            escalation.slack_rule_proposal_ts = await slack.send_rule_proposal(
                escalation,
                rule,
                conflict_warnings=conflict_warnings,
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to process Slack rule edit submission")


@router.post("/events", response_model=None)
async def handle_slack_event(
    request: Request,
    background_tasks: BackgroundTasks,
):
    body = await request.body()
    _verify_slack_signature(
        body=body,
        timestamp=request.headers.get("X-Slack-Request-Timestamp"),
        signature=request.headers.get("X-Slack-Signature"),
    )

    payload = json.loads(body.decode("utf-8"))
    if payload.get("type") == "url_verification":
        return PlainTextResponse(payload["challenge"])

    if payload.get("type") == "event_callback":
        event = payload.get("event", {})
        if event.get("type") == "message":
            background_tasks.add_task(process_slack_message_event, event)

    return {"ok": True}


async def process_slack_message_event(event: dict) -> None:
    subtype = event.get("subtype")
    if subtype or event.get("bot_id"):
        return

    edit_text = str(event.get("text") or "").strip()
    thread_ts = event.get("thread_ts")
    channel_id = event.get("channel")
    if not edit_text or not thread_ts or not channel_id:
        return

    slack = SlackService()

    try:
        async with AsyncSessionLocal() as session:
            escalation = (
                await session.execute(
                    select(Escalation).where(
                        Escalation.slack_message_ts == thread_ts,
                        Escalation.slack_channel_id == channel_id,
                    )
                )
            ).scalar_one_or_none()
            if escalation is None or escalation.rule_id is None:
                return

            rule = await session.get(Rule, escalation.rule_id)
            # Allow editing rules in any status via threaded message
            if rule is None or rule.status not in {"pending_edit", "pending_approval", "active"}:
                return

            # Save version before editing
            await _save_rule_version(session, rule, f"Edited via Slack thread: {edit_text[:100]}")

            revised = await ExtractionService().revise_rule(escalation, rule, edit_text)
            rule.condition_description = revised.condition_description
            rule.action_description = revised.action_description
            rule.exceptions_note = revised.exceptions_note
            rule.structured_conditions = revised.structured_conditions
            rule.structured_action = revised.structured_action
            rule.extraction_confidence = revised.confidence
            # Set to pending_approval to require re-approval
            rule.status = "pending_approval"
            rule.updated_at = datetime.now(UTC)
            await session.flush()
            # Re-run conflict detection after edits
            conflict_warnings = await _prepare_rule_semantics(session, rule)
            escalation.slack_rule_proposal_ts = await slack.send_rule_proposal(
                escalation,
                rule,
                conflict_warnings=conflict_warnings,
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to process Slack rule edit message")
