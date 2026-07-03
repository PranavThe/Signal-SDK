from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Plan:
    tier: str
    name: str
    price_label: str
    org_limit: int
    api_keys_per_org: int
    description: str


PLANS: dict[str, Plan] = {
    "free": Plan(
        tier="free",
        name="Free",
        price_label="$0/mo",
        org_limit=1,
        api_keys_per_org=1,
        description="For testing Signal in one workspace.",
    ),
    "pro": Plan(
        tier="pro",
        name="Pro",
        price_label="$99/mo",
        org_limit=3,
        api_keys_per_org=5,
        description="For teams running a few agents or environments.",
    ),
    "scale": Plan(
        tier="scale",
        name="Scale",
        price_label="$249/mo",
        org_limit=10,
        api_keys_per_org=20,
        description="For multiple products, teams, or customer-facing agents.",
    ),
    "enterprise": Plan(
        tier="enterprise",
        name="Enterprise",
        price_label="Custom",
        org_limit=10_000,
        api_keys_per_org=10_000,
        description="For custom limits, SSO, retention, and support needs.",
    ),
}

PAID_TIERS = {"pro", "scale", "enterprise"}
ACTIVE_BILLING_STATUSES = {"active", "trialing"}


def normalize_tier(tier: str | None) -> str:
    normalized = (tier or "free").strip().lower()
    return normalized if normalized in PLANS else "free"


def plan_for_tier(tier: str | None) -> Plan:
    return PLANS[normalize_tier(tier)]


def effective_tier(plan_tier: str | None, billing_status: str | None) -> str:
    tier = normalize_tier(plan_tier)
    if tier == "free":
        return "free"
    if tier == "enterprise":
        return "enterprise"
    return tier if (billing_status or "").strip().lower() in ACTIVE_BILLING_STATUSES else "free"


def effective_plan(plan_tier: str | None, billing_status: str | None) -> Plan:
    return plan_for_tier(effective_tier(plan_tier, billing_status))


def plan_payload(plan: Plan, *, current: bool = False, effective: bool = False) -> dict[str, Any]:
    return {
        "tier": plan.tier,
        "name": plan.name,
        "price_label": plan.price_label,
        "org_limit": plan.org_limit,
        "api_keys_per_org": plan.api_keys_per_org,
        "description": plan.description,
        "current": current,
        "effective": effective,
    }
