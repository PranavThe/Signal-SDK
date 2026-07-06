from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Rule
from api.services.semantic_service import find_similar_rules

logger = logging.getLogger(__name__)


@dataclass
class DuplicateRuleWarning:
    existing_rule_id: str
    existing_condition: str
    existing_action: str
    similarity: float
    is_exact_match: bool
    explanation: str


class DuplicateRuleService:
    async def check_for_duplicates(
        self,
        session: AsyncSession,
        new_rule: Rule,
        embedding: list[float] | None = None,
        similarity_threshold: float = 0.85,
    ) -> list[DuplicateRuleWarning]:
        """Check if a rule is a duplicate or very similar to existing rules."""
        warnings = []

        # First check for exact structural duplicates
        exact_duplicates = await self._find_exact_duplicates(session, new_rule)
        for existing_rule in exact_duplicates:
            warnings.append(
                DuplicateRuleWarning(
                    existing_rule_id=str(existing_rule.id),
                    existing_condition=existing_rule.condition_description,
                    existing_action=existing_rule.action_description,
                    similarity=1.0,
                    is_exact_match=True,
                    explanation="This rule has identical conditions and action to an existing rule.",
                )
            )

        # Then check for semantic similarity using embeddings
        if embedding is not None:
            similar_rules = await find_similar_rules(
                session,
                embedding,
                str(new_rule.id),
                str(new_rule.org_id) if new_rule.org_id else None,
                limit=5,
            )

            existing_ids = {w.existing_rule_id for w in warnings}
            for similar in similar_rules:
                rule_id = str(similar["id"])
                similarity = float(similar["similarity"])

                # Skip if already found as exact match or below threshold
                if rule_id in existing_ids or similarity < similarity_threshold:
                    continue

                # Check if actions are the same (potential duplicate)
                existing_rule = await session.get(Rule, UUID(rule_id))
                if existing_rule and self._same_action(new_rule, existing_rule):
                    explanation = self._generate_similarity_explanation(similarity)
                    warnings.append(
                        DuplicateRuleWarning(
                            existing_rule_id=rule_id,
                            existing_condition=str(similar["condition_description"]),
                            existing_action=str(similar["action_description"]),
                            similarity=similarity,
                            is_exact_match=False,
                            explanation=explanation,
                        )
                    )

        return warnings

    async def _find_exact_duplicates(
        self,
        session: AsyncSession,
        new_rule: Rule,
    ) -> list[Rule]:
        """Find rules with exact same structured conditions and action."""
        result = await session.execute(
            select(Rule)
            .where(
                Rule.org_id == new_rule.org_id,
                Rule.id != new_rule.id,
                Rule.status.in_(["active", "pending_approval"]),
            )
        )
        all_rules = result.scalars().all()

        exact_duplicates = []
        for existing_rule in all_rules:
            if (
                self._same_conditions(new_rule, existing_rule)
                and self._same_action(new_rule, existing_rule)
            ):
                exact_duplicates.append(existing_rule)

        return exact_duplicates

    def _same_conditions(self, rule_a: Rule, rule_b: Rule) -> bool:
        """Check if two rules have identical structured conditions."""
        if len(rule_a.structured_conditions) != len(rule_b.structured_conditions):
            return False

        # Sort conditions by field for comparison
        a_sorted = sorted(
            rule_a.structured_conditions,
            key=lambda c: (str(c.get("field", "")), str(c.get("operator", "")))
        )
        b_sorted = sorted(
            rule_b.structured_conditions,
            key=lambda c: (str(c.get("field", "")), str(c.get("operator", "")))
        )

        for cond_a, cond_b in zip(a_sorted, b_sorted):
            if (
                cond_a.get("field") != cond_b.get("field")
                or cond_a.get("operator") != cond_b.get("operator")
                or cond_a.get("value") != cond_b.get("value")
            ):
                return False

        return True

    def _same_action(self, rule_a: Rule, rule_b: Rule) -> bool:
        """Check if two rules have the same action."""
        return rule_a.structured_action.get("decision") == rule_b.structured_action.get("decision")

    def _generate_similarity_explanation(self, similarity: float) -> str:
        """Generate a human-readable explanation based on similarity score."""
        if similarity >= 0.95:
            return "This rule is nearly identical to an existing rule. The conditions may differ only in wording."
        elif similarity >= 0.90:
            return "This rule is very similar to an existing rule. Consider if they should be consolidated."
        elif similarity >= 0.85:
            return "This rule shares significant overlap with an existing rule. Review to ensure they serve different purposes."
        else:
            return "This rule is somewhat similar to an existing rule."
