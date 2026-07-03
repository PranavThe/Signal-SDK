from __future__ import annotations

import argparse
import asyncio
import secrets
import string
import uuid

import httpx
from common import (
    add_common_args,
    create_escalation,
    headers,
    lookup_org_id,
    print_step,
    print_success,
    require_api_key,
    restore_webhook,
    set_webhook,
    wait_for_response_stream,
)
from sqlalchemy import delete

from api.auth import hash_api_key
from api.database import AsyncSessionLocal
from api.models import Account, ApiKey, ConsolidationSuggestion, Organization, PolicyCheckLog, Rule


async def main() -> None:
    parser = argparse.ArgumentParser(description="Manual webhook.site event delivery test.")
    add_common_args(parser)
    parser.add_argument("--url", required=True, help="webhook.site URL")
    parser.add_argument("--secret", required=True, help="Webhook signing secret to set temporarily")
    parser.add_argument("--keep-webhook", action="store_true", help="Do not restore the previous webhook settings")
    args = parser.parse_args()
    api_key = require_api_key(args.api_key)
    org_id = await lookup_org_id(api_key)
    old_url, old_secret = await set_webhook(org_id, args.url, args.secret)
    run_id = str(uuid.uuid4())[:8]
    print(f"Configured webhook for org {org_id}. Run id: {run_id}")

    try:
        escalation_id = await create_escalation(
            args.base_url,
            api_key,
            context=f"[QA webhook {run_id}] Customer asks for manual approval.",
            question="Manual webhook test: click Approve to trigger escalation.resolved.",
            agent_id="qa-agent",
            action="qa_webhook_escalation",
            metadata={"qa_run_id": run_id},
        )
        print_success(f"Triggered escalation.created for escalation {escalation_id}")
        print_step("In webhook.site, confirm an escalation.created request arrived.")

        print_step("In Slack, click Approve on the QA webhook card.")
        event = await wait_for_response_stream(args.base_url, api_key, escalation_id, timeout=args.timeout)
        if event.get("human_decision") != "approve":
            raise SystemExit(f"Expected approve, got {event}")
        print_success("Triggered escalation.resolved.")
        print_step("In webhook.site, confirm escalation.resolved arrived.")

        await trigger_rule_created_and_triggered(args.base_url, api_key, org_id, run_id)
        print_step("In webhook.site, confirm rule.created and rule.triggered arrived.")
        print_step("For rule.triggered, run the same script again or inspect timestamps to confirm max one per rule per minute.")
    finally:
        if args.keep_webhook:
            print("Leaving webhook settings in place.")
        else:
            await restore_webhook(org_id, old_url, old_secret)
            print("Restored previous webhook settings.")


async def trigger_rule_created_and_triggered(base_url: str, api_key: str, org_id, run_id: str) -> None:
    raw_key = "sk_live_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
    async with AsyncSessionLocal() as session:
        qa_account = Account(name=f"QA webhook transient {run_id} account", plan_tier="free", billing_status="active")
        session.add(qa_account)
        await session.flush()
        qa_org = Organization(
            name=f"QA webhook transient {run_id}",
            account_id=qa_account.id,
            webhook_url=None,
            webhook_secret=None,
        )
        session.add(qa_org)
        await session.flush()
        session.add(ApiKey(org_id=qa_org.id, key_hash=hash_api_key(raw_key), key_prefix=raw_key[:8], name="QA"))
        rule_a = Rule(
            org_id=qa_org.id,
            condition_description=f"[QA webhook {run_id}] tier is webhook_gold A",
            action_description="Proceed for webhook test",
            exceptions_note="",
            structured_conditions=[{"field": "tier", "operator": "eq", "value": "webhook_gold"}],
            structured_action={"action": "proceed", "parameters": {"qa": True}},
            agent_scope=[],
            extraction_confidence=0.9,
            status="active",
        )
        rule_b = Rule(
            org_id=qa_org.id,
            condition_description=f"[QA webhook {run_id}] tier is webhook_gold B",
            action_description="Proceed for webhook test",
            exceptions_note="",
            structured_conditions=[{"field": "tier", "operator": "eq", "value": "webhook_gold"}],
            structured_action={"action": "proceed", "parameters": {"qa": True}},
            agent_scope=[],
            extraction_confidence=0.9,
            status="active",
        )
        session.add_all([rule_a, rule_b])
        await session.flush()
        suggestion = ConsolidationSuggestion(
            org_id=qa_org.id,
            rule_a_id=rule_a.id,
            rule_b_id=rule_b.id,
            merged_condition=f"[QA webhook {run_id}] tier is webhook_gold",
            merged_action="Proceed for webhook test",
            reason="QA webhook rule.created test.",
            status="pending",
        )
        session.add(suggestion)
        await session.commit()
        qa_account_id = qa_account.id
        qa_org_id = qa_org.id
        suggestion_id = suggestion.id

    try:
        async with AsyncSessionLocal() as session:
            qa_org = await session.get(Organization, qa_org_id)
            qa_org.webhook_url = (await session.get(Organization, org_id)).webhook_url
            qa_org.webhook_secret = (await session.get(Organization, org_id)).webhook_secret
            await session.commit()

        async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=60.0) as client:
            accept = await client.post(
                f"/v1/consolidation/{suggestion_id}/accept",
                headers=headers(raw_key),
            )
            accept.raise_for_status()
            merged_rule_id = accept.json()["merged_rule_id"]
            print_success(f"Triggered rule.created through consolidation accept: {merged_rule_id}")

            check = await client.post(
                "/v1/check",
                headers=headers(raw_key, json_content=True),
                json={"action": "qa_webhook_check", "agent_id": "qa-agent", "context": {"tier": "webhook_gold"}},
            )
            check.raise_for_status()
            print_success("Triggered rule.triggered through matching check.")
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(ConsolidationSuggestion).where(ConsolidationSuggestion.org_id == qa_org_id))
            await session.execute(delete(PolicyCheckLog).where(PolicyCheckLog.org_id == qa_org_id))
            await session.execute(delete(Rule).where(Rule.org_id == qa_org_id))
            await session.execute(delete(ApiKey).where(ApiKey.org_id == qa_org_id))
            await session.execute(delete(Organization).where(Organization.id == qa_org_id))
            await session.execute(delete(Account).where(Account.id == qa_account_id))
            await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
