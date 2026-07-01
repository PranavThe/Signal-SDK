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
    wait_for,
    wait_for_response_stream,
)
from api.database import AsyncSessionLocal
from api.models import Escalation
from api.services.semantic_service import find_similar_escalations


async def main() -> None:
    parser = argparse.ArgumentParser(description="Manual similar past decisions Slack card test.")
    add_common_args(parser)
    args = parser.parse_args()
    api_key = require_api_key(args.api_key)
    run_id = str(uuid.uuid4())[:8]

    first_id = await create_escalation(
        args.base_url,
        api_key,
        context=f"[QA similar {run_id}] Gold customer requests refund for order 42 days old, value 189.",
        question="Manual test part 1: click Approve.",
        agent_id="qa-agent",
        action="qa_similar_refund",
        metadata={"qa_run_id": run_id, "customer_tier": "gold", "order_age_days": 42, "order_value": 189},
    )
    print(f"Created first escalation: {first_id}")
    print_step("In Slack, click Approve on the first QA similar card.")
    event = await wait_for_response_stream(args.base_url, api_key, first_id, timeout=args.timeout)
    if event.get("human_decision") != "approve":
        raise SystemExit(f"Expected approve for first escalation, got {event}")

    async def first_embedded() -> bool:
        async with AsyncSessionLocal() as session:
            escalation = await session.get(Escalation, uuid.UUID(first_id))
            return bool(escalation and escalation.context_embedding is not None)

    await wait_for("first escalation embedding", first_embedded, timeout=args.timeout)
    print_success("First escalation responded and embedded.")

    second_id = await create_escalation(
        args.base_url,
        api_key,
        context=f"[QA similar {run_id}] Gold tier customer wants a refund on a 43 day old order worth 189.",
        question="Manual test part 2: inspect this Slack card for 'Similar past decisions'.",
        agent_id="qa-agent",
        action="qa_similar_refund",
        metadata={"qa_run_id": run_id, "customer_tier": "gold", "order_age_days": 43, "order_value": 189},
    )
    print(f"Created second escalation: {second_id}")

    async def second_similar():
        async with AsyncSessionLocal() as session:
            escalation = await session.get(Escalation, uuid.UUID(second_id))
            if not escalation or escalation.context_embedding is None:
                return None
            return await find_similar_escalations(
                session,
                escalation.context_embedding,
                str(escalation.id),
                str(escalation.org_id) if escalation.org_id else None,
            )

    similar = await wait_for("similar decisions backend result", second_similar, timeout=args.timeout)
    print_success(f"Backend found {len(similar)} similar past decision(s).")
    print_step("In Slack, confirm the second QA similar card shows a 'Similar past decisions' section.")


if __name__ == "__main__":
    asyncio.run(main())
