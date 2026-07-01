from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from api.database import AsyncSessionLocal
from api.models import Escalation, Organization, Rule
from api.rule_engine import rule_applies_to_agent, rule_matches
from api.services.redis_service import publish_escalation_response
from api.services.escalation_pipeline import slack_delivery_available
from api.services.slack_service import SlackService
from api.services.webhook_service import send_webhook_event_by_org_id


logger = logging.getLogger(__name__)


def _action_to_human_decision(action: str) -> str:
    normalized = action.lower()
    if normalized in {"block", "reject", "deny", "skip"}:
        return "reject"
    return "approve"


def _has_exact_structured_coverage(rule: Rule, escalation: Escalation) -> bool:
    if not rule.structured_conditions:
        return False
    return rule_matches(rule, escalation.metadata_ or {})


def _resolution_reason(rule: Rule) -> str:
    return (
        "The newly approved rule matched this escalation's structured metadata exactly: "
        f"{rule.condition_description}"
    )


async def propagate_rule(rule_id: str | UUID, org_id: str | UUID | None) -> dict[str, int]:
    stats = {"checked": 0, "resolved": 0, "left_waiting": 0}
    if org_id is None:
        return stats

    slack = SlackService()
    resolved_escalations: list[Escalation] = []

    try:
        async with AsyncSessionLocal() as session:
            rule = await session.get(Rule, UUID(str(rule_id)))
            if rule is None or rule.status != "active" or str(rule.org_id) != str(org_id):
                return stats

            pending_escalations = (
                await session.execute(
                    select(Escalation)
                    .where(
                        Escalation.org_id == rule.org_id,
                        Escalation.status == "pending",
                    )
                    .order_by(Escalation.created_at.asc())
                )
            ).scalars().all()

            for escalation in pending_escalations:
                stats["checked"] += 1
                if not rule_applies_to_agent(rule, escalation.agent_id):
                    stats["left_waiting"] += 1
                    continue

                if not _has_exact_structured_coverage(rule, escalation):
                    stats["left_waiting"] += 1
                    continue

                action = rule.structured_action or {}
                escalation.status = "responded"
                escalation.human_decision = _action_to_human_decision(str(action.get("action", "proceed")))
                escalation.rule_id = rule.id
                escalation.auto_resolved = True
                escalation.human_reasoning = _resolution_reason(rule)
                now = datetime.now(UTC)
                escalation.responded_at = now
                escalation.finalized_at = now
                escalation.finalization_reason = "auto_resolved"
                resolved_escalations.append(escalation)
                stats["resolved"] += 1

            await session.commit()

            for escalation in resolved_escalations:
                org = await session.get(Organization, escalation.org_id) if escalation.org_id else None
                if slack_delivery_available(org):
                    try:
                        await slack.update_escalation_auto_resolved(escalation, rule)
                    except Exception:
                        logger.exception("Failed to update auto-resolved Slack card for %s", escalation.id)

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
    except Exception:
        logger.exception("Rule propagation failed for rule %s", rule_id)

    return stats
