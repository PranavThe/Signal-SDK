from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.models import Rule, RuleConflict
from api.rule_engine import action_signature
from api.services.semantic_service import find_similar_rules


logger = logging.getLogger(__name__)


@dataclass
class ConflictWarning:
    existing_rule_id: str
    existing_condition: str
    existing_action: str
    explanation: str
    similarity: float


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


def _canonical_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _condition_key(condition: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(condition.get("field")),
        str(condition.get("operator")),
        _canonical_value(condition.get("value")),
    )


def _same_condition_set(rule_a: Rule, rule_b: Rule) -> bool:
    return sorted(_condition_key(condition) for condition in rule_a.structured_conditions) == sorted(
        _condition_key(condition) for condition in rule_b.structured_conditions
    )


def _value_satisfies_condition(value: Any, condition: dict[str, Any]) -> bool:
    operator = str(condition.get("operator"))
    expected = condition.get("value")
    try:
        if operator == "eq":
            return value == expected
        if operator == "neq":
            return value != expected
        if operator == "gt":
            return value > expected
        if operator == "gte":
            return value >= expected
        if operator == "lt":
            return value < expected
        if operator == "lte":
            return value <= expected
        if operator == "in":
            return value in expected
        if operator == "not_in":
            return value not in expected
        if operator == "exists":
            return bool(expected)
    except TypeError:
        return True
    return True


def _numeric_bound(condition: dict[str, Any]) -> tuple[float | None, bool, float | None, bool] | None:
    operator = str(condition.get("operator"))
    value = condition.get("value")
    if operator not in {"gt", "gte", "lt", "lte"}:
        return None
    if not isinstance(value, (int, float)):
        return None
    if operator == "gt":
        return float(value), False, None, False
    if operator == "gte":
        return float(value), True, None, False
    if operator == "lt":
        return None, False, float(value), False
    return None, False, float(value), True


def _numeric_ranges_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool | None:
    left_bound = _numeric_bound(left)
    right_bound = _numeric_bound(right)
    if left_bound is None or right_bound is None:
        return None

    lower = None
    lower_inclusive = True
    upper = None
    upper_inclusive = True
    for candidate_lower, candidate_lower_inclusive, candidate_upper, candidate_upper_inclusive in (
        left_bound,
        right_bound,
    ):
        if candidate_lower is not None and (
            lower is None
            or candidate_lower > lower
            or (candidate_lower == lower and not candidate_lower_inclusive)
        ):
            lower = candidate_lower
            lower_inclusive = candidate_lower_inclusive
        if candidate_upper is not None and (
            upper is None
            or candidate_upper < upper
            or (candidate_upper == upper and not candidate_upper_inclusive)
        ):
            upper = candidate_upper
            upper_inclusive = candidate_upper_inclusive

    if lower is None or upper is None:
        return True
    if lower < upper:
        return True
    if lower == upper:
        return lower_inclusive and upper_inclusive
    return False


def _conditions_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_operator = str(left.get("operator"))
    right_operator = str(right.get("operator"))
    left_value = left.get("value")
    right_value = right.get("value")

    if left_operator == "exists" and left_value is False:
        return right_operator in {"exists", "neq"} and right_value is False
    if right_operator == "exists" and right_value is False:
        return left_operator in {"exists", "neq"} and left_value is False

    if left_operator == "eq":
        return _value_satisfies_condition(left_value, right)
    if right_operator == "eq":
        return _value_satisfies_condition(right_value, left)

    if left_operator == "in" and isinstance(left_value, list):
        return any(_value_satisfies_condition(value, right) for value in left_value)
    if right_operator == "in" and isinstance(right_value, list):
        return any(_value_satisfies_condition(value, left) for value in right_value)

    if left_operator == "neq" and right_operator == "neq":
        return True
    if left_operator == "neq" and right_operator == "in" and isinstance(right_value, list):
        return any(value != left_value for value in right_value)
    if right_operator == "neq" and left_operator == "in" and isinstance(left_value, list):
        return any(value != right_value for value in left_value)

    numeric_overlap = _numeric_ranges_overlap(left, right)
    if numeric_overlap is not None:
        return numeric_overlap

    return True


