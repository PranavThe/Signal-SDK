from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from httpx_sse import aconnect_sse

logger = logging.getLogger("signal")


_NON_WORD_RE = re.compile(r"[^a-zA-Z0-9]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_PERSON_SCALAR_FIELDS = {
    "actor",
    "approver",
    "author",
    "creator",
    "owner",
    "requester",
    "reviewer",
    "submitter",
    "user",
}
_BUILTIN_CONTEXT_ALIASES_RAW = {
    "allowed pairs": "route.pair.cap",
    "allowed_pairs": "route.pair.cap",
    "departure date": "departure.date",
    "departure_date": "departure.date",
    "destination airport": "destination.airports",
    "destination airports": "destination.airports",
    "destinations": "destination.airports",
    "non stop": "nonstop.only",
    "non-stop": "nonstop.only",
    "non_stop": "nonstop.only",
    "nonstop": "nonstop.only",
    "nonstop only": "nonstop.only",
    "nonstop_only": "nonstop.only",
    "operational risk": "operational.risk",
    "origin airport": "origin.airports",
    "origin airports": "origin.airports",
    "origins": "origin.airports",
    "provider limitation": "provider.limitation",
    "provider limitations": "provider.limitation",
    "requested pairs": "requested.route.pairs",
    "requested route pairs": "requested.route.pairs",
    "requested_pairs": "requested.route.pairs",
    "return date": "return.date",
    "return_date": "return.date",
    "route pair cap": "route.pair.cap",
    "route-pair cap": "route.pair.cap",
    "route_pair_cap": "route.pair.cap",
    "route pairs requested": "requested.route.pairs",
    "routes requested per pair": "routes.requested.per.pair",
    "routes requested per route pair": "routes.requested.per.pair",
    "routes_requested_per_pair": "routes.requested.per.pair",
    "sensitive data": "sensitive.data.included",
    "sensitive data included": "sensitive.data.included",
    "trip type": "trip.type",
}


def canonicalize_field_name(field: str) -> str:
    value = str(field or "").strip()
    value = _CAMEL_RE.sub(".", value)
    value = _NON_WORD_RE.sub(".", value)
    return re.sub(r"\.+", ".", value).strip(".").lower()


def _canonicalize_scalar_field(field: str) -> str:
    canonical = canonicalize_field_name(field)
    if canonical in _PERSON_SCALAR_FIELDS:
        return f"{canonical}.name"
    return canonical


def _generated_aliases_for_field(canonical_name: str) -> set[str]:
    aliases = {canonical_name, canonical_name.replace(".", "_"), canonical_name.replace(".", "-")}
    parts = canonical_name.split(".")
    if len(parts) > 1:
        aliases.add("".join([parts[0], *[part.title() for part in parts[1:]]]))
    return {alias for alias in aliases if alias}


def builtin_context_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for raw_alias, raw_canonical in _BUILTIN_CONTEXT_ALIASES_RAW.items():
        canonical = _canonicalize_scalar_field(raw_canonical)
        aliases[_canonicalize_scalar_field(raw_alias)] = canonical
        aliases[_canonicalize_scalar_field(raw_alias.replace(" ", "_"))] = canonical
        aliases[_canonicalize_scalar_field(raw_alias.replace(" ", "-"))] = canonical
        aliases[_canonicalize_scalar_field(canonical)] = canonical
        for generated in _generated_aliases_for_field(canonical):
            aliases[_canonicalize_scalar_field(generated)] = canonical
    return aliases


