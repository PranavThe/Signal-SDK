from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import PolicyCheckLog, Rule

logger = logging.getLogger(__name__)


@dataclass
class RuleUsageStats:
    rule_id: str
    condition_description: str
    action_description: str
    status: str
    trigger_count: int
    override_count: int
    last_triggered_at: datetime | None
    created_at: datetime
    days_since_last_trigger: int | None
    triggers_last_7_days: int
    triggers_last_30_days: int
    triggers_last_90_days: int
    is_stale: bool  # No triggers in 90 days


@dataclass
class OrgRuleAnalytics:
    total_rules: int
    active_rules: int
    stale_rules: int
    most_used_rules: list[RuleUsageStats]
    least_used_rules: list[RuleUsageStats]
    recently_created_rules: list[RuleUsageStats]


class RuleAnalyticsService:
    async def get_rule_usage_stats(
        self,
        session: AsyncSession,
        rule_id: UUID,
    ) -> RuleUsageStats | None:
        """Get detailed usage statistics for a specific rule."""
        rule = await session.get(Rule, rule_id)
        if rule is None:
            return None

        now = datetime.now(UTC)
        days_since_last_trigger = None
        if rule.last_triggered_at:
            days_since_last_trigger = (now - rule.last_triggered_at).days

        # Count triggers in different time periods
        triggers_7d = await self._count_triggers_since(session, rule_id, now - timedelta(days=7))
        triggers_30d = await self._count_triggers_since(session, rule_id, now - timedelta(days=30))
        triggers_90d = await self._count_triggers_since(session, rule_id, now - timedelta(days=90))

        is_stale = (
            rule.last_triggered_at is None
            or (now - rule.last_triggered_at).days > 90
        )

        return RuleUsageStats(
            rule_id=str(rule.id),
            condition_description=rule.condition_description,
            action_description=rule.action_description,
            status=rule.status,
            trigger_count=rule.trigger_count,
            override_count=rule.override_count,
            last_triggered_at=rule.last_triggered_at,
            created_at=rule.created_at,
            days_since_last_trigger=days_since_last_trigger,
            triggers_last_7_days=triggers_7d,
            triggers_last_30_days=triggers_30d,
            triggers_last_90_days=triggers_90d,
            is_stale=is_stale,
        )

    async def get_org_analytics(
        self,
        session: AsyncSession,
        org_id: UUID,
        limit: int = 10,
    ) -> OrgRuleAnalytics:
        """Get analytics for all rules in an organization."""
        # Get all active rules for org
        rules_result = await session.execute(
            select(Rule)
            .where(Rule.org_id == org_id)
            .order_by(Rule.created_at.desc())
        )
        all_rules = rules_result.scalars().all()

        # Calculate statistics
        total_rules = len(all_rules)
        active_rules = sum(1 for r in all_rules if r.status == "active")

        now = datetime.now(UTC)
        stale_rules = sum(
            1 for r in all_rules
            if r.status == "active" and (
                r.last_triggered_at is None
                or (now - r.last_triggered_at).days > 90
            )
        )

        # Get detailed stats for each rule
        rule_stats = []
        for rule in all_rules:
            if rule.status != "active":
                continue

            stats = await self.get_rule_usage_stats(session, rule.id)
            if stats:
                rule_stats.append(stats)

        # Sort by different criteria
        most_used = sorted(rule_stats, key=lambda x: x.trigger_count, reverse=True)[:limit]
        least_used = sorted(rule_stats, key=lambda x: x.trigger_count)[:limit]
        recently_created = sorted(rule_stats, key=lambda x: x.created_at, reverse=True)[:limit]

        return OrgRuleAnalytics(
            total_rules=total_rules,
            active_rules=active_rules,
            stale_rules=stale_rules,
            most_used_rules=most_used,
            least_used_rules=least_used,
            recently_created_rules=recently_created,
        )

    async def get_stale_rules(
        self,
        session: AsyncSession,
        org_id: UUID,
        days_threshold: int = 90,
    ) -> list[RuleUsageStats]:
        """Get all rules that haven't been triggered in the specified number of days."""
        now = datetime.now(UTC)
        threshold_date = now - timedelta(days=days_threshold)

        rules_result = await session.execute(
            select(Rule)
            .where(
                Rule.org_id == org_id,
                Rule.status == "active",
            )
        )
        rules = rules_result.scalars().all()

        stale_rules = []
        for rule in rules:
            if rule.last_triggered_at is None or rule.last_triggered_at < threshold_date:
                stats = await self.get_rule_usage_stats(session, rule.id)
                if stats:
                    stale_rules.append(stats)

        return sorted(stale_rules, key=lambda x: x.created_at, reverse=True)

    async def _count_triggers_since(
        self,
        session: AsyncSession,
        rule_id: UUID,
        since_date: datetime,
    ) -> int:
        """Count how many times a rule was triggered since a specific date."""
        result = await session.execute(
            select(func.count())
            .select_from(PolicyCheckLog)
            .where(
                PolicyCheckLog.rule_id == rule_id,
                PolicyCheckLog.result == "allowed",
                PolicyCheckLog.created_at >= since_date,
            )
        )
        count = result.scalar()
        return int(count) if count else 0
