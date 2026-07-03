from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import string
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, func, or_, select, text, update


ROOT = Path(__file__).resolve().parents[1]
SDK_PATH = ROOT / "sdk"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SDK_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PATH))

import signalops  # noqa: E402
from api.auth import hash_api_key  # noqa: E402
from api.config import settings  # noqa: E402
from api.database import AsyncSessionLocal  # noqa: E402
from api.models import (  # noqa: E402
    Account,
    ApiKey,
    ConsolidationSuggestion,
    DashboardAccountMembership,
    DashboardOrgMembership,
    Escalation,
    Organization,
    PolicyCheckLog,
    Rule,
    RuleConflict,
)
from api.routers.rules import _delete_org_rules  # noqa: E402
from api.services.embedding_service import (  # noqa: E402
    embed,
    save_escalation_embedding,
    save_rule_embedding,
)
from api.services.redis_service import publish_escalation_response  # noqa: E402
from api.services.resolution_propagator import propagate_rule  # noqa: E402
from api.services.review_service import (  # noqa: E402
    mark_escalation_finalized,
    mark_one_time,
    publish_final_escalation_result,
    record_escalation_decision,
)
from api.services.semantic_service import (  # noqa: E402
    find_semantic_rule_match,
    find_similar_escalations,
    find_similar_rules,
)


DEFAULT_BASE_URL = "https://signal-omega-tan.vercel.app"
KEY_PREFIX = "sk_live_"
KEY_RANDOM_LENGTH = 32
VECTOR_SIZE = 1024
Status = Literal["PASS", "FAIL", "SKIP", "CHECK"]


@dataclass
class TestResult:
    area: str
    name: str
    status: Status
    detail: str = ""


@dataclass
class TestOrg:
    id: UUID
    account_id: UUID
    name: str
    api_key: str
    key_id: UUID


class ResultRecorder:
    def __init__(self) -> None:
        self.results: list[TestResult] = []

    def pass_(self, area: str, name: str, detail: str = "") -> None:
        self.results.append(TestResult(area, name, "PASS", detail))
        print(f"PASS  [{area}] {name}{_detail_suffix(detail)}")

    def fail(self, area: str, name: str, detail: str = "") -> None:
        self.results.append(TestResult(area, name, "FAIL", detail))
        print(f"FAIL  [{area}] {name}{_detail_suffix(detail)}")

    def skip(self, area: str, name: str, detail: str = "") -> None:
        self.results.append(TestResult(area, name, "SKIP", detail))
        print(f"SKIP  [{area}] {name}{_detail_suffix(detail)}")

    def check(self, area: str, name: str, detail: str = "") -> None:
        self.results.append(TestResult(area, name, "CHECK", detail))
        print(f"CHECK [{area}] {name}{_detail_suffix(detail)}")

    async def step(self, area: str, name: str, func, *, skip_detail: str | None = None) -> Any:
        if skip_detail:
            self.skip(area, name, skip_detail)
            return None
        try:
            detail = await func()
            self.pass_(area, name, str(detail or ""))
            return detail
        except AssertionError as exc:
            self.fail(area, name, str(exc))
        except Exception as exc:
            self.fail(area, name, f"{type(exc).__name__}: {exc}")
        return None

    def summary(self) -> tuple[int, int, int, int]:
        passed = sum(result.status == "PASS" for result in self.results)
        failed = sum(result.status == "FAIL" for result in self.results)
        skipped = sum(result.status == "SKIP" for result in self.results)
        checks = sum(result.status == "CHECK" for result in self.results)
        return passed, failed, skipped, checks


class WebhookCapture:
    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.events: list[dict[str, Any]] = []
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("Webhook capture server is not running")
        host, port = self._server.server_address
        return f"http://{host}:{port}/webhook"

    def start(self) -> None:
        capture = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                event = json.loads(body.decode("utf-8"))
                capture.events.append(
                    {
                        "body": body,
                        "json": event,
                        "signature": self.headers.get("X-Signal-Signature", ""),
                    }
                )
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    async def wait_for(self, event_name: str, *, timeout: float = 15.0) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in self.events:
                if event["json"].get("event") == event_name:
                    return event
            await asyncio.sleep(0.25)
        return None


def _detail_suffix(detail: str) -> str:
    return f" - {detail}" if detail else ""


def _new_api_key() -> str:
    alphabet = string.ascii_letters + string.digits
    return KEY_PREFIX + "".join(secrets.choice(alphabet) for _ in range(KEY_RANDOM_LENGTH))


