from __future__ import annotations

import argparse
import asyncio
import uuid

from common import add_common_args, create_escalation, print_step, print_success, require_api_key, wait_for_response_stream


async def main() -> None:
    parser = argparse.ArgumentParser(description="Manual Slack approve/reject flow test.")
    add_common_args(parser)
    parser.add_argument("--expect", choices=["approve", "reject"], default="approve")
    args = parser.parse_args()
    api_key = require_api_key(args.api_key)
    run_id = str(uuid.uuid4())[:8]

    escalation_id = await create_escalation(
        args.base_url,
        api_key,
        context=f"[QA approve flow {run_id}] Customer asks whether this test action should proceed.",
        question=f"Manual test: click {args.expect.title()} for this escalation.",
        agent_id="qa-agent",
        action="qa_manual_approve_flow",
        metadata={"qa_run_id": run_id, "expected_decision": args.expect},
    )
    print(f"Created escalation: {escalation_id}")
    print_step(f"In Slack, click {args.expect.title()} on the new [QA approve flow {run_id}] card.")

    event = await wait_for_response_stream(args.base_url, api_key, escalation_id, timeout=args.timeout)
    actual = event.get("human_decision")
    if actual != args.expect:
        raise SystemExit(f"Expected decision {args.expect}, got {actual}. Event: {event}")
    print_success(f"Slack decision resolved through SSE with decision={actual}")


if __name__ == "__main__":
    asyncio.run(main())
