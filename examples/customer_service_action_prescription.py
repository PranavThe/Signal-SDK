"""
Example: Customer Service Agent with Action Prescription

This example demonstrates how to build an agent that:
1. Proposes actions when uncertain
2. Receives prescribed actions from Signal
3. Safely validates and executes actions
4. Handles unknown actions gracefully

Key Concepts:
- Action Prescription: Signal tells the agent WHAT to do, not just yes/no
- Safe Execution: Agent validates actions against a whitelist before executing
- Graceful Degradation: Unknown actions trigger re-escalation for guidance
"""

import asyncio
import logging
from signalops import Signal, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# 1. Define Your Agent's Capabilities
# ============================================================================

def check_account_for_fraud(customer_id: str, transaction_id: str) -> dict:
    """Check account for fraudulent activity."""
    logger.info(f"🔍 Checking account {customer_id} for fraud (transaction: {transaction_id})")
    # Simulate fraud check
    return {"fraud_detected": False, "confidence": 0.92}


def escalate_to_fraud_team(customer_id: str, transaction_id: str) -> dict:
    """Escalate case to specialized fraud team."""
    logger.info(f"🚨 Escalating to fraud team: customer {customer_id}, transaction {transaction_id}")
    # Simulate escalation
    return {"ticket_id": "FRD-12345", "assigned_to": "fraud_specialist"}


def refund_immediately(customer_id: str, amount: float) -> dict:
    """Process immediate refund."""
    logger.info(f"💰 Processing immediate refund of ${amount} for customer {customer_id}")
    # Simulate refund
    return {"refund_id": "REF-67890", "status": "processed"}


def send_verification_email(customer_id: str, email: str) -> dict:
    """Send verification email to customer."""
    logger.info(f"📧 Sending verification email to {email} (customer: {customer_id})")
    # Simulate email
    return {"email_sent": True, "sent_to": email}


def place_security_hold(customer_id: str, duration_hours: int = 24) -> dict:
    """Place temporary security hold on account."""
    logger.info(f"🔒 Placing {duration_hours}h security hold on account {customer_id}")
    # Simulate security hold
    return {"hold_id": "HOLD-99999", "expires_at": "2026-07-09T12:00:00Z"}


# Action registry: Maps action names to functions
# This is your agent's "skill set" - only these actions can be executed
ALLOWED_ACTIONS = {
    "check_account_for_fraud": check_account_for_fraud,
    "escalate_to_fraud_team": escalate_to_fraud_team,
    "refund_immediately": refund_immediately,
    "send_verification_email": send_verification_email,
    "place_security_hold": place_security_hold,
}


# ============================================================================
# 2. Agent Logic with Action Prescription
# ============================================================================