def _rules_can_overlap(rule_a: Rule, rule_b: Rule) -> bool:
    if _same_condition_set(rule_a, rule_b):
        return True

    conditions_by_field: dict[str, list[dict[str, Any]]] = {}
    for condition in rule_b.structured_conditions:
        conditions_by_field.setdefault(str(condition.get("field")), []).append(condition)

    # Track if we found any overlapping fields to check
    found_any_overlap_check = False

    for condition_a in rule_a.structured_conditions:
        field = str(condition_a.get("field"))
        for condition_b in conditions_by_field.get(field, []):
            found_any_overlap_check = True  # Found at least one field to compare
            if not _conditions_overlap(condition_a, condition_b):
                return False

    # CRITICAL FIX: If rules have zero overlapping fields, they can't overlap
    # Example: Rule 1 checks "transfer.amount", Rule 2 checks "card.intent"
    # These are completely different situations and should not conflict
    if not found_any_overlap_check:
        return False

    return True


class ConflictService:
    def __init__(self) -> None:
        self.client = AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    async def detect_conflicts(
        self,
        session: AsyncSession,
        new_rule: Rule,
        embedding: list[float] | None = None,
    ) -> list[ConflictWarning]:
        await session.execute(
            update(RuleConflict)
            .where(RuleConflict.rule_a_id == new_rule.id, RuleConflict.resolved.is_(False))
            .values(resolved=True)
        )

        warnings = await self._detect_structural_conflicts(session, new_rule)
        warning_rule_ids = {warning.existing_rule_id for warning in warnings}

        similar_rules = []
        if embedding is not None:
            similar_rules = await find_similar_rules(
                session,
                embedding,
                str(new_rule.id),
                str(new_rule.org_id) if new_rule.org_id else None,
            )

        for existing in similar_rules:
            if str(existing["id"]) in warning_rule_ids:
                continue
            result = await self._compare_rules(new_rule, existing)
            if not result.get("conflicts"):
                continue

            explanation = str(result.get("explanation") or "These rules may conflict.")
            session.add(
                RuleConflict(
                    rule_a_id=new_rule.id,
                    rule_b_id=UUID(str(existing["id"])),
                    explanation=explanation,
                    resolved=False,
                )
            )
            warnings.append(
                ConflictWarning(
                    existing_rule_id=str(existing["id"]),
                    existing_condition=str(existing["condition_description"]),
                    existing_action=str(existing["action_description"]),
                    explanation=explanation,
                    similarity=float(existing["similarity"]),
                )
            )

        return warnings

    async def _generate_plain_english_explanation(
        self,
        new_rule: Rule,
        existing_rule: Rule,
    ) -> str:
        """Generate a plain English explanation of why two rules conflict using LLM."""
        prompt = f"""You are explaining a rule conflict to a business user. Two rules conflict when they could both apply to the same situation but prescribe different actions.

New rule:
WHEN: {new_rule.condition_description}
DO: {new_rule.action_description}

Existing rule:
WHEN: {existing_rule.condition_description}
DO: {existing_rule.action_description}

Explain in 1-2 simple sentences why these rules conflict. Focus on:
1. What specific situation would trigger both rules
2. What the inconsistency is (one approves, the other rejects, etc.)
3. If there are subtle differences like different identifiers for the same person/thing, point that out

Use plain English. Avoid technical jargon. Be specific about the scenario that causes the conflict.

Example good explanation: "When Alice deploys a bugfix with over 50 files, both rules would apply. The first rule would reject it because you wrote 'alice' while the second rule expects 'alice@company.com' - these are treated as different people."

Respond with ONLY the explanation text, nothing else."""

        try:
            message = await self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=200,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            explanation = _text_from_message(message).strip()
            # Fallback if response is empty or too short
            if len(explanation) < 20:
                return "Both rules can apply to the same structured context, but they prescribe different actions."
            return explanation
        except Exception:
            logger.exception("Could not generate plain English conflict explanation")
            return "Both rules can apply to the same structured context, but they prescribe different actions."

    async def _detect_structural_conflicts(
        self,
        session: AsyncSession,
        new_rule: Rule,
        statuses: tuple[str, ...] = ("active",),
    ) -> list[ConflictWarning]:
        active_rules = (
            await session.execute(
                select(Rule).where(
                    Rule.status.in_(statuses),
                    Rule.id != new_rule.id,
                    Rule.org_id == new_rule.org_id,
                )
            )
        ).scalars().all()
        warnings: list[ConflictWarning] = []

        for existing_rule in active_rules:
            if not self._actions_conflict(new_rule, existing_rule):
                continue
            if not self._agent_scopes_overlap(new_rule, existing_rule):
                continue
            if not _rules_can_overlap(new_rule, existing_rule):
                continue

            # Generate plain English explanation using LLM
            explanation = await self._generate_plain_english_explanation(new_rule, existing_rule)

            session.add(
                RuleConflict(
                    rule_a_id=new_rule.id,
                    rule_b_id=existing_rule.id,
                    explanation=explanation,
                    resolved=False,
                )
            )
            warnings.append(
                ConflictWarning(
                    existing_rule_id=str(existing_rule.id),
                    existing_condition=existing_rule.condition_description,
                    existing_action=existing_rule.action_description,
                    explanation=explanation,
                    similarity=1.0 if _same_condition_set(new_rule, existing_rule) else 0.0,
                )
            )

        return warnings

    async def detect_activation_conflicts(
        self,
        session: AsyncSession,
        rule: Rule,
    ) -> list[ConflictWarning]:
        return await self._detect_structural_conflicts(session, rule, statuses=("active",))

    def _actions_conflict(self, rule_a: Rule, rule_b: Rule) -> bool:
        return action_signature(rule_a) != action_signature(rule_b)

    def _agent_scopes_overlap(self, rule_a: Rule, rule_b: Rule) -> bool:
        if not rule_a.agent_scope or not rule_b.agent_scope:
            return True
        return bool(set(rule_a.agent_scope) & set(rule_b.agent_scope))

    async def load_warnings(self, session: AsyncSession, rule: Rule) -> list[ConflictWarning]:
        rows = (
            await session.execute(
                select(RuleConflict, Rule)
                .join(Rule, Rule.id == RuleConflict.rule_b_id)
                .where(
                    RuleConflict.rule_a_id == rule.id,
                    RuleConflict.resolved.is_(False),
                )
                .order_by(RuleConflict.created_at.desc())
            )
        ).all()

        return [
            ConflictWarning(
                existing_rule_id=str(existing_rule.id),
                existing_condition=existing_rule.condition_description,
                existing_action=existing_rule.action_description,
                explanation=conflict.explanation,
                similarity=0.0,
            )
            for conflict, existing_rule in rows
        ]

    async def _compare_rules(self, new_rule: Rule, existing_rule: dict[str, Any]) -> dict[str, Any]:
        prompt = f"""Rule A conditions: {new_rule.condition_description}
Rule A action: {new_rule.action_description}

Rule B conditions: {existing_rule["condition_description"]}
Rule B action: {existing_rule["action_description"]}

Do these two rules conflict? A conflict means they could apply to the same
situation but prescribe different actions.

Respond with JSON only:
{{
  "conflicts": true or false,
  "explanation": "one sentence explaining why or why not"
}}"""

        message = await self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = _text_from_message(message)
        try:
            result = _json_from_text(response_text)
        except Exception:
            logger.exception("Could not parse conflict response from Claude: %s", response_text)
            return {"conflicts": False, "explanation": "Conflict check could not be parsed."}

        return {
            "conflicts": bool(result.get("conflicts")),
            "explanation": str(result.get("explanation") or ""),
        }
