from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import ConsolidationSuggestion, Escalation, Organization, Rule, RuleConflict
from api.services.conflict_service import ConflictService, ConflictWarning
from api.services.context_schema_service import ContextSchemaService
from api.services.embedding_service import embed, save_rule_embedding
from api.services.escalation_pipeline import slack_delivery_available
from api.services.extraction_service import ExtractionService
from api.services.redis_service import publish_escalation_response
from api.services.resolution_propagator import propagate_rule
from api.services.slack_service import SlackService
from api.services.webhook_service import send_webhook_event_by_org_id


logger = logging.getLogger(__name__)


async def prepare_rule_semantics(session: AsyncSession, rule: Rule) -> list[ConflictWarning]:
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


def mark_escalation_finalized(escalation: Escalation, reason: str) -> None:
    now = datetime.now(UTC)
    escalation.status = "responded"
    escalation.finalized_at = now
    escalation.finalization_reason = reason
    if escalation.responded_at is None:
        escalation.responded_at = now


async def publish_final_escalation_result(escalation: Escalation) -> None:
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
            "reasoning": escalation.human_reasoning,
            "responded_at": escalation.responded_at,
            "finalized_at": escalation.finalized_at,
        },
    )


async def publish_rule_created(rule: Rule) -> None:
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


async def _slack_sync_enabled(session: AsyncSession, escalation: Escalation) -> bool:
    if not escalation.slack_message_ts:
        return False
    org = await session.get(Organization, escalation.org_id) if escalation.org_id else None
    return slack_delivery_available(org)


async def _try_slack(coro: Any, action: str) -> Any:
    try:
        return await coro
    except Exception:
        logger.exception("Slack sync failed while trying to %s", action)
        return None


async def record_escalation_decision(
    session: AsyncSession,
    escalation: Escalation,
    decision: str,
) -> None:
    if escalation.finalized_at is not None:
        raise ValueError("This escalation has already been finalized.")
    if decision not in {"approve", "reject"}:
        raise ValueError("Decision must be approve or reject.")

    escalation.status = "responded"
    escalation.human_decision = decision
    escalation.auto_resolved = False
    escalation.responded_at = datetime.now(UTC)

    if await _slack_sync_enabled(session, escalation):
        slack = SlackService()
        await _try_slack(slack.update_escalation_with_decision(escalation), "update escalation decision")
        followup_ts = await _try_slack(slack.send_apply_broadly_followup(escalation), "send apply-broadly prompt")
        if followup_ts:
            escalation.slack_followup_ts = followup_ts


async def mark_one_time(session: AsyncSession, escalation: Escalation) -> None:
    if escalation.finalized_at is not None:
        raise ValueError("This escalation has already been finalized.")
    if not escalation.human_decision:
        raise ValueError("Record a decision before choosing one-time.")

    escalation.apply_broadly = False
    escalation.rule_id = None
    mark_escalation_finalized(escalation, "one_time")

    if await _slack_sync_enabled(session, escalation):
        await _try_slack(SlackService().acknowledge_one_time_decision(escalation), "acknowledge one-time decision")


