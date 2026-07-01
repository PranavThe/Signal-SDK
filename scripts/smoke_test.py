from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

import httpx

from signal_sdk import Signal


@dataclass
class Result:
    name: str
    passed: bool
    detail: str = ""


def _expect(condition: bool, detail: str = "") -> tuple[bool, str]:
    return condition, detail


async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict | None = None,
) -> httpx.Response:
    return await client.request(method, path, headers=headers, json=json_body)


async def run_smoke() -> list[Result]:
    base_url = os.getenv("SIGNAL_TEST_BASE_URL", "https://signal-omega-tan.vercel.app").rstrip("/")
    api_key = os.getenv("SIGNAL_TEST_API_KEY")
    completed_escalation_id = os.getenv("SIGNAL_TEST_COMPLETED_ESCALATION_ID")
    if not api_key:
        raise SystemExit("Set SIGNAL_TEST_API_KEY before running smoke tests.")

    auth = {"Authorization": f"Bearer {api_key}"}
    json_auth = {**auth, "Content-Type": "application/json"}
    results: list[Result] = []

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        response = await _request(client, "GET", "/health")
        results.append(Result("health", response.status_code == 200 and response.json().get("status") == "ok"))

        for path in ("/dashboard", "/dashboard/rules", "/dashboard/escalations"):
            response = await _request(client, "GET", path)
            results.append(Result(f"dashboard {path}", response.status_code == 200 and "Signal" in response.text))

        response = await _request(
            client,
            "POST",
            "/v1/check",
            headers={"Authorization": "Bearer sk_dev_changeme", "Content-Type": "application/json"},
            json_body={"action": "qa_noop", "agent_id": "qa-agent", "context": {"qa": True}},
        )
        results.append(Result("old dev key rejected", response.status_code == 401))

        response = await _request(
            client,
            "POST",
            "/v1/check",
            headers=json_auth,
            json_body={"action": "qa_noop", "agent_id": "qa-agent", "context": {"qa": True}},
        )
        ok = response.status_code == 200 and {"result", "rule_id", "reasoning", "modification"} <= set(response.json())
        results.append(Result("valid check", ok, f"status={response.status_code}"))

        response = await _request(client, "GET", "/admin/summary", headers=auth)
        payload = response.json() if response.status_code == 200 else {}
        ok = response.status_code == 200 and "totals" in payload and "latest" in payload
        results.append(Result("admin summary", ok, f"status={response.status_code}"))

        response = await _request(client, "POST", "/admin/lifecycle/run-consolidation", headers=auth)
        payload = response.json() if response.status_code == 200 else {}
        ok = response.status_code == 200 and {"orgs", "pairs_checked", "suggestions_created"} <= set(payload)
        results.append(Result("manual consolidation", ok, f"status={response.status_code}"))

        if completed_escalation_id:
            async with client.stream(
                "GET",
                f"/v1/escalations/{completed_escalation_id}/stream",
                headers=auth,
            ) as stream:
                text = ""
                async for chunk in stream.aiter_text():
                    text += chunk
                    if "event: response" in text and "data:" in text:
                        break
            results.append(Result("completed escalation SSE", "event: response" in text and "data:" in text))

    signal = Signal(api_key=api_key, base_url=base_url)
    check = await signal.check(action="qa_noop", agent_id="qa-agent", context={"qa": True})
    results.append(Result("python sdk check", bool(check.result and check.reasoning)))

    secret = "qa_webhook_secret"
    body = json.dumps({"event": "qa.test", "timestamp": "2026-01-01T00:00:00Z", "data": {"ok": True}}).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    results.append(Result("webhook hmac shape", hmac.compare_digest(signature, expected)))

    return results


def main() -> None:
    results = asyncio.run(run_smoke())
    failed = [result for result in results if not result.passed]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        detail = f" ({result.detail})" if result.detail else ""
        print(f"{status} {result.name}{detail}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
