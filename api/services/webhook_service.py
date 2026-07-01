from __future__ import annotations

import hmac
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import AsyncSessionLocal
from api.models import Organization
from api.services.redis_service import acquire_rule_trigger_webhook_slot


logger = logging.getLogger(__name__)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _signed_headers(body: bytes, secret: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.".encode("utf-8") + body
    signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "User-Agent": "Signal-Webhook/0.1",
        "X-Signal-Signature": f"t={timestamp},v1={signature}",
    }


async def send_webhook_event(org: Organization, event: str, data: dict[str, Any]) -> bool:
    if not org.webhook_url or not org.webhook_secret:
        return False

    payload = {
        "event": event,
        "timestamp": _timestamp(),
        "data": data,
    }
    body = json.dumps(payload, default=_json_default, separators=(",", ":")).encode("utf-8")
    headers = _signed_headers(body, org.webhook_secret)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(org.webhook_url, content=body, headers=headers)
            response.raise_for_status()
        return True
    except Exception:
        logger.exception("Webhook delivery failed for org %s event %s", org.id, event)
        return False


async def send_webhook_event_by_org_id(org_id: UUID | str | None, event: str, data: dict[str, Any]) -> bool:
    if org_id is None:
        return False
    async with AsyncSessionLocal() as session:
        org = await session.get(Organization, org_id)
        if org is None:
            return False
        return await send_webhook_event(org, event, data)


async def send_rule_triggered_webhook(
    session: AsyncSession,
    org_id: UUID,
    rule_id: UUID,
    data: dict[str, Any],
) -> bool:
    if not await acquire_rule_trigger_webhook_slot(str(rule_id)):
        return False
    org = await session.get(Organization, org_id)
    if org is None:
        return False
    return await send_webhook_event(org, "rule.triggered", data)


async def send_rule_triggered_webhook_by_org_id(
    org_id: UUID | str | None,
    rule_id: UUID | str | None,
    data: dict[str, Any],
) -> bool:
    if org_id is None or rule_id is None:
        return False
    if not await acquire_rule_trigger_webhook_slot(str(rule_id)):
        return False
    return await send_webhook_event_by_org_id(org_id, "rule.triggered", data)
