from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Rule
from api.services.context_schema_service import ContextSchemaService

logger = logging.getLogger(__name__)


@dataclass
class RuleTestResult:
    rule_id: str
    condition_description: str
    action_description: str
    test_context: dict[str, Any]
    matched: bool
    action: str | None
    reasoning: str
    matched_conditions: list[dict[str, Any]]
    unmatched_conditions: list[dict[str, Any]]


class RuleTestingService:
    async def test_rule(
        self,
        session: AsyncSession,
        rule_id: UUID,
        test_context: dict[str, Any],
    ) -> RuleTestResult | None:
        """Test a rule against a sample context without persisting anything."""
        rule = await session.get(Rule, rule_id)
        if rule is None:
            return None

        context_result = await ContextSchemaService().normalize(
            session,
            rule.org_id,
            test_context,
            learn=False,
            source="rule_test",
        )
        normalized_context = context_result.normalized
        matched_conditions = []
        unmatched_conditions = []

        # Evaluate each condition
        all_conditions_matched = True
        for condition in rule.structured_conditions:
            if self._evaluate_condition(normalized_context, condition):
                matched_conditions.append(condition)
            else:
                unmatched_conditions.append(condition)
                all_conditions_matched = False

        # Determine action if all conditions matched
        action = None
        reasoning_parts = []

        if all_conditions_matched:
            action = rule.structured_action.get("decision")
            reasoning_parts.append(f"All {len(matched_conditions)} condition(s) matched:")
            for i, cond in enumerate(matched_conditions, 1):
                field = cond.get("field", "unknown")
                operator = cond.get("operator", "unknown")
                value = cond.get("value")
                reasoning_parts.append(f"  {i}. {field} {operator} {value}")
            reasoning_parts.append(f"\nAction: {action}")
        else:
            reasoning_parts.append(f"Rule did not match. {len(matched_conditions)} of {len(rule.structured_conditions)} condition(s) matched.")
            if matched_conditions:
                reasoning_parts.append("\nMatched conditions:")
                for i, cond in enumerate(matched_conditions, 1):
                    field = cond.get("field", "unknown")
                    operator = cond.get("operator", "unknown")
                    value = cond.get("value")
                    reasoning_parts.append(f"  {i}. {field} {operator} {value}")
            if unmatched_conditions:
                reasoning_parts.append("\nUnmatched conditions:")
                for i, cond in enumerate(unmatched_conditions, 1):
                    field = cond.get("field", "unknown")
                    operator = cond.get("operator", "unknown")
                    value = cond.get("value")
                    context_value = self._get_nested_value(normalized_context, field)
                    reasoning_parts.append(f"  {i}. {field} {operator} {value} (actual: {context_value})")

        return RuleTestResult(
            rule_id=str(rule.id),
            condition_description=rule.condition_description,
            action_description=rule.action_description,
            test_context=test_context,
            matched=all_conditions_matched,
            action=action,
            reasoning="\n".join(reasoning_parts),
            matched_conditions=matched_conditions,
            unmatched_conditions=unmatched_conditions,
        )

    def _evaluate_condition(self, context: dict[str, Any], condition: dict[str, Any]) -> bool:
        """Evaluate a single condition against context."""
        field = str(condition.get("field", ""))
        operator = str(condition.get("operator", ""))
        expected_value = condition.get("value")

        actual_value = self._get_nested_value(context, field)

        try:
            if operator == "eq":
                return actual_value == expected_value
            elif operator == "neq":
                return actual_value != expected_value
            elif operator == "gt":
                return actual_value > expected_value
            elif operator == "gte":
                return actual_value >= expected_value
            elif operator == "lt":
                return actual_value < expected_value
            elif operator == "lte":
                return actual_value <= expected_value
            elif operator == "in":
                if isinstance(expected_value, list):
                    return actual_value in expected_value
                return False
            elif operator == "not_in":
                if isinstance(expected_value, list):
                    return actual_value not in expected_value
                return False
            elif operator == "exists":
                if expected_value is True:
                    return actual_value is not None
                elif expected_value is False:
                    return actual_value is None
                return False
            elif operator == "contains":
                if isinstance(actual_value, str) and isinstance(expected_value, str):
                    return expected_value in actual_value
                return False
            else:
                logger.warning(f"Unknown operator: {operator}")
                return False
        except (TypeError, AttributeError) as e:
            logger.warning(f"Error evaluating condition: {e}")
            return False

    def _get_nested_value(self, context: dict[str, Any], field: str) -> Any:
        """Get a potentially nested value from context using dot notation."""
        parts = field.split(".")
        value = context
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
            if value is None:
                return None
        return value

    async def test_rule_against_multiple_contexts(
        self,
        session: AsyncSession,
        rule_id: UUID,
        test_contexts: list[dict[str, Any]],
    ) -> list[RuleTestResult]:
        """Test a rule against multiple sample contexts."""
        results = []
        for context in test_contexts:
            result = await self.test_rule(session, rule_id, context)
            if result:
                results.append(result)
        return results