async def create_rule_from_escalation(
    session: AsyncSession,
    escalation: Escalation,
) -> tuple[Rule, list[ConflictWarning]]:
    if escalation.finalized_at is not None:
        raise ValueError("This escalation has already been finalized.")
    if not escalation.human_decision:
        raise ValueError("Record a decision before creating a rule.")

    if escalation.rule_id:
        existing_rule = await session.get(Rule, escalation.rule_id)
        if existing_rule is not None:
            warnings = await ConflictService().load_warnings(session, existing_rule)
            return existing_rule, warnings

    escalation.apply_broadly = True
    extracted = await ExtractionService().extract_rule(escalation)
    structured_conditions, _ = await ContextSchemaService().canonicalize_conditions(
        session,
        escalation.org_id,
        extracted.structured_conditions,
        learn=True,
        source="rule_extraction",
    )
    rule = Rule(
        condition_description=extracted.condition_description,
        action_description=extracted.action_description,
        exceptions_note=extracted.exceptions_note,
        structured_conditions=structured_conditions,
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
    warnings = await prepare_rule_semantics(session, rule)

    if await _slack_sync_enabled(session, escalation):
        proposal_ts = await _try_slack(
            SlackService().send_rule_proposal(escalation, rule, conflict_warnings=warnings),
            "send rule proposal",
        )
        if proposal_ts:
            escalation.slack_rule_proposal_ts = proposal_ts

    return rule, warnings


async def approve_rule(
    session: AsyncSession,
    rule: Rule,
) -> tuple[bool, list[ConflictWarning], Escalation | None]:
    warnings = await prepare_rule_semantics(session, rule)
    escalation = await session.get(Escalation, rule.source_escalation_id) if rule.source_escalation_id else None

    if warnings:
        rule.status = "pending_approval"
        rule.updated_at = datetime.now(UTC)
        if escalation is not None and await _slack_sync_enabled(session, escalation):
            await _try_slack(
                SlackService().update_rule_proposal(
                    escalation,
                    rule,
                    "blocked by conflict",
                    conflict_warnings=warnings,
                    include_buttons=True,
                ),
                "update conflicted rule proposal",
            )
        return False, warnings, escalation

    # Re-check for conflicts immediately before activation with locking
    # to prevent race condition where another rule might have been activated
    conflict_service = ConflictService()
    final_warnings = await conflict_service.detect_conflicts(session, rule, rule.condition_embedding)
    if final_warnings:
        rule.status = "pending_approval"
        rule.updated_at = datetime.now(UTC)
        if escalation is not None and await _slack_sync_enabled(session, escalation):
            await _try_slack(
                SlackService().update_rule_proposal(
                    escalation,
                    rule,
                    "blocked by conflict",
                    conflict_warnings=final_warnings,
                    include_buttons=True,
                ),
                "update conflicted rule proposal",
            )
        return False, final_warnings, escalation

    rule.status = "active"
    rule.updated_at = datetime.now(UTC)
    if escalation is not None:
        escalation.rule_id = rule.id
        mark_escalation_finalized(escalation, "rule_approved")
        if await _slack_sync_enabled(session, escalation):
            await _try_slack(SlackService().update_rule_proposal(escalation, rule, "approved"), "approve rule proposal")
    return True, [], escalation


async def revise_rule(
    session: AsyncSession,
    rule: Rule,
    edit_text: str,
) -> tuple[Rule, list[ConflictWarning]]:
    if not edit_text.strip():
        raise ValueError("Tell me what should change before submitting.")

    escalation = await session.get(Escalation, rule.source_escalation_id) if rule.source_escalation_id else None
    if escalation is None:
        raise ValueError("This rule is missing its source escalation.")

    revised = await ExtractionService().revise_rule(escalation, rule, edit_text.strip())
    structured_conditions, _ = await ContextSchemaService().canonicalize_conditions(
        session,
        rule.org_id,
        revised.structured_conditions,
        learn=True,
        source="rule_revision",
    )
    rule.condition_description = revised.condition_description
    rule.action_description = revised.action_description
    rule.exceptions_note = revised.exceptions_note
    rule.structured_conditions = structured_conditions
    rule.structured_action = revised.structured_action
    rule.extraction_confidence = revised.confidence
    rule.status = "pending_approval"
    rule.updated_at = datetime.now(UTC)
    await session.flush()
    warnings = await prepare_rule_semantics(session, rule)

    if await _slack_sync_enabled(session, escalation):
        proposal_ts = await _try_slack(
            SlackService().send_rule_proposal(escalation, rule, conflict_warnings=warnings),
            "send revised rule proposal",
        )
        if proposal_ts:
            escalation.slack_rule_proposal_ts = proposal_ts

    return rule, warnings


async def discard_rule(
    session: AsyncSession,
    rule: Rule,
) -> Escalation | None:
    escalation = await session.get(Escalation, rule.source_escalation_id) if rule.source_escalation_id else None
    if escalation is not None:
        escalation.rule_id = None
        mark_escalation_finalized(escalation, "rule_discarded")
        if await _slack_sync_enabled(session, escalation):
            await _try_slack(SlackService().update_rule_proposal(escalation, rule, "discarded"), "discard rule proposal")

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

    await session.flush()
    await session.delete(rule)
    return escalation


async def after_rule_approved(rule_id: Any, org_id: Any) -> None:
    await propagate_rule(rule_id, org_id)
