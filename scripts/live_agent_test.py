from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SDK_PATH = ROOT / "sdk"
if SDK_PATH.exists():
    sys.path.insert(0, str(SDK_PATH))

import signalops  # noqa: E402


BASE_URL = "https://signal-omega-tan.vercel.app"
ACTION = "approve_vendor_wire_payment"
AGENT_ID = "finance-ops-live-agent"


def build_context(run_id: str, invoice_number: str, amount: int, vendor: str) -> dict:
    return {
        "test_run_id": run_id,
        "invoice_number": invoice_number,
        "vendor": vendor,
        "vendor_status": "new_vendor",
        "payment_method": "wire_transfer",
        "amount_usd": amount,
        "department": "growth",
        "budget_owner": "Maya Chen",
        "invoice_age_days": 2,
        "risk_flags": [
            "new vendor",
            "wire transfer",
            "amount above agent comfort threshold",
        ],
        "agent_recommendation": "wait_for_human_review",
    }


def context_text(context: dict) -> str:
    return (
        "A finance operations agent is reviewing a vendor payment.\n\n"
        f"Vendor: {context['vendor']}\n"
        f"Invoice: {context['invoice_number']}\n"
        f"Amount: ${context['amount_usd']:,}\n"
        f"Payment method: {context['payment_method']}\n"
        f"Vendor status: {context['vendor_status']}\n"
        f"Department: {context['department']}\n"
        f"Budget owner: {context['budget_owner']}\n"
        f"Risk flags: {', '.join(context['risk_flags'])}\n\n"
        "The agent is unsure whether to approve the payment automatically."
    )


def print_check(label: str, check) -> None:
    print(f"\n{label}")
    print(f"  Result: {check.result}")
    print(f"  Rule ID: {check.rule_id or 'None'}")
    print(f"  Reasoning: {check.reasoning}")
    if check.modification:
        print(f"  Modification: {check.modification}")


async def run(args: argparse.Namespace) -> None:
    api_key = args.api_key or os.getenv("SIGNALOPS_API_KEY") or os.getenv("SIGNAL_TEST_API_KEY")
    if not api_key:
        raise SystemExit("Set SIGNALOPS_API_KEY, or pass --api-key.")

    base_url = (args.base_url or os.getenv("SIGNALOPS_BASE_URL") or BASE_URL).rstrip("/")
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]

    signalops.configure(api_key=api_key, base_url=base_url)

    first_context = build_context(
        run_id=run_id,
        invoice_number=f"SIG-LIVE-{run_id}",
        amount=args.amount,
        vendor=args.vendor,
    )

    print("\n" + "=" * 72)
    print("Signal live agent test")
    print("=" * 72)
    print(f"Base URL: {base_url}")
    print(f"Agent:    {AGENT_ID}")
    print(f"Action:   {ACTION}")
    print(f"Run ID:   {run_id}")
    print("\nScenario:")
    print(context_text(first_context))

    check = await signalops.check(
        action=ACTION,
        agent_id=AGENT_ID,
        context=first_context,
    )
    print_check("Initial policy check", check)

    if check.rule_id and not args.force_escalation:
        print("\nA rule already matched, so the agent did not need to escalate.")
        print("Use --force-escalation if you want to send a fresh live review card anyway.")
    else:
        if check.rule_id:
            print("\nA rule matched, but --force-escalation was set, so the agent is sending a fresh review anyway.")
        else:
            print("\nNo usable rule matched, so the agent is escalating and will wait here.")
        print("Open Slack or the dashboard Review tab and finish the full decision flow:")
        print("  1. Approve or reject the payment.")
        print("  2. If asked whether to make it reusable, choose either one-time or make it a rule.")
        print("  3. If a rule is proposed, approve, edit, or discard it.")
        print("\nWaiting for Signal to return a finalized decision...\n")

        result = await signalops.escalate(
            context=context_text(first_context),
            question="Should the finance agent approve this vendor wire payment?",
            agent_id=AGENT_ID,
            action=ACTION,
            metadata=first_context,
            timeout_seconds=args.timeout_seconds,
        )

        print("Final decision returned to the agent")
        print(f"  Decision:      {result.decision}")
        print(f"  Rule ID:       {result.rule_id or 'None'}")
        print(f"  Auto-resolved: {result.auto_resolved}")

        if result.decision in {"approve", "proceed", "yes"}:
            print("\nAgent action: payment would be approved.")
        elif result.decision in {"reject", "block", "no"}:
            print("\nAgent action: payment would be rejected.")
        else:
            print("\nAgent action: decision returned; inspect the dashboard for exact handling.")

    if args.skip_followup_check:
        return

    followup_context = build_context(
        run_id=run_id,
        invoice_number=f"SIG-LIVE-FOLLOWUP-{run_id}",
        amount=args.amount + 350,
        vendor=args.vendor,
    )
    followup_context["invoice_age_days"] = 3
    followup_context["risk_flags"] = [
        "new vendor",
        "wire transfer",
        "amount above agent comfort threshold",
    ]

    print("\n" + "-" * 72)
    print("Follow-up check with a similar payment")
    print("-" * 72)

    followup = await signalops.check(
        action=ACTION,
        agent_id=AGENT_ID,
        context=followup_context,
    )
    print_check("Follow-up policy check", followup)

    if followup.rule_id:
        print("\nSuccess: a saved rule matched the similar follow-up situation.")
    else:
        print("\nNo rule matched the follow-up. That is expected if you chose one-time or discarded the rule.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a live Signal agent test against the hosted API.")
    parser.add_argument("--api-key", help="Signal API key. Prefer SIGNALOPS_API_KEY instead of passing this.")
    parser.add_argument("--base-url", default=None, help=f"Signal API base URL. Defaults to {BASE_URL}.")
    parser.add_argument("--timeout-seconds", type=int, default=1800, help="How long escalate() waits.")
    parser.add_argument("--run-id", default=None, help="Optional fixed run id for repeatable testing.")
    parser.add_argument("--vendor", default="Northstar Analytics", help="Vendor name for the test scenario.")
    parser.add_argument("--amount", type=int, default=18450, help="Payment amount in USD.")
    parser.add_argument(
        "--force-escalation",
        action="store_true",
        help="Send an escalation even if the initial policy check already matches a rule.",
    )
    parser.add_argument(
        "--skip-followup-check",
        action="store_true",
        help="Skip the second check that verifies whether a rule was created.",
    )
    return parser.parse_args()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
