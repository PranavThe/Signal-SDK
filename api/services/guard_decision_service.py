from __future__ import annotations

from typing import Any

from api.models import Rule
from api.schemas import GuardDecision


OUTCOME_SCHEMA_VERSION = "1.0"
SAFE_REVIEW_RESPONSE = "I need to send this for review before I can continue."

_ALLOW_ACTIONS = {"allow", "approve", "proceed", "yes", "notify"}
_BLOCK_ACTIONS = {"block", "reject", "deny", "skip", "no"}


class _TemplateValues(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def normalize_guard_decision(value: Any) -> str:
    normalized = str(value or "allow").strip().lower()
    if normalized in _ALLOW_ACTIONS:
        return "allow"
    if normalized in _BLOCK_ACTIONS:
        return "block"
    if normalized == "modify":
        return "modify"
    if normalized == "escalate":
        return "escalate"
    return "escalate"


def _outcome(rule: Rule) -> dict[str, Any]:
    action = rule.structured_action or {}
    outcome = action.get("outcome")
    return outcome if isinstance(outcome, dict) else {}


def _flatten_values(value: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    flattened: dict[str, Any] = {}
    for raw_key, child in value.items():
        key = str(raw_key)
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            flattened.update(_flatten_values(child, path))
            continue
        flattened[path] = child
        flattened[path.replace(".", "_")] = child
        if "." not in path:
            flattened[key] = child
    return flattened


def render_customer_response(template: str | None, facts: dict[str, Any], context: dict[str, Any]) -> str | None:
    if not template or not template.strip():
        return None

    values = _TemplateValues()
    values.update(_flatten_values(context))
    values.update(_flatten_values(facts))
    values.update(facts)
    try:
        return template.format_map(values)
    except Exception:
        return template


def prescribed_action_for_rule(rule: Rule, *, action_name: str = "proceed") -> str:
    structured_action = rule.structured_action or {}
    outcome = _outcome(rule)
    decision = normalize_guard_decision(outcome.get("decision") or structured_action.get("action"))
    return str(
        outcome.get("prescribed_action")
        or structured_action.get("prescribed_action")
        or ("proceed" if decision == "allow" else structured_action.get("action") or action_name)
    )


def guard_decision_from_rule(
    rule: Rule,
    *,
    action_name: str,
    internal_reason: str,
    context: dict[str, Any],
    context_warnings: list[str] | None = None,
) -> GuardDecision:
    structured_action = rule.structured_action or {}
    outcome = _outcome(rule)
    decision = normalize_guard_decision(outcome.get("decision") or structured_action.get("action"))
    outcome_parameters = outcome.get("parameters") if isinstance(outcome.get("parameters"), dict) else None
    legacy_parameters = structured_action.get("parameters") if isinstance(structured_action.get("parameters"), dict) else None
    parameters = outcome_parameters or legacy_parameters or {}
    prescribed_action = prescribed_action_for_rule(rule, action_name=action_name)
    facts = outcome.get("facts") if isinstance(outcome.get("facts"), dict) else {}
    handoff = outcome.get("handoff") if isinstance(outcome.get("handoff"), dict) else None

    return GuardDecision(
        decision=decision,  # type: ignore[arg-type]
        allowed=decision == "allow",
        prescribed_action=prescribed_action,
        customer_response=render_customer_response(
            str(outcome.get("customer_response_template") or ""),
            facts,
            context,
        ),
        internal_reason=internal_reason,
        rule_id=rule.id,
        confidence=rule.extraction_confidence,
        requires_human=bool(outcome.get("requires_human")) or decision == "escalate",
        handoff=handoff,
        modification=parameters if decision == "modify" else None,
        context_warnings=context_warnings or [],
    )


def allow_guard_decision(*, internal_reason: str, context_warnings: list[str] | None = None) -> GuardDecision:
    return GuardDecision(
        decision="allow",
        allowed=True,
        prescribed_action="proceed",
        customer_response=None,
        internal_reason=internal_reason,
        rule_id=None,
        confidence=None,
        requires_human=False,
        handoff=None,
        modification=None,
        context_warnings=context_warnings or [],
    )


def conflict_guard_decision(rule_ids: list[str], *, context_warnings: list[str] | None = None) -> GuardDecision:
    return GuardDecision(
        decision="escalate",
        allowed=False,
        prescribed_action="escalate_for_human_review",
        customer_response=SAFE_REVIEW_RESPONSE,
        internal_reason=(
            "Conflicting active rules matched this context, so Signal will not choose automatically. "
            f"Matching rule IDs: {', '.join(rule_ids)}"
        ),
        rule_id=None,
        confidence=None,
        requires_human=True,
        handoff=None,
        modification=None,
        context_warnings=context_warnings or [],
    )


def validate_rule_outcome_for_activation(rule: Rule) -> list[str]:
    structured_action = rule.structured_action or {}
    outcome = _outcome(rule)
    if not outcome:
        return []

    errors: list[str] = []
    if str(outcome.get("schema_version") or "") != OUTCOME_SCHEMA_VERSION:
        errors.append(f"Outcome schema version must be {OUTCOME_SCHEMA_VERSION}.")

    decision = normalize_guard_decision(outcome.get("decision") or structured_action.get("action"))
    if decision != "allow":
        if not str(outcome.get("prescribed_action") or "").strip():
            errors.append("Non-allow outcomes must include prescribed_action.")
        if not str(outcome.get("customer_response_template") or "").strip():
            errors.append("Non-allow outcomes must include an approved customer_response_template.")

    return errors


def decision_payload(decision: GuardDecision) -> dict[str, Any]:
    return decision.model_dump(mode="json")
