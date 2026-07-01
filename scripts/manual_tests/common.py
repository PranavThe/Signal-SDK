from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import delete, select, update

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from api.auth import hash_api_key
from api.database import AsyncSessionLocal
from api.models import (
    ApiKey,
    ConsolidationSuggestion,
    Escalation,
    Organization,
    PolicyCheckLog,
    Rule,
    RuleConflict,
)


DEFAULT_BASE_URL = "https://signal-omega-tan.vercel.app"


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-url",
        default=os.getenv("SIGNAL_TEST_BASE_URL", DEFAULT_BASE_URL),
        help="Signal API base URL. Defaults to SIGNAL_TEST_BASE_URL or production.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("SIGNAL_TEST_API_KEY"),
        help="Signal API key. Defaults to SIGNAL_TEST_API_KEY.",
    )
    parser.add_argument("--timeout", type=int, default=900, help="Seconds to wait for manual steps.")


def require_api_key(api_key: str | None) -> str:
    if not api_key:
        raise SystemExit("Pass --api-key or set SIGNAL_TEST_API_KEY.")
    if api_key == "sk_dev_changeme":
        raise SystemExit(
            "sk_dev_changeme is the old development key and is intentionally invalid now. "
            "Set SIGNAL_TEST_API_KEY to a generated sk_live_... key."
        )
    return api_key


def headers(api_key: str, *, json_content: bool = False) -> dict[str, str]:
    value = {"Authorization": f"Bearer {api_key}"}
    if json_content:
        value["Content-Type"] = "application/json"
    return value


def raise_for_signal_status(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise SystemExit(
            "Signal returned 401 Unauthorized. Use a generated sk_live_... API key, "
            "not sk_dev_changeme."
        )
    response.raise_for_status()


async def lookup_org_id(api_key: str) -> UUID:
    key_hash = hash_api_key(api_key)
    async with AsyncSessionLocal() as session:
        key = (await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))).scalar_one_or_none()
        if key is None:
            raise SystemExit("Could not find this API key in the database.")
        return key.org_id


async def create_escalation(
    base_url: str,
    api_key: str,
    *,
    context: str,
    question: str,
    agent_id: str = "qa-agent",
    action: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=30.0) as client:
        response = await client.post(
            "/v1/escalations",
            headers=headers(api_key, json_content=True),
            json={
                "context": context,
                "question": question,
                "agent_id": agent_id,
                "action": action,
                "metadata": metadata or {},
            },
        )
        raise_for_signal_status(response)
        return str(response.json()["escalation_id"])


async def get_escalation(escalation_id: str) -> Escalation | None:
    async with AsyncSessionLocal() as session:
        return await session.get(Escalation, UUID(escalation_id))


async def get_rule(rule_id: UUID | str | None) -> Rule | None:
    if not rule_id:
        return None
    async with AsyncSessionLocal() as session:
        return await session.get(Rule, UUID(str(rule_id)))


async def wait_for(
    label: str,
    predicate: Callable[[], Awaitable[Any]],
    *,
    timeout: int,
    interval: float = 2.0,
) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {label}")


async def wait_for_response_stream(base_url: str, api_key: str, escalation_id: str, *, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=httpx.Timeout(30.0, read=None)) as client:
        async with client.stream(
            "GET",
            f"/v1/escalations/{escalation_id}/stream",
            headers=headers(api_key),
        ) as response:
            response.raise_for_status()
            event_name = "message"
            async for line in response.aiter_lines():
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Timed out waiting for escalation {escalation_id} SSE response")
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                if line.startswith("data:"):
                    data = json.loads(line.split(":", 1)[1].strip())
                    if event_name == "response" or data.get("status") in {"responded", "timed_out"}:
                        return data
    raise TimeoutError(f"Stream ended before escalation {escalation_id} responded")


async def wait_for_rule_for_escalation(escalation_id: str, *, timeout: int) -> Rule:
    async def predicate() -> Rule | None:
        async with AsyncSessionLocal() as session:
            escalation = await session.get(Escalation, UUID(escalation_id))
            if escalation is None or escalation.rule_id is None:
                return None
            return await session.get(Rule, escalation.rule_id)

    return await wait_for("rule for escalation", predicate, timeout=timeout)


async def wait_for_rule_status(rule_id: UUID | str, status: str, *, timeout: int) -> Rule:
    async def predicate() -> Rule | None:
        async with AsyncSessionLocal() as session:
            rule = await session.get(Rule, UUID(str(rule_id)))
            return rule if rule and rule.status == status else None

    return await wait_for(f"rule {rule_id} status {status}", predicate, timeout=timeout)


async def wait_for_rule_change(rule_id: UUID | str, original_condition: str, *, timeout: int) -> Rule:
    async def predicate() -> Rule | None:
        async with AsyncSessionLocal() as session:
            rule = await session.get(Rule, UUID(str(rule_id)))
            if rule and rule.condition_description != original_condition and rule.status == "pending_approval":
                return rule
            return None

    return await wait_for(f"rule {rule_id} revision", predicate, timeout=timeout)


async def find_conflicts_for_rule(rule_id: UUID | str) -> list[RuleConflict]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(RuleConflict).where(
                    RuleConflict.rule_a_id == UUID(str(rule_id)),
                    RuleConflict.resolved.is_(False),
                )
            )
        ).scalars().all()
        return list(rows)


async def qa_cleanup_org(org_id: UUID, *, delete_escalations: bool = False) -> None:
    async with AsyncSessionLocal() as session:
        if delete_escalations:
            await session.execute(update(Escalation).where(Escalation.org_id == org_id).values(rule_id=None))
        await session.execute(
            delete(RuleConflict).where(
                RuleConflict.rule_a_id.in_(select(Rule.id).where(Rule.org_id == org_id))
            )
        )
        await session.execute(
            delete(ConsolidationSuggestion).where(ConsolidationSuggestion.org_id == org_id)
        )
        await session.execute(delete(PolicyCheckLog).where(PolicyCheckLog.org_id == org_id))
        await session.execute(delete(Rule).where(Rule.org_id == org_id))
        if delete_escalations:
            await session.execute(delete(Escalation).where(Escalation.org_id == org_id))
        await session.execute(delete(ApiKey).where(ApiKey.org_id == org_id))
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


async def restore_webhook(org_id: UUID, webhook_url: str | None, webhook_secret: str | None) -> None:
    async with AsyncSessionLocal() as session:
        org = await session.get(Organization, org_id)
        if org:
            org.webhook_url = webhook_url
            org.webhook_secret = webhook_secret
            await session.commit()


async def set_webhook(org_id: UUID, url: str, secret: str) -> tuple[str | None, str | None]:
    async with AsyncSessionLocal() as session:
        org = await session.get(Organization, org_id)
        if org is None:
            raise SystemExit(f"No organization found: {org_id}")
        old = (org.webhook_url, org.webhook_secret)
        org.webhook_url = url
        org.webhook_secret = secret
        await session.commit()
        return old


def print_step(message: str) -> None:
    print(f"\n==> {message}")


def print_success(message: str) -> None:
    print(f"PASS {message}")