class CustomerServiceAgent:
    def __init__(self, api_key: str):
        # Initialize Signal with schema for consistent context
        self.signal = Signal(
            api_key=api_key,
            schema=[
                Field("customer.id", type="string"),
                Field("transaction.id", type="string"),
                Field("transaction.amount", type="number"),
                Field("transaction.type", type="string"),
                Field("customer.tier", type="string"),
                Field("reported.as", type="string"),
                Field("account.age.days", type="integer"),
            ]
        )

    async def handle_fraud_report(self, customer_id: str, transaction_id: str,
                                   amount: float, transaction_type: str,
                                   customer_tier: str = "standard"):
        """
        Handle a customer fraud report.

        The agent doesn't know what to do - it asks Signal and executes
        the prescribed action.
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"🎯 New Fraud Report: Customer {customer_id}, ${amount} {transaction_type}")
        logger.info(f"{'='*70}\n")

        # Build context for Signal
        context = {
            "customer.id": customer_id,
            "transaction.id": transaction_id,
            "transaction.amount": amount,
            "transaction.type": transaction_type,
            "customer.tier": customer_tier,
            "reported.as": "unauthorized",
        }

        # Ask Signal what to do
        # The agent proposes its best guess, but Signal may prescribe something different
        result = await self.signal.escalate(
            agent_id="customer-service",
            question="How should I handle this fraud report?",
            action="check_account_for_fraud",  # Agent's default action
            context=context,
        )

        logger.info(f"\n📋 Signal Response:")
        logger.info(f"   Decision: {result.decision}")
        logger.info(f"   Prescribed Action: {result.action}")
        logger.info(f"   Auto-resolved: {result.auto_resolved}")
        logger.info(f"   Rule ID: {result.rule_id}\n")

        # Execute the prescribed action safely
        await self.execute_action(result.action, context)

    async def execute_action(self, action_name: str, context: dict):
        """
        Safely execute a prescribed action.

        Key safety features:
        1. Validates action against whitelist (ALLOWED_ACTIONS)
        2. Handles unknown actions by re-escalating
        3. Logs all executions for audit trail
        """
        if not action_name:
            logger.warning("⚠️  No action prescribed by Signal")
            return

        # Validate action before executing
        action_fn = ALLOWED_ACTIONS.get(action_name)

        if action_fn:
            logger.info(f"✅ Executing allowed action: {action_name}")

            # Extract parameters from context
            customer_id = context.get("customer.id")
            transaction_id = context.get("transaction.id")
            amount = context.get("transaction.amount")

            # Execute the action
            try:
                if action_name == "refund_immediately":
                    result = action_fn(customer_id, amount)
                elif action_name in ["check_account_for_fraud", "escalate_to_fraud_team"]:
                    result = action_fn(customer_id, transaction_id)
                elif action_name == "send_verification_email":
                    result = action_fn(customer_id, context.get("customer.email", "unknown"))
                elif action_name == "place_security_hold":
                    result = action_fn(customer_id)
                else:
                    result = action_fn(customer_id, transaction_id)

                logger.info(f"✨ Action completed: {result}")

            except Exception as e:
                logger.error(f"❌ Action execution failed: {e}")
                # Re-escalate the error to Signal
                await self.signal.escalate(
                    agent_id="customer-service",
                    question=f"Action {action_name} failed with error: {e}. What should I do?",
                    context=context,
                )
        else:
            # Unknown action - agent doesn't know how to execute this
            logger.error(f"❌ Unknown action prescribed: {action_name}")
            logger.info(f"   Allowed actions: {list(ALLOWED_ACTIONS.keys())}")
            logger.info(f"   Re-escalating to Signal for guidance...")

            # Re-escalate to Signal asking for help
            await self.signal.escalate(
                agent_id="customer-service",
                question=f"I don't know how to '{action_name}'. What should I do instead?",
                context={
                    **context,
                    "error.type": "unknown_action",
                    "error.action_requested": action_name,
                },
            )


# ============================================================================
# 3. Demo: See Action Prescription in Action
# ============================================================================

async def demo():
    """
    Demonstrate action prescription with various scenarios.

    Try these scenarios to see how Signal learns:
    1. First fraud report - no rule exists, waits for human
    2. Second fraud report - similar context, uses learned rule
    3. High-value fraud - different action prescribed based on amount
    """
    import os

    api_key = os.getenv("SIGNAL_API_KEY", "sk_live_your_key_here")
    agent = CustomerServiceAgent(api_key)

    # Scenario 1: Standard fraud report
    print("\n" + "="*70)
    print("SCENARIO 1: Standard unauthorized charge")
    print("="*70)
    await agent.handle_fraud_report(
        customer_id="cust_12345",
        transaction_id="txn_98765",
        amount=84.99,
        transaction_type="card_charge",
        customer_tier="standard"
    )

    # Scenario 2: High-value fraud report
    print("\n" + "="*70)
    print("SCENARIO 2: High-value unauthorized charge")
    print("="*70)
    await agent.handle_fraud_report(
        customer_id="cust_67890",
        transaction_id="txn_11111",
        amount=1499.99,
        transaction_type="card_charge",
        customer_tier="premium"
    )

    # Scenario 3: Multiple small charges (pattern fraud)
    print("\n" + "="*70)
    print("SCENARIO 3: Premium customer with pattern fraud")
    print("="*70)
    await agent.handle_fraud_report(
        customer_id="cust_premium_001",
        transaction_id="txn_22222",
        amount=9.99,
        transaction_type="recurring_subscription",
        customer_tier="premium"
    )


if __name__ == "__main__":
    print("""
    ╔════════════════════════════════════════════════════════════════════╗
    ║                                                                    ║
    ║          Customer Service Agent - Action Prescription Demo        ║
    ║                                                                    ║
    ║  This demo shows how Signal prescribes ACTIONS, not just yes/no   ║
    ║                                                                    ║
    ╚════════════════════════════════════════════════════════════════════╝

    How to use:
    1. Set SIGNAL_API_KEY environment variable
    2. Run this script
    3. Watch as the agent asks "what should I do?"
    4. Signal responds with a prescribed action
    5. Agent validates and executes the action safely

    What you'll see:
    - First run: No rule exists, waits for human decision
    - Subsequent runs: Rules learned, actions prescribed automatically
    - Safety: Unknown actions trigger re-escalation instead of crashing

    """)

    asyncio.run(demo())
