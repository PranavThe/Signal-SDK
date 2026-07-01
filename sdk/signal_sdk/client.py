from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
from httpx_sse import aconnect_sse


class EscalationResult:
    def __init__(self, decision: str, rule_id: str | None, auto_resolved: bool = False):
        self.decision = decision
        self.rule_id = rule_id
        self.auto_resolved = auto_resolved


class CheckResult:
    def __init__(self, result: str, rule_id: str | None, reasoning: str, modification: dict | None):
        self.result = result
        self.rule_id = rule_id
        self.reasoning = reasoning
        self.modification = modification


class Signal:
    def __init__(self, api_key: str, base_url: str = "http://localhost:8000"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}

    async def escalate(
        self,
        context: str,
        question: str,
        agent_id: str,
        metadata: dict[str, Any] | None = None,
        action: str | None = None,
        timeout_seconds: int = 3600,
        poll_interval_seconds: int = 3,
    ) -> EscalationResult:
        deadline = time.monotonic() + timeout_seconds
        timeout = httpx.Timeout(30.0, read=None)
        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=timeout) as client:
            response = await client.post(
                "/v1/escalations",
                json={
                    "context": context,
                    "question": question,
                    "agent_id": agent_id,
                    "action": action,
                    "metadata": metadata or {},
                },
            )
            response.raise_for_status()
            escalation_id = response.json()["escalation_id"]

            try:
                return await self._wait_for_stream(client, escalation_id, deadline)
            except Exception:
                return await self._poll_until_response(
                    client,
                    escalation_id,
                    deadline,
                    poll_interval_seconds,
                )

        raise TimeoutError(f"Escalation {escalation_id} did not receive a response in time")

    async def _wait_for_stream(
        self,
        client: httpx.AsyncClient,
        escalation_id: str,
        deadline: float,
    ) -> EscalationResult:
        remaining = max(deadline - time.monotonic(), 0)
        if remaining <= 0:
            raise TimeoutError(f"Escalation {escalation_id} did not receive a response in time")

        async with asyncio.timeout(remaining):
            async with aconnect_sse(client, "GET", f"/v1/escalations/{escalation_id}/stream") as event_source:
                async for sse in event_source.aiter_sse():
                    if not sse.data:
                        continue
                    state = json.loads(sse.data)
                    if state.get("event") == "created":
                        continue
                    finalized = state.get("finalized", state.get("status") == "responded")
                    if finalized:
                        return EscalationResult(
                            decision=state.get("human_decision"),
                            rule_id=state.get("rule_id"),
                            auto_resolved=bool(state.get("auto_resolved")),
                        )
                    if state.get("status") == "timed_out":
                        raise TimeoutError(f"Escalation {escalation_id} timed out")

        raise TimeoutError(f"Escalation {escalation_id} did not receive a response in time")

    async def _poll_until_response(
        self,
        client: httpx.AsyncClient,
        escalation_id: str,
        deadline: float,
        poll_interval_seconds: int,
    ) -> EscalationResult:
        while time.monotonic() < deadline:
            state_response = await client.get(f"/v1/escalations/{escalation_id}")
            state_response.raise_for_status()
            state = state_response.json()

            finalized = state.get("finalized", state["status"] == "responded")
            if finalized:
                return EscalationResult(
                    decision=state["human_decision"],
                    rule_id=state["rule_id"],
                    auto_resolved=bool(state.get("auto_resolved")),
                )
            if state["status"] == "timed_out":
                raise TimeoutError(f"Escalation {escalation_id} timed out")

            await asyncio.sleep(poll_interval_seconds)

        raise TimeoutError(f"Escalation {escalation_id} did not receive a response in time")

    async def check(
        self,
        action: str,
        context: dict[str, Any],
        agent_id: str,
    ) -> CheckResult:
        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=30.0) as client:
            response = await client.post(
                "/v1/check",
                json={
                    "action": action,
                    "agent_id": agent_id,
                    "context": context,
                },
            )
            response.raise_for_status()
            data = response.json()

        return CheckResult(
            result=data["result"],
            rule_id=data["rule_id"],
            reasoning=data["reasoning"],
            modification=data["modification"],
        )