def _auth_headers(api_key: str, *, json_content: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def _is_local_url(base_url: str) -> bool:
    return any(host in base_url for host in ("localhost", "127.0.0.1", "0.0.0.0"))


def _is_local_redis_url(redis_url: str) -> bool:
    parsed = urlparse(redis_url)
    return parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _can_drive_sse_from_test_runner(base_url: str) -> bool:
    if _is_local_url(base_url):
        return True
    return not _is_local_redis_url(settings.redis_url)


def _vector(seed: float = 1.0) -> list[float]:
    values = [0.0] * VECTOR_SIZE
    values[0] = seed
    values[1] = 1.0 - min(seed, 0.99)
    return values


def _verify_signal_signature(body: bytes, header: str, secret: str) -> bool:
    parts = dict(part.split("=", 1) for part in header.split(",") if "=" in part)
    timestamp = parts.get("t", "")
    signature = parts.get("v1", "")
    if not timestamp or not signature:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _stripe_signature(body: bytes, secret: str) -> str:
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    return str(value)


async def wait_for(label: str, predicate, *, timeout: float = 20.0, interval: float = 0.5) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {label}")


async def cleanup_orgs(org_ids: list[UUID]) -> None:
    if not org_ids:
        return
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            async with AsyncSessionLocal() as session:
                account_ids = [
                    row
                    for row in (
                        await session.execute(select(Organization.account_id).where(Organization.id.in_(org_ids)))
                    ).scalars()
                    if row is not None
                ]
                rule_ids = [
                    row for row in (await session.execute(select(Rule.id).where(Rule.org_id.in_(org_ids)))).scalars()
                ]
                if rule_ids:
                    await session.execute(update(Rule).where(Rule.id.in_(rule_ids)).values(source_escalation_id=None))
                await session.execute(update(Escalation).where(Escalation.org_id.in_(org_ids)).values(rule_id=None))
                if rule_ids:
                    await session.execute(
                        delete(RuleConflict).where(
                            or_(RuleConflict.rule_a_id.in_(rule_ids), RuleConflict.rule_b_id.in_(rule_ids))
                        )
                    )
                await session.execute(delete(ConsolidationSuggestion).where(ConsolidationSuggestion.org_id.in_(org_ids)))
                await session.execute(delete(PolicyCheckLog).where(PolicyCheckLog.org_id.in_(org_ids)))
                if rule_ids:
                    await session.execute(delete(Rule).where(Rule.id.in_(rule_ids)))
                await session.execute(delete(Escalation).where(Escalation.org_id.in_(org_ids)))
                await session.execute(delete(ApiKey).where(ApiKey.org_id.in_(org_ids)))
                await session.execute(delete(DashboardOrgMembership).where(DashboardOrgMembership.org_id.in_(org_ids)))
                if account_ids:
                    await session.execute(
                        delete(DashboardAccountMembership).where(DashboardAccountMembership.account_id.in_(account_ids))
                    )
                await session.execute(delete(PolicyCheckLog).where(PolicyCheckLog.org_id.in_(org_ids)))
                await session.execute(delete(Organization).where(Organization.id.in_(org_ids)))
                if account_ids:
                    await session.execute(
                        delete(Account).where(
                            Account.id.in_(account_ids),
                            ~select(Organization.id).where(Organization.account_id == Account.id).exists(),
                        )
                    )
                await session.commit()
                return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(attempt)
    if last_error is not None:
        raise last_error


async def create_test_org(run_id: str, name: str, *, billing_status: str = "active") -> TestOrg:
    api_key = _new_api_key()
    async with AsyncSessionLocal() as session:
        account = Account(
            name=f"[MASTER QA {run_id}] {name} account",
            plan_tier="scale",
            billing_status="active",
        )
        session.add(account)
        await session.flush()
        org = Organization(
            name=f"[MASTER QA {run_id}] {name}",
            account_id=account.id,
            slack_notifications_enabled=False,
            billing_status=billing_status,
        )
        session.add(org)
        await session.flush()
        key = ApiKey(
            org_id=org.id,
            key_hash=hash_api_key(api_key),
            key_prefix=api_key[:8],
            name="Master QA",
        )
        session.add(key)
        await session.flush()
        await session.commit()
        return TestOrg(id=org.id, account_id=account.id, name=org.name, api_key=api_key, key_id=key.id)


async def create_rule(
    org_id: UUID,
    run_id: str,
    *,
    case: str,
    action: str,
    status: str = "active",
    agent_scope: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
    conditions: list[dict[str, Any]] | None = None,
    confidence: float = 0.95,
) -> Rule:
    rule = Rule(
        org_id=org_id,
        condition_description=f"[MASTER QA {run_id}] case {case}",
        action_description=f"{action} for master QA case {case}",
        exceptions_note="",
        structured_conditions=conditions or [{"field": "qa_case", "operator": "eq", "value": case}],
        structured_action={"action": action, "parameters": parameters or {}},
        agent_scope=agent_scope or [],
        extraction_confidence=confidence,
        status=status,
    )
    async with AsyncSessionLocal() as session:
        session.add(rule)
        await session.flush()
        await session.commit()
        await session.refresh(rule)
        return rule


async def get_rule(rule_id: UUID | str) -> Rule:
    async with AsyncSessionLocal() as session:
        rule = await session.get(Rule, UUID(str(rule_id)))
        if rule is None:
            raise AssertionError(f"Rule not found: {rule_id}")
        return rule


async def get_escalation(escalation_id: UUID | str) -> Escalation:
    async with AsyncSessionLocal() as session:
        escalation = await session.get(Escalation, UUID(str(escalation_id)))
        if escalation is None:
            raise AssertionError(f"Escalation not found: {escalation_id}")
        return escalation


async def finalize_escalation_one_time(escalation_id: UUID | str, decision: str = "approve") -> None:
    async with AsyncSessionLocal() as session:
        escalation = await session.get(Escalation, UUID(str(escalation_id)))
        if escalation is None:
            raise AssertionError(f"Escalation not found: {escalation_id}")
        await record_escalation_decision(session, escalation, decision)
        await mark_one_time(session, escalation)
        await session.commit()
        await publish_final_escalation_result(escalation)


async def create_escalation_api(
    client: httpx.AsyncClient,
    api_key: str,
    *,
    context: str,
    question: str,
    agent_id: str,
    action: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    response = await client.post(
        "/v1/escalations",
        headers=_auth_headers(api_key, json_content=True),
        json={
            "context": context,
            "question": question,
            "agent_id": agent_id,
            "action": action,
            "metadata": metadata or {},
        },
    )
    response.raise_for_status()
    return str(response.json()["escalation_id"])


async def check_api(
    client: httpx.AsyncClient,
    api_key: str,
    *,
    action: str,
    agent_id: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(
        "/v1/check",
        headers=_auth_headers(api_key, json_content=True),
        json={"action": action, "agent_id": agent_id, "context": context},
    )
    response.raise_for_status()
    return response.json()


async def listen_for_sse(
    client: httpx.AsyncClient,
    api_key: str,
    escalation_id: str,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    async with client.stream(
        "GET",
        f"/v1/escalations/{escalation_id}/stream",
        headers=_auth_headers(api_key),
    ) as response:
        response.raise_for_status()
        event_name = "message"
        async for line in response.aiter_lines():
            if time.monotonic() > deadline:
                raise TimeoutError(f"Timed out waiting for SSE for {escalation_id}")
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            if line.startswith("data:"):
                payload = json.loads(line.split(":", 1)[1].strip())
                if event_name == "response" or payload.get("finalized") or payload.get("status") == "timed_out":
                    return payload
    raise TimeoutError(f"SSE stream ended before final response for {escalation_id}")


async def dashboard_login(
    client: httpx.AsyncClient,
    *,
    email: str,
    password: str,
) -> str:
    config_response = await client.get("/dashboard/auth/config")
    config_response.raise_for_status()
    config = config_response.json()
    assert config.get("configured") is True, "Dashboard auth is not configured"
    supabase_url = str(config["supabase_url"]).rstrip("/")
    supabase_anon_key = str(config["supabase_anon_key"])
    async with httpx.AsyncClient(timeout=30.0) as supabase:
        token_response = await supabase.post(
            f"{supabase_url}/auth/v1/token?grant_type=password",
            headers={"apikey": supabase_anon_key, "Content-Type": "application/json"},
            json={"email": email, "password": password},
        )
    if token_response.status_code != 200:
        raise AssertionError(f"Supabase login failed: {token_response.status_code} {token_response.text[:300]}")
    access_token = token_response.json()["access_token"]
    session_response = await client.post("/dashboard/session", headers={"Authorization": f"Bearer {access_token}"})
    session_response.raise_for_status()
    return access_token


async def run_environment_tests(rec: ResultRecorder, client: httpx.AsyncClient, args: argparse.Namespace) -> None:
    async def health() -> str:
        response = await client.get("/health")
        assert response.status_code == 200, f"status={response.status_code}"
        assert response.json().get("status") == "ok", response.text
        return args.base_url

    await rec.step("environment", "public health endpoint", health)

    async def db_vector() -> str:
        async with AsyncSessionLocal() as session:
            vector = (await session.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))).scalar()
            assert vector == "vector", "pgvector extension is not installed"
            columns = (
                await session.execute(
                    text(
                        """
                        SELECT table_name, column_name
                        FROM information_schema.columns
                        WHERE table_name IN ('rules', 'escalations')
                          AND column_name IN ('condition_embedding', 'context_embedding')
                        """
                    )
                )
            ).all()
            assert len(columns) == 2, f"expected 2 vector columns, found {len(columns)}"
        return "pgvector extension and vector columns exist"

    await rec.step("environment", "pgvector schema", db_vector)

    async def dashboard_public() -> str:
        login = await client.get("/login")
        assert login.status_code == 200, f"/login status={login.status_code}"
        assert "Signal" in login.text, "/login did not render Signal"
        dashboard = await client.get("/dashboard", follow_redirects=False)
        assert dashboard.status_code in {303, 307, 401}, f"/dashboard unauth status={dashboard.status_code}"
        logo = await client.get("/static/signal-logo.png")
        assert logo.status_code == 200, f"logo status={logo.status_code}"
        assert logo.content[:8] == b"\x89PNG\r\n\x1a\n", "logo is not a PNG response"
        return "login renders, dashboard is protected, logo serves"

    await rec.step("dashboard", "public auth boundaries and logo asset", dashboard_public)


async def run_auth_and_org_tests(
    rec: ResultRecorder,
    client: httpx.AsyncClient,
    primary: TestOrg,
    isolated: TestOrg,
    run_id: str,
) -> None:
    async def old_key_rejected() -> str:
        response = await client.post(
            "/v1/check",
            headers=_auth_headers("sk_dev_changeme", json_content=True),
            json={"action": "qa", "agent_id": "qa", "context": {"qa": True}},
        )
        assert response.status_code == 401, f"status={response.status_code}"
        return "legacy sk_dev_changeme is invalid"

    await rec.step("auth", "old development key rejected", old_key_rejected)

    async def valid_key_works() -> str:
        payload = await check_api(
            client,
            primary.api_key,
            action=f"master_noop_{run_id}",
            agent_id="master-auth-agent",
            context={"qa_case": f"no_rule_{run_id}"},
        )
        assert payload["result"] == "proceed", payload
        assert payload["rule_id"] is None, payload
        async with AsyncSessionLocal() as session:
            key = await session.get(ApiKey, primary.key_id)
            assert key and key.last_used_at is not None, "API key last_used_at was not updated"
        return "valid key maps to org and updates last_used_at"

    await rec.step("auth", "valid API key authorizes check", valid_key_works)

    async def org_isolation() -> str:
        rule = await create_rule(isolated.id, run_id, case=f"isolated_{run_id}", action="block")
        primary_payload = await check_api(
            client,
            primary.api_key,
            action="master_isolation",
            agent_id="master-auth-agent",
            context={"qa_case": f"isolated_{run_id}"},
        )
        assert primary_payload["rule_id"] is None, primary_payload
        isolated_payload = await check_api(
            client,
            isolated.api_key,
            action="master_isolation",
            agent_id="master-auth-agent",
            context={"qa_case": f"isolated_{run_id}"},
        )
        assert isolated_payload["rule_id"] == str(rule.id), isolated_payload
        return "rules are scoped by organization"

    await rec.step("auth", "organization data isolation", org_isolation)


async def run_policy_engine_tests(
    rec: ResultRecorder,
    client: httpx.AsyncClient,
    org: TestOrg,
    run_id: str,
) -> dict[str, Rule]:
    created: dict[str, Rule] = {}

    async def no_rule_default() -> str:
        payload = await check_api(
            client,
            org.api_key,
            action="master_default",
            agent_id="master-policy-agent",
            context={"qa_case": f"missing_{run_id}"},
        )
        assert payload["result"] == "proceed", payload
        assert payload["rule_id"] is None, payload
        return "no matching rule proceeds by default"

    await rec.step("policy", "default no-rule behavior", no_rule_default)

    async def exact_actions() -> str:
        proceed = await create_rule(org.id, run_id, case=f"proceed_{run_id}", action="proceed")
        block = await create_rule(org.id, run_id, case=f"block_{run_id}", action="block")
        modify = await create_rule(
            org.id,
            run_id,
            case=f"modify_{run_id}",
            action="modify",
            parameters={"new_value": "master_modified"},
        )
        created.update({"proceed": proceed, "block": block, "modify": modify})
        checks = [
            (proceed, "proceed", None),
            (block, "block", None),
            (modify, "modify", {"new_value": "master_modified"}),
        ]
        for rule, expected, modification in checks:
            payload = await check_api(
                client,
                org.api_key,
                action=f"master_{expected}",
                agent_id="master-policy-agent",
                context={"qa_case": rule.structured_conditions[0]["value"]},
            )
            assert payload["result"] == expected, payload
            assert payload["rule_id"] == str(rule.id), payload
            if modification is not None:
                assert payload["modification"] == modification, payload
        return "proceed, block, and modify actions match"

    await rec.step("policy", "exact structured rule actions", exact_actions)

    async def trigger_logs() -> str:
        rule = created["proceed"]
        refreshed = await get_rule(rule.id)
        assert refreshed.trigger_count >= 1, "trigger_count did not increment"
        assert refreshed.last_triggered_at is not None, "last_triggered_at was not set"
        async with AsyncSessionLocal() as session:
            logs = (
                await session.execute(
                    select(func.count())
                    .select_from(PolicyCheckLog)
                    .where(PolicyCheckLog.org_id == org.id, PolicyCheckLog.rule_id == rule.id)
                )
            ).scalar_one()
        assert logs >= 1, "policy_check_log was not written"
        return f"trigger_count={refreshed.trigger_count}, logs={logs}"

    await rec.step("policy", "policy check logging and rule usage counters", trigger_logs)

    async def agent_scope() -> str:
        scoped = await create_rule(
            org.id,
            run_id,
            case=f"scoped_{run_id}",
            action="block",
            agent_scope=["master-scoped-agent"],
        )
        miss = await check_api(
            client,
            org.api_key,
            action="master_scope",
            agent_id="wrong-agent",
            context={"qa_case": f"scoped_{run_id}"},
        )
        hit = await check_api(
            client,
            org.api_key,
            action="master_scope",
            agent_id="master-scoped-agent",
            context={"qa_case": f"scoped_{run_id}"},
        )
        assert miss["rule_id"] is None, miss
        assert hit["rule_id"] == str(scoped.id), hit
        return "agent scope is enforced"

    await rec.step("policy", "agent-scoped rules", agent_scope)

    async def lifecycle_statuses() -> str:
        rule = await create_rule(org.id, run_id, case=f"status_{run_id}", action="block")
        pause = await client.patch(
            f"/v1/rules/{rule.id}",
            headers=_auth_headers(org.api_key, json_content=True),
            json={"status": "paused"},
        )
        pause.raise_for_status()
        paused_check = await check_api(
            client,
            org.api_key,
            action="master_status",
            agent_id="master-policy-agent",
            context={"qa_case": f"status_{run_id}"},
        )
        assert paused_check["rule_id"] is None, paused_check
        activate = await client.patch(
            f"/v1/rules/{rule.id}",
            headers=_auth_headers(org.api_key, json_content=True),
            json={"status": "active"},
        )
        activate.raise_for_status()
        active_check = await check_api(
            client,
            org.api_key,
            action="master_status",
            agent_id="master-policy-agent",
            context={"qa_case": f"status_{run_id}"},
        )
        assert active_check["rule_id"] == str(rule.id), active_check
        archive = await client.patch(
            f"/v1/rules/{rule.id}",
            headers=_auth_headers(org.api_key, json_content=True),
            json={"status": "archived"},
        )
        archive.raise_for_status()
        archived_check = await check_api(
            client,
            org.api_key,
            action="master_status",
            agent_id="master-policy-agent",
            context={"qa_case": f"status_{run_id}"},
        )
        assert archived_check["rule_id"] is None, archived_check
        return "pause, activate, and archive all affect matching"

    await rec.step("rules", "rule status update API", lifecycle_statuses)

    async def delete_rule() -> str:
        rule = await create_rule(org.id, run_id, case=f"delete_{run_id}", action="block")
        response = await client.delete(f"/v1/rules/{rule.id}", headers=_auth_headers(org.api_key))
        response.raise_for_status()
        assert response.json()["count"] == 1, response.text
        payload = await check_api(
            client,
            org.api_key,
            action="master_delete",
            agent_id="master-policy-agent",
            context={"qa_case": f"delete_{run_id}"},
        )
        assert payload["rule_id"] is None, payload
        return "deleted rule no longer matches"

    await rec.step("rules", "rule delete API", delete_rule)
    return created


async def run_conflict_tests(
    rec: ResultRecorder,
    client: httpx.AsyncClient,
    org: TestOrg,
    run_id: str,
) -> None:
    async def runtime_conflict_escalates() -> str:
        case = f"runtime_conflict_{run_id}"
        rule_a = await create_rule(org.id, run_id, case=case, action="proceed")
        rule_b = await create_rule(org.id, run_id, case=case, action="block")
        payload = await check_api(
            client,
            org.api_key,
            action="master_conflict_runtime",
            agent_id="master-conflict-agent",
            context={"qa_case": case},
        )
        assert payload["result"] == "escalate", payload
        assert payload["rule_id"] is None, payload
        assert str(rule_a.id) in payload["reasoning"] and str(rule_b.id) in payload["reasoning"], payload
        return "conflicting active rules force escalation"

    await rec.step("conflicts", "runtime active-rule conflict handling", runtime_conflict_escalates)

    async def activation_conflict_blocks() -> str:
        case = f"activation_conflict_{run_id}"
        active = await create_rule(org.id, run_id, case=case, action="proceed")
        paused = await create_rule(org.id, run_id, case=case, action="block", status="paused")
        response = await client.patch(
            f"/v1/rules/{paused.id}",
            headers=_auth_headers(org.api_key, json_content=True),
            json={"status": "active"},
        )
        assert response.status_code == 409, f"status={response.status_code}, body={response.text}"
        detail = response.json()["detail"]
        assert "conflict" in json.dumps(detail).lower(), detail
        async with AsyncSessionLocal() as session:
            conflicts = (
                await session.execute(
                    select(RuleConflict).where(
                        RuleConflict.rule_a_id == paused.id,
                        RuleConflict.rule_b_id == active.id,
                        RuleConflict.resolved.is_(False),
                    )
                )
            ).scalars().all()
        assert conflicts, "no rule_conflicts row was written"
        return "activation returns 409 with conflict detail and stores row"

    await rec.step("conflicts", "paused contradictory rule cannot be activated", activation_conflict_blocks)


async def run_vector_and_semantic_tests(
    rec: ResultRecorder,
    client: httpx.AsyncClient,
    org: TestOrg,
    run_id: str,
    *,
    with_ai: bool,
) -> None:
    async def vector_search() -> str:
        rule = await create_rule(org.id, run_id, case=f"semantic_{run_id}", action="block")
        async with AsyncSessionLocal() as session:
            await save_rule_embedding(session, str(rule.id), _vector(0.95))
            await session.commit()
            similar = await find_similar_rules(session, _vector(0.96), str(uuid4()), str(org.id), limit=3)
            semantic = await find_semantic_rule_match(
                session,
                _vector(0.96),
                str(org.id),
                "master-semantic-agent",
                query_text=f"[MASTER QA {run_id}] case semantic_{run_id}",
                threshold=0.1,
            )
        assert any(str(item["id"]) == str(rule.id) for item in similar), similar
        assert semantic is not None and str(semantic[0].id) == str(rule.id), semantic
        return "pgvector similar-rules and semantic-rule lookup work"

    await rec.step("semantic", "vector search over rule embeddings", vector_search)

    async def similar_escalations() -> str:
        first = Escalation(
            org_id=org.id,
            context=f"[MASTER QA {run_id}] similar past decision A",
            question="QA?",
            agent_id="master-semantic-agent",
            metadata_={"qa_case": f"similar_a_{run_id}"},
            status="responded",
            human_decision="approve",
            responded_at=datetime.now(UTC),
            finalized_at=datetime.now(UTC),
            finalization_reason="one_time",
        )
        second = Escalation(
            org_id=org.id,
            context=f"[MASTER QA {run_id}] similar past decision B",
            question="QA?",
            agent_id="master-semantic-agent",
            metadata_={"qa_case": f"similar_b_{run_id}"},
            status="pending",
        )
        async with AsyncSessionLocal() as session:
            session.add_all([first, second])
            await session.flush()
            await save_escalation_embedding(session, str(first.id), _vector(0.90))
            await save_escalation_embedding(session, str(second.id), _vector(0.91))
            await session.commit()
            similar = await find_similar_escalations(session, _vector(0.91), str(second.id), str(org.id), limit=3)
        assert similar and similar[0]["human_decision"] == "approve", similar
        return "similar past decisions query finds responded escalation"

    await rec.step("semantic", "similar past decisions query", similar_escalations)

    async def voyage_embedding() -> str:
        last_error: Exception | None = None
        for attempt, delay in enumerate((0, 10, 30), start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                embedding = await embed(f"[MASTER QA {run_id}] verify voyage embedding path attempt {attempt}")
                break
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code != 429 or attempt == 3:
                    raise
        else:
            raise AssertionError(f"Voyage embedding failed: {last_error}")
        assert len(embedding) == VECTOR_SIZE, f"len={len(embedding)}"
        return "Voyage embedding returned 1024 dimensions"

    await rec.step(
        "semantic",
        "live Voyage embedding generation",
        voyage_embedding,
        skip_detail=None if with_ai and settings.voyage_api_key else "pass --with-ai and configure VOYAGE_API_KEY",
    )

    async def background_escalation_embedding() -> str:
        escalation_id = await create_escalation_api(
            client,
            org.api_key,
            context=f"[MASTER QA {run_id}] background embedding escalation",
            question="Should this be reviewed?",
            agent_id="master-semantic-agent",
            action="master_background_embedding",
            metadata={"qa_run_id": run_id, "qa_case": "background_embedding"},
        )

        async def embedded() -> bool:
            escalation = await get_escalation(escalation_id)
            return escalation.context_embedding is not None

        await wait_for("background escalation embedding", embedded, timeout=45)
        return f"escalation_id={escalation_id}"

    await rec.step(
        "semantic",
        "background escalation embedding on write",
        background_escalation_embedding,
        skip_detail=None if with_ai and settings.voyage_api_key else "pass --with-ai and configure VOYAGE_API_KEY",
    )


async def run_escalation_and_sse_tests(
    rec: ResultRecorder,
    client: httpx.AsyncClient,
    org: TestOrg,
    run_id: str,
    *,
    redis_drivable: bool,
) -> None:
    async def create_and_poll() -> str:
        escalation_id = await create_escalation_api(
            client,
            org.api_key,
            context=f"[MASTER QA {run_id}] basic escalation",
            question="Should the agent proceed?",
            agent_id="master-escalation-agent",
            action="master_basic_escalation",
            metadata={"qa_run_id": run_id, "qa_case": "basic_escalation"},
        )
        response = await client.get(f"/v1/escalations/{escalation_id}", headers=_auth_headers(org.api_key))
        response.raise_for_status()
        state = response.json()
        assert state["status"] == "pending", state
        escalation = await get_escalation(escalation_id)
        assert escalation.org_id == org.id, "escalation org_id mismatch"
        return f"escalation_id={escalation_id}"

    await rec.step("escalations", "create escalation and polling fallback state", create_and_poll)

    async def sse_response() -> str:
        escalation_id = await create_escalation_api(
            client,
            org.api_key,
            context=f"[MASTER QA {run_id}] SSE escalation",
            question="Should the stream resolve?",
            agent_id="master-escalation-agent",
            action="master_sse",
            metadata={"qa_run_id": run_id, "qa_case": "sse"},
        )
        stream_task = asyncio.create_task(listen_for_sse(client, org.api_key, escalation_id, timeout=30))
        await asyncio.sleep(1.0)
        await finalize_escalation_one_time(escalation_id, "approve")
        event = await stream_task
        assert event["human_decision"] == "approve", event
        assert event["finalized"] is True, event
        fallback = await client.get(f"/v1/escalations/{escalation_id}", headers=_auth_headers(org.api_key))
        fallback.raise_for_status()
        assert fallback.json()["finalized"] is True, fallback.text
        return "SSE stream and polling fallback both returned final state"

    redis_skip = None if redis_drivable else "local Redis config does not target the hosted API Redis"
    await rec.step("escalations", "Redis/SSE escalation response stream", sse_response, skip_detail=redis_skip)

    async def sdk_waits_for_one_time_finalization() -> str:
        signalops.configure(api_key=org.api_key, base_url=str(client.base_url))
        context = f"[MASTER QA {run_id}] SDK one-time wait test"
        task = asyncio.create_task(
            signalops.escalate(
                context=context,
                question="Should SDK wait until one-time finalization?",
                agent_id="master-sdk-agent",
                action="master_sdk_wait_one_time",
                metadata={"qa_run_id": run_id, "qa_case": "sdk_one_time"},
                timeout_seconds=60,
            )
        )

        async def created() -> Escalation | None:
            async with AsyncSessionLocal() as session:
                return (
                    await session.execute(
                        select(Escalation).where(Escalation.org_id == org.id, Escalation.context == context)
                    )
                ).scalar_one_or_none()

        escalation = await wait_for("SDK-created escalation", created, timeout=15)
        await asyncio.sleep(1.0)
        assert not task.done(), "SDK returned before any human decision"
        async with AsyncSessionLocal() as session:
            fresh = await session.get(Escalation, escalation.id)
            assert fresh is not None
            await record_escalation_decision(session, fresh, "approve")
            await session.commit()
        await asyncio.sleep(1.0)
        assert not task.done(), "SDK returned after initial decision but before finalization"
        await finalize_escalation_one_time(escalation.id, "approve")
        result = await task
        assert result.decision == "approve", result.__dict__
        assert result.rule_id is None, result.__dict__
        return "signalops.escalate waited until one-time finalization"

    await rec.step(
        "sdk",
        "Python SDK escalate waits for one-time finalization",
        sdk_waits_for_one_time_finalization,
        skip_detail=redis_skip,
    )

    async def sdk_waits_for_rule_approval() -> str:
        signalops.configure(api_key=org.api_key, base_url=str(client.base_url))
        context = f"[MASTER QA {run_id}] SDK rule approval wait test"
        task = asyncio.create_task(
            signalops.escalate(
                context=context,
                question="Should SDK wait until rule approval?",
                agent_id="master-sdk-agent",
                action="master_sdk_wait_rule",
                metadata={"qa_run_id": run_id, "qa_case": f"sdk_rule_{run_id}"},
                timeout_seconds=60,
            )
        )

        async def created() -> Escalation | None:
            async with AsyncSessionLocal() as session:
                return (
                    await session.execute(
                        select(Escalation).where(Escalation.org_id == org.id, Escalation.context == context)
                    )
                ).scalar_one_or_none()

        escalation = await wait_for("SDK-created rule escalation", created, timeout=15)
        async with AsyncSessionLocal() as session:
            fresh = await session.get(Escalation, escalation.id)
            assert fresh is not None
            await record_escalation_decision(session, fresh, "approve")
            rule = Rule(
                org_id=org.id,
                condition_description=f"[MASTER QA {run_id}] SDK wait rule",
                action_description="Approve SDK wait rule",
                exceptions_note="",
                structured_conditions=[{"field": "qa_case", "operator": "eq", "value": f"sdk_rule_{run_id}"}],
                structured_action={"action": "proceed", "parameters": {}},
                agent_scope=[],
                extraction_confidence=0.9,
                status="pending_approval",
                source_escalation_id=fresh.id,
            )
            session.add(rule)
            await session.flush()
            fresh.rule_id = rule.id
            await session.commit()
            rule_id = rule.id
        await asyncio.sleep(1.0)
        assert not task.done(), "SDK returned before pending rule was approved"
        async with AsyncSessionLocal() as session:
            fresh = await session.get(Escalation, escalation.id)
            rule = await session.get(Rule, rule_id)
            assert fresh is not None and rule is not None
            rule.status = "active"
            mark_escalation_finalized(fresh, "rule_approved")
            await session.commit()
            await publish_escalation_response(fresh)
        result = await task
        assert result.decision == "approve", result.__dict__
        assert result.rule_id == str(rule_id), result.__dict__
        return "signalops.escalate waited until rule approval"

    await rec.step(
        "sdk",
        "Python SDK escalate waits for rule approval",
        sdk_waits_for_rule_approval,
        skip_detail=redis_skip,
    )

    async def propagation_auto_resolves() -> str:
        escalation_id = await create_escalation_api(
            client,
            org.api_key,
            context=f"[MASTER QA {run_id}] propagation escalation",
            question="Should a later rule resolve this?",
            agent_id="master-propagation-agent",
            action="master_propagation",
            metadata={"qa_run_id": run_id, "qa_case": f"propagate_{run_id}"},
        )
        stream_task = asyncio.create_task(listen_for_sse(client, org.api_key, escalation_id, timeout=30))
        rule = await create_rule(
            org.id,
            run_id,
            case=f"propagate_{run_id}",
            action="proceed",
            conditions=[{"field": "qa_case", "operator": "eq", "value": f"propagate_{run_id}"}],
        )
        stats = await propagate_rule(rule.id, org.id)
        assert stats["resolved"] >= 1, stats
        event = await stream_task
        assert event["auto_resolved"] is True, event
        assert event["rule_id"] == str(rule.id), event
        return "newly approved rule auto-resolved pending matching escalation"

    await rec.step(
        "escalations",
        "resolution propagator auto-resolves matching pending escalations",
        propagation_auto_resolves,
        skip_detail=redis_skip,
    )


async def run_override_and_lifecycle_tests(
    rec: ResultRecorder,
    client: httpx.AsyncClient,
    org: TestOrg,
    run_id: str,
) -> None:
    async def override_count() -> str:
        rule = await create_rule(org.id, run_id, case=f"override_{run_id}", action="proceed")
        payload = await check_api(
            client,
            org.api_key,
            action="master_override_action",
            agent_id="master-override-agent",
            context={"qa_case": f"override_{run_id}"},
        )
        assert payload["rule_id"] == str(rule.id), payload
        await create_escalation_api(
            client,
            org.api_key,
            context=f"[MASTER QA {run_id}] override escalation",
            question="Human overrode the previous automatic result.",
            agent_id="master-override-agent",
            action="master_override_action",
            metadata={"qa_case": f"override_{run_id}"},
        )
        refreshed = await get_rule(rule.id)
        assert refreshed.override_count >= 1, f"override_count={refreshed.override_count}"
        return f"override_count={refreshed.override_count}"

    await rec.step("lifecycle", "override detection increments rule override_count", override_count)

    async def staleness_endpoint() -> str:
        stale = await create_rule(org.id, run_id, case=f"stale_{run_id}", action="proceed")
        unreliable = await create_rule(org.id, run_id, case=f"unreliable_{run_id}", action="proceed")
        async with AsyncSessionLocal() as session:
            stale_db = await session.get(Rule, stale.id)
            unreliable_db = await session.get(Rule, unreliable.id)
            assert stale_db is not None and unreliable_db is not None
            stale_db.created_at = datetime.now(UTC) - timedelta(days=10)
            stale_db.last_triggered_at = None
            unreliable_db.trigger_count = 10
            unreliable_db.override_count = 3
            await session.commit()
        response = await client.post(
            "/admin/lifecycle/run-staleness?include_new_rules=true",
            headers=_auth_headers(org.api_key),
        )
        response.raise_for_status()
        data = response.json()
        assert data["stale"] >= 1, data
        assert data["unreliable"] >= 1, data
        return f"stale={data['stale']}, unreliable={data['unreliable']}"

    await rec.step("lifecycle", "manual staleness and unreliable-rule scan", staleness_endpoint)

    async def consolidation_accept() -> str:
        rule_a = await create_rule(org.id, run_id, case=f"merge_{run_id}", action="proceed")
        rule_b = await create_rule(
            org.id,
            run_id,
            case=f"merge_{run_id}",
            action="proceed",
            conditions=[{"field": "qa_case", "operator": "eq", "value": f"merge_{run_id}"}],
        )
        async with AsyncSessionLocal() as session:
            suggestion = ConsolidationSuggestion(
                org_id=org.id,
                rule_a_id=rule_a.id,
                rule_b_id=rule_b.id,
                merged_condition=f"[MASTER QA {run_id}] merged rule",
                merged_action="Proceed for merged QA rule",
                reason="Master QA consolidation accept test.",
                status="pending",
            )
            session.add(suggestion)
            await session.flush()
            suggestion_id = suggestion.id
            await session.commit()
        response = await client.post(
            f"/v1/consolidation/{suggestion_id}/accept",
            headers=_auth_headers(org.api_key),
        )
        response.raise_for_status()
        data = response.json()
        merged = await get_rule(data["merged_rule_id"])
        archived_a = await get_rule(rule_a.id)
        archived_b = await get_rule(rule_b.id)
        assert merged.status == "active", merged.status
        assert archived_a.status == "archived" and archived_b.status == "archived", (
            archived_a.status,
            archived_b.status,
        )
        return f"merged_rule_id={merged.id}"

    await rec.step("lifecycle", "consolidation suggestion accept archives originals", consolidation_accept)


async def run_webhook_tests(
    rec: ResultRecorder,
    client: httpx.AsyncClient,
    org: TestOrg,
    run_id: str,
    *,
    capture: WebhookCapture | None,
    manual_url: str | None,
    interactive: bool,
) -> None:
    async def hmac_shape() -> str:
        secret = "master-test-secret"
        body = json.dumps({"event": "qa.test", "data": {"ok": True}}, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
        header = f"t={timestamp},v1={signature}"
        assert _verify_signal_signature(body, header, secret), "signature did not verify"
        return "Stripe-style t=...,v1=... signature verifies"

    await rec.step("webhooks", "webhook HMAC signature verifier", hmac_shape)

    if capture is None and not manual_url:
        rec.skip("webhooks", "actual webhook event delivery", "use localhost API or pass --webhook-url")
        return

    secret = "master-webhook-secret"
    webhook_url = capture.url if capture is not None else str(manual_url)

    async def configure_and_trigger() -> str:
        async with AsyncSessionLocal() as session:
            db_org = await session.get(Organization, org.id)
            assert db_org is not None
            db_org.webhook_url = webhook_url
            db_org.webhook_secret = secret
            await session.commit()

        escalation_id = await create_escalation_api(
            client,
            org.api_key,
            context=f"[MASTER QA {run_id}] webhook escalation",
            question="Trigger webhook events.",
            agent_id="master-webhook-agent",
            action="master_webhook",
            metadata={"qa_run_id": run_id, "qa_case": "webhook"},
        )
        await finalize_escalation_one_time(escalation_id, "approve")
        rule = await create_rule(org.id, run_id, case=f"webhook_trigger_{run_id}", action="proceed")
        await check_api(
            client,
            org.api_key,
            action="master_webhook_trigger",
            agent_id="master-webhook-agent",
            context={"qa_case": f"webhook_trigger_{run_id}"},
        )
        await check_api(
            client,
            org.api_key,
            action="master_webhook_trigger",
            agent_id="master-webhook-agent",
            context={"qa_case": f"webhook_trigger_{run_id}"},
        )
        return f"triggered escalation.created, escalation.resolved, rule.triggered via rule {rule.id}"

    await rec.step("webhooks", "configure webhook and trigger events", configure_and_trigger)

    if capture is not None:
        async def verify_capture() -> str:
            created = await capture.wait_for("escalation.created")
            resolved = await capture.wait_for("escalation.resolved")
            triggered = await capture.wait_for("rule.triggered")
            assert created and resolved and triggered, f"events={[event['json'].get('event') for event in capture.events]}"
            for event in (created, resolved, triggered):
                assert _verify_signal_signature(event["body"], event["signature"], secret), event["signature"]
            triggered_count = sum(event["json"].get("event") == "rule.triggered" for event in capture.events)
            assert triggered_count == 1, f"rule.triggered throttle failed, count={triggered_count}"
            return "captured events arrived with valid signatures and rule.triggered throttle"

        await rec.step("webhooks", "actual webhook delivery and throttle", verify_capture)
    elif interactive:
        if sys.stdin.isatty():
            answer = input(
                "Open your webhook receiver and confirm the Signal events arrived with X-Signal-Signature. "
                "Type yes/no: "
            )
            if answer.strip().lower().startswith("y"):
                rec.pass_("webhooks", "manual webhook receiver confirmation", webhook_url)
            else:
                rec.fail("webhooks", "manual webhook receiver confirmation", "user reported no event")
        else:
            rec.check(
                "webhooks",
                "manual webhook receiver confirmation",
                f"events sent to {webhook_url}; confirm in the receiver UI",
            )
    else:
        rec.check("webhooks", "manual webhook receiver confirmation", webhook_url)


async def run_dashboard_tests(
    rec: ResultRecorder,
    client: httpx.AsyncClient,
    org: TestOrg,
    run_id: str,
    *,
    email: str | None,
    password: str | None,
    created_org_ids: list[UUID],
    with_stripe_checkout: bool,
) -> None:
    if not email or not password:
        rec.skip("dashboard", "authenticated dashboard flow", "set SIGNAL_DASHBOARD_EMAIL and SIGNAL_DASHBOARD_PASSWORD")
        return

    async def login_and_select() -> str:
        await dashboard_login(client, email=email, password=password)
        select_response = await client.post(
            "/dashboard/org-session",
            json={"api_key": org.api_key},
            headers={"Content-Type": "application/json"},
        )
        select_response.raise_for_status()
        selected = select_response.json()["organization"]
        assert selected["id"] == str(org.id), selected
        return f"logged in as {email} and selected {org.name}"

    await rec.step("dashboard", "Supabase email/password session and org selection", login_and_select)

    async def pages_render() -> str:
        account_paths = ("/dashboard", "/dashboard/account")
        for path in account_paths:
            response = await client.get(path)
            assert response.status_code == 200, f"{path} status={response.status_code}"
            assert "Organizations" in response.text or "Account Settings" in response.text, f"{path} missing account dashboard"
            assert "Signal" in response.text, f"{path} missing Signal"

        org_paths = ("/dashboard/overview", "/dashboard/review", "/dashboard/rules", "/dashboard/escalations", "/dashboard/settings")
        for path in org_paths:
            response = await client.get(path)
            assert response.status_code == 200, f"{path} status={response.status_code}"
            assert org.name in response.text, f"{path} missing org signal"
            assert "Signal" in response.text, f"{path} missing Signal"
        return "account, organizations, overview, review, rules, escalations, and organization settings render"

    await rec.step("dashboard", "authenticated dashboard pages render", pages_render)

    async def admin_json_endpoints() -> str:
        for path in ("/admin/summary", "/admin/review", "/admin/settings", "/admin/rules", "/admin/escalations", "/admin/check-logs"):
            response = await client.get(path)
            response.raise_for_status()
            assert isinstance(response.json(), dict), path
        return "admin JSON endpoints respond for selected org"

    await rec.step("dashboard", "dashboard admin JSON APIs", admin_json_endpoints)

    async def settings_and_keys() -> str:
        patch = await client.patch(
            "/admin/settings",
            json={"slack_notifications_enabled": False, "slack_channel_id": ""},
            headers={"Content-Type": "application/json"},
        )
        patch.raise_for_status()
        settings_payload = patch.json()
        assert settings_payload["organization"]["slack_notifications_enabled"] is False, settings_payload
        keys = await client.get("/admin/api-keys")
        keys.raise_for_status()
        items = keys.json()["items"]
        assert items, "temporary org key was not listed"
        assert org.api_key not in json.dumps(items), "full API key leaked in list endpoint"
        generate = await client.post(
            "/admin/api-keys/generate",
            json={"name": f"Master QA {run_id}"},
            headers={"Content-Type": "application/json"},
        )
        generate.raise_for_status()
        generated = generate.json()
        assert generated["api_key"].startswith("sk_live_"), generated
        keys_after = await client.get("/admin/api-keys")
        keys_after.raise_for_status()
        assert generated["api_key"] not in json.dumps(keys_after.json()), "full generated key leaked after listing"
        return "settings save, key list, and key generation work without leaking full keys"

    await rec.step("dashboard", "settings API and API key management", settings_and_keys)

    async def setup_account_org_key_flow() -> str:
        setup = await client.post(
            "/admin/setup",
            json={"organization_name": f"[MASTER QA {run_id}] Dashboard-created org"},
            headers={"Content-Type": "application/json"},
        )
        setup.raise_for_status()
        new_org_id = UUID(setup.json()["organization"]["id"])
        created_org_ids.append(new_org_id)
        generated = await client.post(
            "/admin/api-keys/generate",
            json={"name": "New org key"},
            headers={"Content-Type": "application/json"},
        )
        generated.raise_for_status()
        assert generated.json()["api_key"].startswith("sk_live_"), generated.text
        select_back = await client.post(
            "/dashboard/org-session",
            json={"org_id": str(org.id)},
            headers={"Content-Type": "application/json"},
        )
        select_back.raise_for_status()
        return "account-level organization creation and selected-org API key creation work"

    await rec.step("dashboard", "account-level organization setup and API-key limits", setup_account_org_key_flow)

    if with_stripe_checkout:
        async def checkout_url() -> str:
            response = await client.post(
                "/admin/billing/checkout",
                json={"tier": "pro"},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            url = response.json().get("url", "")
            assert url.startswith("https://"), url
            return "subscription page URL returned"

        await rec.step("billing", "Stripe subscription page creation", checkout_url)
    else:
        rec.skip("billing", "Stripe subscription page creation", "pass --with-stripe-checkout")

    async def logout() -> str:
        response = await client.post("/dashboard/logout")
        response.raise_for_status()
        blocked = await client.get("/admin/settings")
        assert blocked.status_code == 401, f"status={blocked.status_code}"
        return "logout clears dashboard session cookies"

    await rec.step("dashboard", "dashboard logout", logout)


async def run_billing_webhook_tests(
    rec: ResultRecorder,
    client: httpx.AsyncClient,
    org: TestOrg,
    *,
    enabled: bool,
) -> None:
    if not enabled:
        rec.skip("billing", "Stripe webhook billing status update", "pass --with-stripe-webhook")
        return
    if not settings.stripe_webhook_secret:
        rec.skip("billing", "Stripe webhook billing status update", "STRIPE_WEBHOOK_SECRET is not configured locally")
        return

    async def webhook() -> str:
        body = json.dumps(
            {
                "id": f"evt_master_{uuid4().hex}",
                "object": "event",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": f"cs_master_{uuid4().hex}",
                        "object": "checkout.session",
                        "client_reference_id": str(org.account_id),
                        "customer": "cus_master_qa",
                        "subscription": "sub_master_qa",
                        "metadata": {"account_id": str(org.account_id), "plan_tier": "pro"},
                    }
                },
            },
            separators=(",", ":"),
        ).encode()
        response = await client.post(
            "/stripe/webhook",
            content=body,
            headers={"Stripe-Signature": _stripe_signature(body, settings.stripe_webhook_secret)},
        )
        response.raise_for_status()
        async with AsyncSessionLocal() as session:
            db_account = await session.get(Account, org.account_id)
            assert db_account is not None
            assert db_account.billing_status == "active", db_account.billing_status
            assert db_account.plan_tier == "pro", db_account.plan_tier
            assert db_account.stripe_customer_id == "cus_master_qa", db_account.stripe_customer_id
        return "signed checkout.session.completed updated account billing"

    await rec.step("billing", "Stripe webhook billing status update", webhook)


async def run_sdk_tests(
    rec: ResultRecorder,
    client: httpx.AsyncClient,
    org: TestOrg,
    run_id: str,
    *,
    with_typescript: bool,
) -> None:
    async def python_signalops_check() -> str:
        signalops.configure(api_key=org.api_key, base_url=str(client.base_url))
        check = await signalops.check(
            action="master_python_sdk",
            agent_id="master-python-sdk-agent",
            context={"qa_case": f"python_sdk_no_rule_{run_id}"},
        )
        assert check.result == "proceed", check.__dict__
        assert hasattr(signalops, "escalate"), "signalops.escalate is missing"
        assert hasattr(signalops, "check"), "signalops.check is missing"
        return "signalops.check and signalops.escalate public API are exported"

    await rec.step("sdk", "Python signalops package-level API", python_signalops_check)

    async def ts_build() -> str:
        if not (ROOT / "sdk-ts" / "node_modules").exists():
            raise AssertionError("sdk-ts/node_modules is missing; run npm install or use --with-typescript after installing")
        result = subprocess.run(
            ["npm", "--prefix", str(ROOT / "sdk-ts"), "run", "build"],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr[-1000:] or result.stdout[-1000:]
        assert (ROOT / "sdk-ts" / "dist" / "client.d.ts").exists(), "dist/client.d.ts missing"
        return "TypeScript SDK builds and exports declarations"

    await rec.step(
        "sdk",
        "TypeScript SDK build",
        ts_build,
        skip_detail=None if with_typescript else "pass --with-typescript",
    )


async def run_rate_limit_test(
    rec: ResultRecorder,
    client: httpx.AsyncClient,
    org: TestOrg,
    run_id: str,
    *,
    enabled: bool,
    attempts: int,
) -> None:
    if not enabled:
        rec.skip("rate limits", "1000/minute check limit", "pass --include-rate-limit")
        return

    async def rate_limit() -> str:
        rate_case = f"rate_{run_id}"
        rule = await create_rule(org.id, run_id, case=rate_case, action="proceed")
        concurrency = 8
        semaphore = asyncio.Semaphore(concurrency)
        saw_retry_after: str | None = None
        completed = 0

        async def send_one(index: int) -> httpx.Response | Exception:
            async with semaphore:
                try:
                    return await client.post(
                        "/v1/check",
                        headers=_auth_headers(org.api_key, json_content=True),
                        json={
                            "action": "master_rate_limit",
                            "agent_id": "master-rate-limit-agent",
                            "context": {"qa_case": rate_case, "i": index},
                        },
                    )
                except Exception as exc:
                    return exc

        tasks = [asyncio.create_task(send_one(index)) for index in range(attempts)]
        try:
            for task in asyncio.as_completed(tasks):
                result = await task
                completed += 1
                if isinstance(result, Exception):
                    continue
                if result.status_code == 429:
                    saw_retry_after = result.headers.get("Retry-After")
                    break
                if result.status_code >= 500:
                    raise AssertionError(f"unexpected server status={result.status_code}")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        assert saw_retry_after is not None, f"no 429 after {completed} completed requests out of {attempts}"
        refreshed = await get_rule(rule.id)
        return (
            f"429 observed after {completed} completed requests with Retry-After={saw_retry_after}; "
            f"rate-test trigger_count={refreshed.trigger_count}"
        )

    await rec.step("rate limits", "1000/minute check limit", rate_limit)


async def run_manual_review_checkpoint(
    rec: ResultRecorder,
    org: TestOrg,
    run_id: str,
    *,
    base_url: str,
    enabled: bool,
    interactive: bool,
    timeout: int,
) -> None:
    if not enabled:
        rec.skip("manual review", "Slack/dashboard end-to-end human review", "pass --with-manual-review")
        return

    async def manual_review() -> str:
        async with AsyncSessionLocal() as session:
            db_org = await session.get(Organization, org.id)
            assert db_org is not None
            db_org.slack_notifications_enabled = True
            await session.commit()
        signalops.configure(api_key=org.api_key, base_url=base_url)
        tag = f"[MASTER QA {run_id}] manual review"
        print("\nManual checkpoint:")
        print(f"  Temporary org: {org.name}")
        print(f"  Temporary API key, if you need to select it in dashboard settings: {org.api_key}")
        print(f"  Look for this context: {tag}")
        print("  Finish the full review flow: approve/reject, then one-time or rule approval/discard.")
        if not interactive:
            return "manual review launched only in --interactive mode"
        result = await signalops.escalate(
            context=f"{tag}: The agent needs a final human decision.",
            question="Should this master QA manual action proceed?",
            agent_id="master-manual-agent",
            action="master_manual_review",
            metadata={"qa_run_id": run_id, "qa_case": "manual_review"},
            timeout_seconds=timeout,
        )
        assert result.decision in {"approve", "reject"}, result.__dict__
        return f"decision={result.decision}, rule_id={result.rule_id}"

    if interactive:
        await rec.step("manual review", "Slack/dashboard end-to-end human review", manual_review)
    else:
        detail = await manual_review()
        rec.check("manual review", "Slack/dashboard end-to-end human review", detail)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the master Signal product test suite against a live API and its backing database."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("SIGNAL_TEST_BASE_URL", DEFAULT_BASE_URL),
        help="Signal API base URL. Defaults to SIGNAL_TEST_BASE_URL or production.",
    )
    parser.add_argument("--run-id", default=None, help="Optional fixed run id.")
    parser.add_argument("--keep-data", action="store_true", help="Keep temporary QA orgs and data.")
    parser.add_argument("--strict-skips", action="store_true", help="Exit non-zero if any feature is skipped.")
    parser.add_argument("--with-ai", action="store_true", help="Run live Voyage/AI-dependent checks.")
    parser.add_argument("--with-typescript", action="store_true", help="Run the TypeScript SDK build check.")
    parser.add_argument("--with-stripe-checkout", action="store_true", help="Create a real Stripe checkout session.")
    parser.add_argument("--with-stripe-webhook", action="store_true", help="Send a signed Stripe webhook test event.")
    parser.add_argument("--include-rate-limit", action="store_true", help="Run the noisy 1000/minute rate-limit test.")
    parser.add_argument("--rate-limit-attempts", type=int, default=1005, help="Attempts for the rate-limit test.")
    parser.add_argument("--with-manual-review", action="store_true", help="Pause for a real Slack/dashboard review.")
    parser.add_argument("--interactive", action="store_true", help="Allow prompts for manual checkpoints.")
    parser.add_argument("--manual-timeout", type=int, default=1800, help="Seconds to wait for manual review.")
    parser.add_argument("--webhook-url", default=os.getenv("SIGNAL_TEST_WEBHOOK_URL"), help="External webhook receiver URL.")
    parser.add_argument(
        "--dashboard-email",
        default=os.getenv("SIGNAL_DASHBOARD_EMAIL"),
        help="Dashboard test user's email.",
    )
    parser.add_argument(
        "--dashboard-password",
        default=os.getenv("SIGNAL_DASHBOARD_PASSWORD"),
        help="Dashboard test user's password.",
    )
    return parser


async def run(args: argparse.Namespace) -> ResultRecorder:
    args.base_url = args.base_url.rstrip("/")
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:6]
    rec = ResultRecorder()
    created_org_ids: list[UUID] = []
    capture: WebhookCapture | None = None

    print("\n" + "=" * 78)
    print("Signal Master QA")
    print("=" * 78)
    print(f"Run ID:   {run_id}")
    print(f"Base URL: {args.base_url}")
    print("Mode:     automatic core suite" + (" + manual checkpoints" if args.interactive else ""))

    timeout = httpx.Timeout(30.0, read=None)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout, follow_redirects=False) as client:
        primary = await create_test_org(run_id, "Primary org")
        isolated = await create_test_org(run_id, "Isolation org")
        created_org_ids.extend([primary.id, isolated.id])
        print(f"\nTemporary org: {primary.name} ({primary.id})")

        if _is_local_url(args.base_url) and not args.webhook_url:
            capture = WebhookCapture("master-webhook-secret")
            capture.start()

        try:
            await run_environment_tests(rec, client, args)
            await run_auth_and_org_tests(rec, client, primary, isolated, run_id)
            await run_policy_engine_tests(rec, client, primary, run_id)
            await run_conflict_tests(rec, client, primary, run_id)
            await run_vector_and_semantic_tests(rec, client, primary, run_id, with_ai=args.with_ai)
            await run_escalation_and_sse_tests(
                rec,
                client,
                primary,
                run_id,
                redis_drivable=_can_drive_sse_from_test_runner(args.base_url),
            )
            await run_override_and_lifecycle_tests(rec, client, primary, run_id)
            await run_webhook_tests(
                rec,
                client,
                primary,
                run_id,
                capture=capture,
                manual_url=args.webhook_url,
                interactive=args.interactive,
            )
            await run_dashboard_tests(
                rec,
                client,
                primary,
                run_id,
                email=args.dashboard_email,
                password=args.dashboard_password,
                created_org_ids=created_org_ids,
                with_stripe_checkout=args.with_stripe_checkout,
            )
            await run_billing_webhook_tests(rec, client, primary, enabled=args.with_stripe_webhook)
            await run_sdk_tests(rec, client, primary, run_id, with_typescript=args.with_typescript)
            await run_rate_limit_test(
                rec,
                client,
                primary,
                run_id,
                enabled=args.include_rate_limit,
                attempts=args.rate_limit_attempts,
            )
            await run_manual_review_checkpoint(
                rec,
                primary,
                run_id,
                base_url=args.base_url,
                enabled=args.with_manual_review,
                interactive=args.interactive,
                timeout=args.manual_timeout,
            )
        finally:
            if capture is not None:
                capture.stop()
            if args.keep_data:
                print("\nKeeping temporary QA data because --keep-data was set.")
                print("Temporary org ids:")
                for org_id in created_org_ids:
                    print(f"  {org_id}")
            else:
                await cleanup_orgs(created_org_ids)
                print("\nCleaned up temporary QA organizations and data.")

    return rec


def main() -> None:
    args = build_parser().parse_args()
    recorder = asyncio.run(run(args))
    passed, failed, skipped, checks = recorder.summary()
    print("\n" + "=" * 78)
    print("Master QA Summary")
    print("=" * 78)
    print(f"PASS:  {passed}")
    print(f"FAIL:  {failed}")
    print(f"SKIP:  {skipped}")
    print(f"CHECK: {checks}")

    if failed:
        raise SystemExit(1)
    if args.strict_skips and skipped:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