def normalize_context(context: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    normalized: dict[str, Any] = {}
    warnings: list[str] = []
    aliases = builtin_context_aliases()

    def visit(value: Any, prefix: str = "") -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = canonicalize_field_name(str(raw_key))
                path = f"{prefix}.{key}" if prefix else key
                visit(child, path)
            return
        normalized_prefix = _canonicalize_scalar_field(prefix)
        field = aliases.get(normalized_prefix, normalized_prefix)
        if not field:
            return
        if field in normalized and normalized[field] != value:
            warnings.append(f"Multiple values mapped to canonical field '{field}'.")
        normalized[field] = value
        if field != prefix:
            warnings.append(f"Normalized context field '{prefix}' to '{field}'.")

    visit(context or {})
    return normalized, warnings


class EscalationResult:
    def __init__(self, decision: str, rule_id: str | None, auto_resolved: bool = False):
        self.decision = decision
        self.rule_id = rule_id
        self.auto_resolved = auto_resolved


class CheckResult:
    def __init__(
        self,
        result: str,
        rule_id: str | None,
        reasoning: str,
        modification: dict | None,
        context_warnings: list[str] | None = None,
    ):
        self.result = result
        self.rule_id = rule_id
        self.reasoning = reasoning
        self.modification = modification
        self.context_warnings = context_warnings or []


class Signal:
    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        dev_mode: bool = False,
        auto_enrich: bool = True,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.dev_mode = dev_mode
        self.auto_enrich = auto_enrich

        if dev_mode:
            logging.basicConfig(level=logging.DEBUG)
            logger.setLevel(logging.DEBUG)

    def _enrich_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Auto-enrich context with environment metadata."""
        if not self.auto_enrich:
            return context

        enriched = dict(context)
        enriched.setdefault("_signal_timestamp", datetime.now(timezone.utc).isoformat())
        enriched.setdefault("_signal_environment", os.environ.get("ENVIRONMENT", "unknown"))

        return enriched

    async def escalate(
        self,
        context: str | dict[str, Any],
        question: str,
        agent_id: str,
        metadata: dict[str, Any] | None = None,
        action: str | None = None,
        timeout_seconds: int = 3600,
        poll_interval_seconds: int = 3,
    ) -> EscalationResult:
        outbound_context = context
        outbound_metadata = dict(metadata or {})
        if isinstance(context, dict):
            # Auto-enrich context
            enriched_context = self._enrich_context(context)
            normalized_context, warnings = normalize_context(enriched_context)
            outbound_context = json.dumps(normalized_context, sort_keys=True)
            outbound_metadata.setdefault("_signal_raw_context", context)
            if warnings:
                outbound_metadata.setdefault("_signal_context_warnings", warnings)

        deadline = time.monotonic() + timeout_seconds
        timeout = httpx.Timeout(30.0, read=None)
        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=timeout) as client:
            if self.dev_mode:
                logger.debug(f"Creating escalation: agent_id={agent_id}, action={action}")
                logger.debug(f"Context: {outbound_context[:200]}...")

            response = await client.post(
                "/v1/escalations",
                json={
                    "context": outbound_context,
                    "question": question,
                    "agent_id": agent_id,
                    "action": action,
                    "metadata": outbound_metadata,
                },
            )
            response.raise_for_status()
            response_data = response.json()
            escalation_id = response_data["escalation_id"]

            # Display context warnings from API
            api_warnings = response_data.get("context_warnings", [])
            if api_warnings:
                for warning in api_warnings:
                    logger.warning(f"Context validation: {warning}")
                if self.dev_mode:
                    logger.debug(f"Received {len(api_warnings)} context warnings from API")

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
        # Auto-enrich context
        enriched_context = self._enrich_context(context)
        normalized_context, local_warnings = normalize_context(enriched_context)

        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=30.0) as client:
            if self.dev_mode:
                logger.debug(f"Checking policy: action={action}, agent_id={agent_id}")
                logger.debug(f"Normalized context: {json.dumps(normalized_context, indent=2)[:200]}...")

            response = await client.post(
                "/v1/check",
                json={
                    "action": action,
                    "agent_id": agent_id,
                    "context": normalized_context,
                },
            )
            response.raise_for_status()
            data = response.json()

        all_warnings = [*local_warnings, *(data.get("context_warnings") or [])]
        if all_warnings and self.dev_mode:
            logger.debug(f"Check returned {len(all_warnings)} context warnings")

        return CheckResult(
            result=data["result"],
            rule_id=data["rule_id"],
            reasoning=data["reasoning"],
            modification=data["modification"],
            context_warnings=all_warnings,
        )
