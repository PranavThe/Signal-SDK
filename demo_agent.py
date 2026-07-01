import asyncio
from signal_sdk import Signal

signal = Signal(
    api_key="YOUR_SIGNAL_API_KEY",
    base_url="https://YOUR_SIGNAL_BASE_URL"
)

CUSTOMER_REQUESTS = [
    {
        "customer_name": "Sarah Chen",
        "request_type": "refund",
        "order_id": "ORD-1001",
        "order_age_days": 47,
        "order_value": 189.00,
        "customer_tier": "gold",
        "customer_ltv": 4900,
        "reason": "Item arrived broken"
    },
    {
        "customer_name": "Marcus Webb",
        "request_type": "refund",
        "order_id": "ORD-1002",
        "order_age_days": 38,
        "order_value": 95.00,
        "customer_tier": "gold",
        "customer_ltv": 2800,
        "reason": "Wrong item delivered"
    },
    {
        "customer_name": "Priya Patel",
        "request_type": "refund",
        "order_id": "ORD-1003",
        "order_age_days": 15,
        "order_value": 45.00,
        "customer_tier": "basic",
        "customer_ltv": 120,
        "reason": "Changed mind"
    },
    {
        "customer_name": "James Torres",
        "request_type": "account_upgrade",
        "order_id": None,
        "order_age_days": None,
        "order_value": None,
        "customer_tier": "basic",
        "customer_ltv": 89,
        "reason": "Wants free upgrade to gold tier"
    }
]


async def process_request(request: dict) -> str:
    print(f"\n{'='*60}")
    print(f"Processing request from {request['customer_name']}")
    print(f"Request: {request['request_type']}")
    print(f"Reason: {request['reason']}")
    print(f"{'='*60}")

    context = {k: v for k, v in request.items() if v is not None}

    print(f"\n→ Checking rules for action: {request['request_type']}...")
    check = await signal.check(
        action=request["request_type"],
        agent_id="support-agent-v1",
        context=context
    )

    print(f"→ Check result: {check.result}")
    print(f"→ Reasoning: {check.reasoning}")

    if check.rule_id is not None:
        if check.result == "proceed":
            print(f"✅ AUTO-APPROVED — matched existing rule")
            return f"Approved {request['request_type']} for {request['customer_name']}"

        elif check.result == "block":
            print(f"❌ AUTO-REJECTED — matched existing rule")
            return f"Rejected {request['request_type']} for {request['customer_name']}"

        elif check.result == "modify":
            print(f"→ Rule says to modify action: {check.modification}")
            return f"Modified {request['request_type']} for {request['customer_name']}: {check.modification}"

    # No rule matched — escalate to human
    print(f"\n→ No rule found for this situation.")
    print(f"→ Escalating to Slack now.")
    print(f"→ Go to Slack and click Approve or Reject on the card.\n")

    result = await signal.escalate(
        context=(
            f"Customer {request['customer_name']} ({request['customer_tier']} tier, "
            f"LTV ${request.get('customer_ltv', 'N/A')}) is requesting a "
            f"{request['request_type']}. "
            f"Reason: {request['reason']}. "
            f"Order {request.get('order_id', 'N/A')} is "
            f"{request.get('order_age_days', 'N/A')} days old, "
            f"value ${request.get('order_value', 'N/A')}."
        ),
        question=f"Should I approve or reject this {request['request_type']} request?",
        agent_id="support-agent-v1",
        metadata=context,
        timeout_seconds=600
    )

    print(f"→ Human decision received: {result.decision}")
    print(f"\n⏸️  Now complete the rule flow in Slack:")
    print(f"   1. Click 'Yes, make it a rule'")
    print(f"   2. Review the proposed rule")
    print(f"   3. Click 'Approve rule'")
    print(f"\n   Press ENTER here when you are completely done in Slack...")
    await asyncio.get_event_loop().run_in_executor(None, input)

    if result.rule_id:
        print(f"→ Rule created: {result.rule_id}")
        print(f"→ Future similar requests will be handled automatically")
    else:
        print(f"→ No rule created — one-off decision")

    return f"{result.decision.upper()} — {request['request_type']} for {request['customer_name']}"


async def main():
    print("\n🤖 Signal Demo Agent Starting")
    print("This agent processes customer support requests.")
    print("Each escalation pauses and waits for you to finish the full Slack flow.")
    print("Watch for AUTO-APPROVED on Request 2 — that's the magic moment.")
    print("\nProcessing", len(CUSTOMER_REQUESTS), "customer requests...\n")

    results = []
    for i, request in enumerate(CUSTOMER_REQUESTS, 1):
        print(f"\n[{i}/{len(CUSTOMER_REQUESTS)}] Starting next request...")
        result = await process_request(request)
        results.append(result)

        if i < len(CUSTOMER_REQUESTS):
            print(f"\n→ Moving to next request in 2 seconds...")
            await asyncio.sleep(2)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for i, result in enumerate(results, 1):
        print(f"{i}. {result}")
    print(f"\nDone. Check your dashboard at https://YOUR_SIGNAL_BASE_URL/dashboard")


if __name__ == "__main__":
    asyncio.run(main())