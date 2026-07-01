from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy import Float, and_, cast, exists, or_, select, text

from api.config import settings
from api.database import AsyncSessionLocal
from api.models import ConsolidationSuggestion, Organization, Rule
from api.services.escalation_pipeline import slack_delivery_available
from api.services.slack_service import SlackService


logger = logging.getLogger(__name__)


def _json_from_text(text_value: str) -> dict[str, Any]:
    start = text_value.find("{")
    end = text_value.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in Claude response")
    return json.loads(text_value[start : end + 1])


def _text_from_message(message: Any) -> str:
    chunks: list[str] = []
    for block in message.content:
        block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if block_type == "text":
            chunks.append(block.get("text") if isinstance(block, dict) else getattr(block, "text", ""))
    return "\n".join(chunks)


async def run_staleness_check(include_new_rules: bool = False) -> dict[str, int]:
    now = datetime.now(UTC)
    created_before = now - timedelta(days=7)
    last_triggered_before = now - timedelta(days=60)
    stats = {"stale": 0, "unreliable": 0, "sent": 0}

    async with AsyncSessionLocal() as session:
        stale_filters = [
            Rule.status == "active",
            or_(Rule.last_triggered_at < last_triggered_before, Rule.last_triggered_at.is_(None)),
        ]
        if not include_new_rules:
            stale_filters.append(Rule.created_at < created_before)

        stale_rules = (await session.execute(select(Rule).where(*stale_filters))).scalars().all()
        unreliable_rules = (
            await session.execute(
                select(Rule).where(
                    Rule.status == "active",
                    Rule.trigger_count >= 10,
                    cast(Rule.override_count, Float) / cast(Rule.trigger_count, Float) > 0.20,
                )
            )
        ).scalars().all()

        stats["stale"] = len(stale_rules)
        stats["unreliable"] = len(unreliable_rules)
        slack = SlackService()
        sent_rule_ids: set[UUID] = set()

        for rule in stale_rules:
            if rule.id in sent_rule_ids:
                continue
            org = await session.get(Organization, rule.org_id) if rule.org_id else None
            if not slack_delivery_available(org):
                continue
            channel_id = org.slack_channel_id if org and org.slack_channel_id else settings.slack_channel_id
            try:
                await slack.send_rule_review_warning(rule, channel_id=channel_id, reason="stale")
                stats["sent"] += 1
                sent_rule_ids.add(rule.id)
            except Exception:
                logger.exception("Failed to send stale-rule warning for %s", rule.id)

        for rule in unreliable_rules:
            if rule.id in sent_rule_ids:
                continue
            org = await session.get(Organization, rule.org_id) if rule.org_id else None
            if not slack_delivery_available(org):
                continue
            channel_id = org.slack_channel_id if org and org.slack_channel_id else settings.slack_channel_id
            try:
                await slack.send_rule_review_warning(rule, channel_id=channel_id, reason="unreliable")
                stats["sent"] += 1
                sent_rule_ids.add(rule.id)
            except Exception:
                logger.exception("Failed to send unreliable-rule warning for %s", rule.id)

    return stats


async def run_consolidation(max_pairs_per_org: int = 25) -> dict[str, int]:
    stats = {"orgs": 0, "pairs_checked": 0, "suggestions_created": 0}
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async with AsyncSessionLocal() as session:
        orgs = (await session.execute(select(Organization))).scalars().all()
        for org in orgs:
            stats["orgs"] += 1
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT
                            a.id AS rule_a_id,
                            b.id AS rule_b_id,
                            a.condition_description AS rule_a_condition,
                            a.action_description AS rule_a_action,
                            b.condition_description AS rule_b_condition,
                            b.action_description AS rule_b_action,
                            a.condition_embedding <=> b.condition_embedding AS distance
                        FROM rules a
                        JOIN rules b
                          ON a.org_id = b.org_id
                         AND a.id < b.id
                        WHERE a.org_id = CAST(:org_id AS uuid)
                          AND a.status = 'active'
                          AND b.status = 'active'
                          AND a.condition_embedding IS NOT NULL
                          AND b.condition_embedding IS NOT NULL
                          AND a.condition_embedding <=> b.condition_embedding < 0.15
                          AND NOT EXISTS (
                              SELECT 1
                              FROM consolidation_suggestions cs
                              WHERE cs.status = 'pending'
                                AND (
                                    (cs.rule_a_id = a.id AND cs.rule_b_id = b.id)
                                    OR (cs.rule_a_id = b.id AND cs.rule_b_id = a.id)
                                )
                          )
                        ORDER BY distance ASC
                        LIMIT :limit
                        """
                    ),
                    {"org_id": str(org.id), "limit": max_pairs_per_org},
                )
            ).mappings().all()

            for row in rows:
                stats["pairs_checked"] += 1
                result = await _ask_can_merge(client, row)
                if not result.get("can_merge"):
                    continue

                session.add(
                    ConsolidationSuggestion(
                        org_id=org.id,
                        rule_a_id=UUID(str(row["rule_a_id"])),
                        rule_b_id=UUID(str(row["rule_b_id"])),
                        merged_condition=str(result.get("merged_condition") or row["rule_a_condition"]),
                        merged_action=str(result.get("merged_action") or row["rule_a_action"]),
                        reason=str(result.get("reason") or "These rules are semantically similar."),
                        status="pending",
                    )
                )
                stats["suggestions_created"] += 1

        await session.commit()

    return stats


async def _ask_can_merge(client: AsyncAnthropic, row: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""Rule A: {row["rule_a_condition"]} → {row["rule_a_action"]}
Rule B: {row["rule_b_condition"]} → {row["rule_b_action"]}

Can these two rules be merged into a single clearer rule?
Respond with JSON only:
{{
  "can_merge": true or false,
  "merged_condition": "...",
  "merged_action": "...",
  "reason": "one sentence"
}}"""

    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    response_text = _text_from_message(message)
    try:
        result = _json_from_text(response_text)
    except Exception:
        logger.exception("Could not parse consolidation response from Claude: %s", response_text)
        return {"can_merge": False, "reason": "Could not parse consolidation result."}

    return {
        "can_merge": bool(result.get("can_merge")),
        "merged_condition": str(result.get("merged_condition") or ""),
        "merged_action": str(result.get("merged_action") or ""),
        "reason": str(result.get("reason") or ""),
    }
