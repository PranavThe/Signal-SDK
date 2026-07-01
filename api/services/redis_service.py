from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as redis

from api.config import settings
from api.models import Escalation


logger = logging.getLogger(__name__)
_client: redis.Redis | None = None


def escalation_response_channel(escalation_id: str) -> str:
    return f"escalation_responses:{escalation_id}"


def _json_default(value: Any) -> str:
    return str(value)


def _client_for_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def publish_escalation_event(escalation_id: str, payload: dict[str, Any]) -> bool:
    try:
        await _client_for_redis().publish(
            escalation_response_channel(escalation_id),
            json.dumps(payload, default=_json_default),
        )
        return True
    except Exception:
        logger.exception("Could not publish Redis escalation event for %s", escalation_id)
        return False


async def publish_escalation_created(escalation: Escalation) -> bool:
    return await publish_escalation_event(
        str(escalation.id),
        {
            "event": "created",
            "escalation_id": str(escalation.id),
            "status": escalation.status,
        },
    )


async def publish_escalation_response(escalation: Escalation) -> bool:
    return await publish_escalation_event(
        str(escalation.id),
        {
            "event": "response",
            "escalation_id": str(escalation.id),
            "status": escalation.status,
            "human_decision": escalation.human_decision,
            "rule_id": str(escalation.rule_id) if escalation.rule_id else None,
            "auto_resolved": escalation.auto_resolved,
            "finalized": escalation.finalized_at is not None,
            "finalization_reason": escalation.finalization_reason,
            "reasoning": escalation.human_reasoning,
            "responded_at": escalation.responded_at,
        },
    )


async def acquire_rule_trigger_webhook_slot(rule_id: str) -> bool:
    try:
        acquired = await _client_for_redis().set(f"webhook:rule_triggered:{rule_id}", "1", ex=60, nx=True)
        return bool(acquired)
    except Exception:
        logger.exception("Could not check Redis webhook rate limit for rule %s", rule_id)
        return True


async def subscribe_escalation_events(escalation_id: str) -> AsyncGenerator[dict[str, Any], None]:
    pubsub = _client_for_redis().pubsub()
    channel = escalation_response_channel(escalation_id)
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if not data:
                continue
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                logger.warning("Ignoring malformed Redis event on %s", channel)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
