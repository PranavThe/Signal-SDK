from __future__ import annotations

import argparse
import asyncio
import uuid

from common import (
    add_common_args,
    create_escalation,
    find_conflicts_for_rule,
    print_step,
    print_success,
    require_api_key,
    wait_for,
    wait_for_response_stream,
    wait_for_rule_for_escalation,
    wait_for_rule_status,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Manual semantic conflict detection test.")
    add_common_args(parser)
    args = parser.parse_args()
    api_key = require_api_key(args.api_key)
    run_id = str(uuid.uuid4())[:8]

    first_id = await create_escalation(
        args.base_url,
        api_key,
        context=f"[QA conflict {run_id}] Gold customer requests refund for order 20 days old, value 120.",
        question="Manual test part 1: click Approve, then make and approve the rule.",
        agent_id="qa-agent",
        action="qa_conflict_refund",
        metadata={"qa_run_id": run_id, "customer_tier": "gold", "order_age_days": 20, "order_value": 120},
    )
    print(f"Created first escalation: {first_id}")
    print_step("In Slack, click Approve.")
    event = await wait_for_response_stream(args.base_url, api_key, first_id, timeout=args.timeout)
    if event.get("human_decision") != "approve":
        raise SystemExit(f"Expected approve, got {event}")
    print_step("Click 'Yes, make it a rule', then click 'Approve rule'.")
    first_rule = await wait_for_rule_for_escalation(first_id, timeout=args.timeout)
    first_rule = await wait_for_rule_status(first_rule.id, "active", timeout=args.timeout)
    print_success(f"First active rule created: {first_rule.id}")

    second_id = await create_escalation(
        args.base_url,
        api_key,
        context=f"[QA conflict {run_id}] Gold customer requests refund for order 20 days old, value 120.",
        question="Manual test part 2: click Reject, then make it a rule.",
        agent_id="qa-agent",
        action="qa_conflict_refund",
        metadata={"qa_run_id": run_id, "customer_tier": "gold", "order_age_days": 20, "order_value": 120},
    )
    print(f"Created second escalation: {second_id}")
    print_step("In Slack, click Reject.")
    event = await wait_for_response_stream(args.base_url, api_key, second_id, timeout=args.timeout)
    if event.get("human_decision") != "reject":
        raise SystemExit(f"Expected reject, got {event}")
    print_step("Click 'Yes, make it a rule'. Watch the proposal for a conflict warning.")
    second_rule = await wait_for_rule_for_escalation(second_id, timeout=args.timeout)

    async def conflict_rows():
        rows = await find_conflicts_for_rule(second_rule.id)
        return rows or None

    conflicts = await wait_for("rule conflict row", conflict_rows, timeout=args.timeout)
    print_success(f"Detected {len(conflicts)} conflict row(s) for second rule: {second_rule.id}")
    print_step("In Slack, confirm the proposal includes 'Potential conflict with existing rule'.")


if __name__ == "__main__":
    asyncio.run(main())
