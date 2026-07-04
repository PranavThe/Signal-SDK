from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from api.models import Rule


def evaluate_condition(field: str, operator: str, expected: Any, context: dict[str, Any]) -> bool:
    actual = context.get(field)

    # Check exists operator first before None check
    if operator == "exists":
        return (actual is not None) == expected

    if actual is None:
        return False

    try:
        if operator == "eq":
            return actual == expected
        if operator == "neq":
            return actual != expected
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
        if operator == "in":
            return actual in expected
        if operator == "not_in":
            return actual not in expected
        if operator == "contains":
            return expected in actual
    except TypeError:
        return False

    return False


def rule_matches(rule: Rule, context: dict[str, Any]) -> bool:
    return all(
        evaluate_condition(
            field=str(condition.get("field")),
            operator=str(condition.get("operator")),
            expected=condition.get("value"),
            context=context,
        )
        for condition in rule.structured_conditions
    )


def rule_applies_to_agent(rule: Rule, agent_id: str) -> bool:
    return not rule.agent_scope or agent_id in rule.agent_scope


def matching_rules_for_context(rules: list[Rule], context: dict[str, Any], agent_id: str) -> list[Rule]:
    return [
        rule
        for rule in rules
        if rule.status == "active"
        and rule_applies_to_agent(rule, agent_id)
        and rule_matches(rule, context)
    ]


def action_signature(rule: Rule) -> str:
    action = str((rule.structured_action or {}).get("action", "proceed")).lower()
    if action in {"block", "reject", "deny", "skip"}:
        return "block"
    if action in {"proceed", "approve", "allow", "notify", "yes"}:
        return "proceed"
    if action == "modify":
        return json.dumps(rule.structured_action or {}, sort_keys=True, separators=(",", ":"))
    return action


def conflicting_actions(rules: list[Rule]) -> bool:
    return len({action_signature(rule) for rule in rules}) > 1


def _timestamp_key(value: datetime | None) -> datetime:
    return value if value is not None else datetime.min.replace(tzinfo=UTC)


def rule_precedence_key(rule: Rule) -> tuple[int, datetime, datetime, str]:
    return (
        rule.trigger_count,
        _timestamp_key(rule.updated_at),
        _timestamp_key(rule.created_at),
        str(rule.id),
    )


def most_specific_rules(rules: list[Rule]) -> list[Rule]:
    if not rules:
        return []
    max_specificity = max(len(rule.structured_conditions) for rule in rules)
    return [rule for rule in rules if len(rule.structured_conditions) == max_specificity]


def pick_most_specific_rule(rules: list[Rule], context: dict[str, Any], agent_id: str) -> Rule | None:
    candidates = most_specific_rules(matching_rules_for_context(rules, context, agent_id))
    if not candidates or conflicting_actions(candidates):
        return None
    return max(candidates, key=rule_precedence_key)
