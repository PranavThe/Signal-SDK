from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.models import Account, Organization
from api.plans import ACTIVE_BILLING_STATUSES, PAID_TIERS, normalize_tier

try:
    import stripe
except ImportError:  # pragma: no cover - dependency is installed in deployed requirements
    stripe = None  # type: ignore[assignment]


def stripe_price_id_for_tier(tier: str) -> str:
    normalized = normalize_tier(tier)
    if normalized == "pro":
        return settings.stripe_pro_price_id or settings.stripe_price_id
    if normalized == "scale":
        return settings.stripe_scale_price_id or settings.stripe_price_id
    return ""


def billing_configured(tier: str | None = None) -> bool:
    if not settings.stripe_secret_key:
        return False
    if tier is None:
        return bool(settings.stripe_price_id or settings.stripe_pro_price_id or settings.stripe_scale_price_id)
    return bool(stripe_price_id_for_tier(tier))


def billing_is_active(account: Account) -> bool:
    if normalize_tier(account.plan_tier) == "free":
        return True
    return account.billing_status in ACTIVE_BILLING_STATUSES


def _stripe_object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    to_dict_recursive = getattr(value, "to_dict_recursive", None)
    if callable(to_dict_recursive):
        return dict(to_dict_recursive())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    data = getattr(value, "_data", None)
    if isinstance(data, dict):
        return dict(data)
    return dict(value)


def _configure_stripe() -> None:
    if not settings.stripe_secret_key or stripe is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured.",
        )
    stripe.api_key = settings.stripe_secret_key


async def create_checkout_session(
    account: Account,
    email: str,
    tier: str,
) -> str:
    normalized_tier = normalize_tier(tier)
    if normalized_tier not in PAID_TIERS or normalized_tier == "enterprise":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose Pro or Scale to start a subscription.",
        )
    price_id = stripe_price_id_for_tier(normalized_tier)
    if not billing_configured(normalized_tier):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{normalized_tier.title()} subscriptions are not configured.",
        )
    _configure_stripe()

    payload: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": f"{settings.api_base_url}/dashboard/account?billing=success",
        "cancel_url": f"{settings.api_base_url}/dashboard/account?billing=cancelled",
        "client_reference_id": str(account.id),
        "metadata": {"account_id": str(account.id), "plan_tier": normalized_tier},
        "subscription_data": {"metadata": {"account_id": str(account.id), "plan_tier": normalized_tier}},
        "allow_promotion_codes": True,
    }
    if account.stripe_customer_id:
        payload["customer"] = account.stripe_customer_id
    else:
        payload["customer_email"] = email

    checkout_session = await asyncio.to_thread(stripe.checkout.Session.create, **payload)
    checkout_session_data = _stripe_object_to_dict(checkout_session)
    url = str(checkout_session_data.get("url") or "")
    if not url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe did not return a subscription page URL.",
        )
    return url


def construct_webhook_event(body: bytes, signature: str | None) -> Any:
    if not settings.stripe_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook is not configured.",
        )
    try:
        return stripe.Webhook.construct_event(body, signature, settings.stripe_webhook_secret)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe webhook") from exc


def _timestamp_to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except Exception:
        return None


async def _find_org_for_stripe_object(session: AsyncSession, data: dict[str, Any]) -> Organization | None:
    org_id = data.get("metadata", {}).get("org_id") or data.get("client_reference_id")
    if org_id:
        org = await session.get(Organization, org_id)
        if org is not None:
            return org

    customer_id = data.get("customer")
    subscription_id = data.get("subscription") or data.get("id")
    if not customer_id and not subscription_id:
        return None

    return (
        await session.execute(
            select(Organization).where(
                or_(
                    Organization.stripe_customer_id == customer_id,
                    Organization.stripe_subscription_id == subscription_id,
                )
            )
        )
    ).scalar_one_or_none()


def _tier_from_stripe_object(data: dict[str, Any]) -> str | None:
    metadata_tier = data.get("metadata", {}).get("plan_tier")
    if metadata_tier:
        return normalize_tier(str(metadata_tier))

    try:
        price_id = data["items"]["data"][0]["price"]["id"]
    except Exception:
        price_id = None
    if not price_id:
        return None
    if price_id == (settings.stripe_scale_price_id or ""):
        return "scale"
    if price_id == (settings.stripe_pro_price_id or settings.stripe_price_id):
        return "pro"
    return None


async def _find_account_for_stripe_object(session: AsyncSession, data: dict[str, Any]) -> Account | None:
    account_id = data.get("metadata", {}).get("account_id") or data.get("client_reference_id")
    if account_id:
        account = await session.get(Account, account_id)
        if account is not None:
            return account

    legacy_org = await _find_org_for_stripe_object(session, data)
    if legacy_org is not None and legacy_org.account_id:
        account = await session.get(Account, legacy_org.account_id)
        if account is not None:
            return account

    customer_id = data.get("customer")
    subscription_id = data.get("subscription") or data.get("id")
    if not customer_id and not subscription_id:
        return None

    return (
        await session.execute(
            select(Account).where(
                or_(
                    Account.stripe_customer_id == customer_id,
                    Account.stripe_subscription_id == subscription_id,
                )
            )
        )
    ).scalar_one_or_none()


async def apply_stripe_event(session: AsyncSession, event: Any) -> bool:
    event_data = _stripe_object_to_dict(event)
    event_type = str(event_data.get("type") or "")
    data = dict(event_data.get("data", {}).get("object", {}))
    account = await _find_account_for_stripe_object(session, data)
    if account is None:
        return False

    if event_type == "checkout.session.completed":
        account.stripe_customer_id = data.get("customer") or account.stripe_customer_id
        account.stripe_subscription_id = data.get("subscription") or account.stripe_subscription_id
        account.plan_tier = _tier_from_stripe_object(data) or normalize_tier(account.plan_tier)
        account.billing_status = "active"
        return True

    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        account.stripe_customer_id = data.get("customer") or account.stripe_customer_id
        account.stripe_subscription_id = data.get("id") or account.stripe_subscription_id
        account.plan_tier = _tier_from_stripe_object(data) or normalize_tier(account.plan_tier)
        account.billing_status = str(data.get("status") or account.billing_status)
        account.billing_current_period_end = _timestamp_to_datetime(data.get("current_period_end"))
        return True

    if event_type == "customer.subscription.deleted":
        account.stripe_subscription_id = data.get("id") or account.stripe_subscription_id
        account.billing_status = "canceled"
        account.plan_tier = "free"
        account.billing_current_period_end = _timestamp_to_datetime(data.get("current_period_end"))
        return True

    return False
