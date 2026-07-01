from __future__ import annotations

import argparse
import asyncio
import uuid

from common import (
    add_common_args,
    create_escalation,
    print_step,
    print_success,
    require_api_key,
    wait_for_response_stream,
    wait_for_rule_change,
    wait_for_rule_for_escalation,
    wait_for_rule_status,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Manual Slack rule proposal edit flow test.")
    add_common_args(parser)
    parser.add_argument(
        "--edit-instruction",
        default="Only apply this rule when order value is under $250.",
        help="Text to submit in the Slack edit modal.",
    )
    args = parser.parse_args()
    api_key = require_api_key(args.api_key)
    run_id = str(uuid.uuid4())[:8]

    escalation_id = await create_escalation(
        args.base_url,
        api_key,
        context=(
            f"[QA rule edit {run_id}] Gold customer asks for a refund. "
            "Order age is 42 days and order value is 189 dollars."
        ),
        question="Manual test: click Approve, then make this decision a rule.",
        agent_id="qa-agent",
        action="qa_refund_edit_flow",
        metadata={"qa_run_id": run_id, "customer_tier": "gold", "order_age_days": 42, "order_value": 189},
    )
    print(f"Created escalation: {escalation_id}")

    print_step("In Slack, click Approve.")
    event = await wait_for_response_stream(args.base_url, api_key, escalation_id, timeout=args.timeout)
    if event.get("human_decision") != "approve":
        raise SystemExit(f"Expected approve, got {event}")
    print_success("Escalation approved.")

    print_step("In Slack, click 'Yes, make it a rule'. Waiting for the proposed rule...")
    rule = await wait_for_rule_for_escalation(escalation_id, timeout=args.timeout)
    original_condition = rule.condition_description
    print_success(f"Rule proposal created: {rule.id}")
    print(f"Current condition: {rule.condition_description}")
    print(f"Current action: {rule.action_description}")

    print_step("In Slack, click 'Edit rule'. In the modal, submit this exact edit:")
    print(args.edit_instruction)
    revised = await wait_for_rule_change(rule.id, original_condition, timeout=args.timeout)
    print_success("Revised rule proposal detected.")
    print(f"Revised condition: {revised.condition_description}")
    print(f"Revised action: {revised.action_description}")

    print_step("In Slack, click 'Approve rule'.")
    active = await wait_for_rule_status(rule.id, "active", timeout=args.timeout)
    print_success(f"Rule approved and active: {active.id}")


if __name__ == "__main__":
    asyncio.run(main())
