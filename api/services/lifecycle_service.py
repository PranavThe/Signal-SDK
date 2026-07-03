from __future__ import annotations

import json
import logging
import re
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

CONSOLIDATION_VECTOR_DISTANCE_THRESHOLD = 0.32
CONSOLIDATION_TEXT_SIMILARITY_THRESHOLD = 0.48
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "about",
    "across",
    "action",
    "additional",
    "after",
    "again",
    "against",
    "alert",
    "also",
    "and",
    "any",
    "apply",
    "but",
    "can",
    "case",
    "condition",
    "does",
    "for",
    "from",
    "has",
    "have",
    "having",
    "into",
    "not",
    "other",
    "raise",
    "rule",
    "same",
    "should",
    "signal",
    "such",
    "than",
    "that",
    "the",
    "then",
    "this",
    "when",
    "where",
    "with",
    "without",
}


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


def _tokens(text_value: str) -> set[str]:
    return {
        token
        for token in _TOKEN_RE.findall(text_value.lower().replace("_", " "))
        if (len(token) >= 4 or token.isdigit()) and token not in _STOP_WORDS
    }


def _dice_similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return 2 * len(left_tokens & right_tokens) / (len(left_tokens) + len(right_tokens))


def _rule_text_similarity(rule_a: Rule, rule_b: Rule) -> float:
    condition_similarity = _dice_similarity(rule_a.condition_description, rule_b.condition_description)
    action_similarity = _dice_similarity(rule_a.action_description, rule_b.action_description)
    exception_similarity = _dice_similarity(rule_a.exceptions_note or "", rule_b.exceptions_note or "")
    return (condition_similarity * 0.65) + (action_similarity * 0.25) + (exception_similarity * 0.10)


def _candidate_key(row: dict[str, Any]) -> tuple[str, str]:
    left = str(row["rule_a_id"])
    right = str(row["rule_b_id"])
    return (left, right) if left < right else (right, left)


async def _pending_suggestion_exists(session, rule_a_id: UUID, rule_b_id: UUID) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(
                    ConsolidationSuggestion.status == "pending",
                    or_(
                        and_(
                            ConsolidationSuggestion.rule_a_id == rule_a_id,
                            ConsolidationSuggestion.rule_b_id == rule_b_id,
                        ),
                        and_(
                            ConsolidationSuggestion.rule_a_id == rule_b_id,
                            ConsolidationSuggestion.rule_b_id == rule_a_id,
                        ),
                    ),
                )
            )
        )
    )


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


async def run_consolidation(
    max_pairs_per_org: int = 25,
    org_id: UUID | str | None = None,
) -> dict[str, int]:
    stats = {"orgs": 0, "pairs_checked": 0, "suggestions_created": 0}
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async with AsyncSessionLocal() as session:
        org_query = select(Organization)
        if org_id is not None:
            org_query = org_query.where(Organization.id == UUID(str(org_id)))
        orgs = (await session.execute(org_query)).scalars().all()
        for org in orgs:
            stats["orgs"] += 1
            vector_rows = (
                await session.execute(
                    text(
                        """
                        SELECT
                            a.id AS rule_a_id,
                            b.id AS rule_b_id,
                            a.condition_description AS rule_a_condition,
                            a.action_description AS rule_a_action,
                            a.exceptions_note AS rule_a_exceptions,
                            b.condition_description AS rule_b_condition,
                            b.action_description AS rule_b_action,
                            b.exceptions_note AS rule_b_exceptions,
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
                          AND (a.condition_embedding <=> b.condition_embedding) < :distance_threshold
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
                    {
                        "org_id": str(org.id),
                        "distance_threshold": CONSOLIDATION_VECTOR_DISTANCE_THRESHOLD,
                        "limit": max_pairs_per_org,
                    },
                )
            ).mappings().all()

            rows: list[dict[str, Any]] = [dict(row) for row in vector_rows]
            seen_pairs = {_candidate_key(row) for row in rows}

            active_rules = (
                await session.execute(
                    select(Rule)
                    .where(Rule.org_id == org.id, Rule.status == "active")
                    .order_by(Rule.updated_at.desc(), Rule.created_at.desc())
                    .limit(300)
                )
            ).scalars().all()
            for index, rule_a in enumerate(active_rules):
                if len(rows) >= max_pairs_per_org:
                    break
                for rule_b in active_rules[index + 1 :]:
                    if len(rows) >= max_pairs_per_org:
                        break
                    key = tuple(sorted((str(rule_a.id), str(rule_b.id))))
                    if key in seen_pairs:
                        continue
                    text_similarity = _rule_text_similarity(rule_a, rule_b)
                    if text_similarity < CONSOLIDATION_TEXT_SIMILARITY_THRESHOLD:
                        continue
                    if await _pending_suggestion_exists(session, rule_a.id, rule_b.id):
                        continue
                    rows.append(
                        {
                            "rule_a_id": rule_a.id,
                            "rule_b_id": rule_b.id,
                            "rule_a_condition": rule_a.condition_description,
                            "rule_a_action": rule_a.action_description,
                            "rule_a_exceptions": rule_a.exceptions_note,
                            "rule_b_condition": rule_b.condition_description,
                            "rule_b_action": rule_b.action_description,
                            "rule_b_exceptions": rule_b.exceptions_note,
                            "distance": None,
                            "text_similarity": text_similarity,
                        }
                    )
                    seen_pairs.add(key)

            for row in rows:
                stats["pairs_checked"] += 1
                try:
                    result = await _ask_can_merge(client, row)
                except Exception:
                    logger.exception(
                        "Could not evaluate consolidation pair %s/%s",
                        row["rule_a_id"],
                        row["rule_b_id"],
                    )
                    continue
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
Rule A exceptions: {row.get("rule_a_exceptions") or "None"}

Rule B: {row["rule_b_condition"]} → {row["rule_b_action"]}
Rule B exceptions: {row.get("rule_b_exceptions") or "None"}

Can these two rules be merged into a single clearer rule?
Only return can_merge=true when they cover substantially overlapping situations
and prescribe compatible behavior. If they are contradictory, return false.

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
