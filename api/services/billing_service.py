from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.models import Organization

try:
    import stripe
except ImportError:  # pragma: no cover - dependency is installed in deployed requirements
    stripe = None  # type: ignore[assignment]


ACTIVE_BILLING_STATUSES = {"active", "trialing"}


def billing_configured() -> bool:
    return bool(settings.stripe_secret_key and settings.stripe_price_id)


def billing_is_active(org: Organization) -> bool:
    return org.billing_status in ACTIVE_BILLING_STATUSES


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
    org: Organization,
    email: str,
) -> str:
    if not billing_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscriptions are not configured.",
        )
    _configure_stripe()

    payload: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": settings.stripe_price_id, "quantity": 1}],
        "success_url": f"{settings.api_base_url}/dashboard/settings?billing=success",
        "cancel_url": f"{settings.api_base_url}/dashboard/settings?billing=cancelled",
        "client_reference_id": str(org.id),
        "metadata": {"org_id": str(org.id)},
        "subscription_data": {"metadata": {"org_id": str(org.id)}},
        "allow_promotion_codes": True,
    }
    if org.stripe_customer_id:
        payload["customer"] = org.stripe_customer_id
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


async def apply_stripe_event(session: AsyncSession, event: Any) -> bool:
    event_data = _stripe_object_to_dict(event)
    event_type = str(event_data.get("type") or "")
    data = dict(event_data.get("data", {}).get("object", {}))
    org = await _find_org_for_stripe_object(session, data)
    if org is None:
        return False

    if event_type == "checkout.session.completed":
        org.stripe_customer_id = data.get("customer") or org.stripe_customer_id
        org.stripe_subscription_id = data.get("subscription") or org.stripe_subscription_id
        org.billing_status = "active"
        return True

    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        org.stripe_customer_id = data.get("customer") or org.stripe_customer_id
        org.stripe_subscription_id = data.get("id") or org.stripe_subscription_id
        org.billing_status = str(data.get("status") or org.billing_status)
        org.billing_current_period_end = _timestamp_to_datetime(data.get("current_period_end"))
        return True

    if event_type == "customer.subscription.deleted":
        org.stripe_subscription_id = data.get("id") or org.stripe_subscription_id
        org.billing_status = "canceled"
        org.billing_current_period_end = _timestamp_to_datetime(data.get("current_period_end"))
        return True

    return False
