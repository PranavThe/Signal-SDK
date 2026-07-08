import React, { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { Check, X, Download } from "lucide-react";
import { motion, useInView } from "motion/react";

function Reveal({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });
  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 24 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay }}
    >
      {children}
    </motion.div>
  );
}

const DASHBOARD_URL = "https://signal-omega-tan.vercel.app/dashboard";
const SIGNALOPS_VERSION = "0.2.1";

function useIsNarrow(breakpoint: number) {
  const [isNarrow, setIsNarrow] = useState(false);

  useEffect(() => {
    const update = () => setIsNarrow(window.innerWidth < breakpoint);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [breakpoint]);

  return isNarrow;
}

// Helper components for cleaner rendering
const CodeBlock = ({ language, code }: { language: string; code: string }) => (
  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)" }}>
    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>{language}</div>
    <pre style={{ padding: "1.25rem", fontSize: "0.875rem", lineHeight: 1.6, fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>{code}</pre>
  </div>
);

const SectionDivider = () => <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />;

// Function to generate markdown from the docs
function generateMarkdown(): string {
  return `# Signal Documentation

Version ${SIGNALOPS_VERSION}
Generated on ${new Date().toLocaleDateString()}

## Quickstart (5 Minutes)

### Step 1: Install Signal

\`\`\`bash
pip install signalops
\`\`\`

### Step 2: Get Your API Key

1. Go to ${DASHBOARD_URL}
2. Sign up and create an account
3. Create an organization (or open an existing one)
4. Go to Organization Settings
5. Click "Add new key", name it, and copy it
6. Save this key securely - it starts with \`sk_live_\`

### Step 3: Write Your First Agent with Signal

Here's a complete working example of a customer support agent that escalates refund decisions:

\`\`\`python
import asyncio
import signalops

# Configure Signal with your API key
signalops.configure(
    api_key="sk_live_your_api_key_here",
    # base_url is optional - defaults to https://signal-omega-tan.vercel.app
)

async def handle_refund_request(customer_id: str, order_amount: float, reason: str, days_since_purchase: int):
    """
    Handle a customer refund request.
    Signal will either auto-approve based on existing rules, or escalate to a human.
    """

    # Ask Signal whether to approve the refund
    result = await signalops.escalate(
        agent_id="customer-support-refunds",
        question="Should I issue a refund for this order?",
        context={
            "customer_id": customer_id,
            "order_amount": order_amount,
            "reason": reason,
            "days_since_purchase": days_since_purchase,
            "customer_tier": "premium"
        }
    )

    # The result object contains the decision
    print(f"Decision: {result.decision}")
    print(f"Auto-resolved: {result.auto_resolved}")

    if result.auto_resolved:
        print(f"Resolved by rule: {result.rule_id}")
    else:
        print("Human made this decision")

    # Act on the decision
    if result.decision in ["approve", "yes"]:
        print(f"✓ Refund approved for customer {customer_id}")
        # Your code to issue refund goes here
        return True
    else:
        print(f"✗ Refund denied for customer {customer_id}")
        # Your code to deny refund goes here
        return False

# Example usage
async def main():
    approved = await handle_refund_request(
        customer_id="cust_123",
        order_amount=150.00,
        reason="Product arrived damaged",
        days_since_purchase=3
    )
    print(f"Final result: {'Refunded' if approved else 'Not refunded'}")

if __name__ == "__main__":
    asyncio.run(main())
\`\`\`

### Step 4: Run Your Agent

\`\`\`bash
python your_agent.py
\`\`\`

**What happens:**
1. Your agent calls \`escalate()\`
2. Signal checks if any existing rules match this decision
3. If a rule matches → Returns decision immediately (auto-resolved)
4. If no rule matches → Shows in dashboard for human review
5. Human approves/rejects and optionally creates a rule
6. Your agent receives the decision and acts on it

### Step 5: Review Decisions in Dashboard

Go to ${DASHBOARD_URL} and click the **Review** tab to see pending escalations.

**Workflow:**
1. **Decision:** Click Approve or Reject
2. **Scope:** Choose "Create a rule" or "One-time decision"
3. **Review:** If creating a rule, review the AI-generated rule and approve, edit, or discard

Once approved, similar future decisions will be auto-resolved by the rule.

---

## Core Concepts

### What is Signal?

Signal is a human-in-the-loop decision framework for AI agents. Instead of hard-coding rules or letting your agent make risky decisions alone, Signal lets you:

1. **Escalate uncertain decisions to humans**
2. **Learn from those decisions** by creating reusable rules
3. **Progressively automate** as your agent builds up a rulebook

### How It Works

\`\`\`
Agent needs decision
        ↓
   escalate() call
        ↓
   Check existing rules
        ↓
   ┌─────────┴─────────┐
   ↓                   ↓
Rule found       No rule found
(auto-resolve)   (escalate to human)
   ↓                   ↓
Return decision   Show in dashboard
                       ↓
                  Human decides
                       ↓
                  Create rule?
                       ↓
              Rule added to system
\`\`\`

### Key Terms

- **Escalation:** A decision your agent asks Signal to make
- **Rule:** A policy that auto-resolves future similar escalations
- **Agent ID:** Identifier for your agent (e.g., "customer-support-refunds")
- **Action:** Type of decision being made (e.g., "refund_request")
- **Context:** Information about the decision (formatted as field:value pairs)
- **Auto-resolved:** Decision was made by a rule without human input
- **Autonomy Score:** Percentage of decisions handled automatically by rules

---

## Installation

### Requirements

- Python 3.8 or higher
- An async-compatible environment (Signal uses \`async/await\`)

### Install via pip

\`\`\`bash
pip install signalops
\`\`\`

### Verify Installation

\`\`\`python
import signalops
print(signalops.__version__)  # Should print 0.2.1 or newer
\`\`\`

---

## Complete Examples

### Example 1: Content Moderation Agent

\`\`\`python
import asyncio
import signalops

signalops.configure(api_key="sk_live_your_api_key_here")

async def moderate_post(post_id: str, content: str, user_reputation: float):
    """
    Moderate user-generated content.
    Auto-approve trusted users, escalate suspicious content.
    """

    result = await signalops.escalate(
        agent_id="content-moderator",
        question="Should I approve this post?",
        action="moderate_post",
        context=f"""Post ID: {post_id}
Content: {content[:200]}...
User Reputation Score: {user_reputation}
Content Length: {len(content)} characters
Contains URLs: {'yes' if 'http' in content else 'no'}""",
        metadata={
            "post_id": post_id,
            "user_reputation": user_reputation,
            "content_length": len(content)
        },
        timeout_seconds=300  # Wait up to 5 minutes for human decision
    )

    if result.decision == "approve":
        return "approved"
    else:
        return "rejected"

asyncio.run(moderate_post("post_789", "Check out this cool article...", 0.85))
\`\`\`

### Example 2: Transaction Approval Agent

\`\`\`python
import asyncio
import signalops

signalops.configure(api_key="sk_live_your_api_key_here")

async def approve_transaction(
    transaction_id: str,
    amount: float,
    user_id: str,
    risk_score: float,
    is_international: bool
):
    """
    Approve or reject financial transactions based on risk.
    """

    result = await signalops.escalate(
        agent_id="transaction-approvals",
        question="Should I approve this transaction?",
        action="approve_transaction",
        context=f"""Transaction ID: {transaction_id}
Amount: $\{amount:.2f}
User ID: {user_id}
Risk Score: {risk_score}
International: {'yes' if is_international else 'no'}
Account Age: 6 months
Previous Transactions: 42""",
        metadata={
            "transaction_id": transaction_id,
            "amount": amount,
            "risk_score": risk_score
        }
    )

    if result.decision == "approve":
        print(f"✓ Transaction {transaction_id} approved")
        if result.auto_resolved:
            print(f"  Auto-approved by rule {result.rule_id}")
        # Process transaction
        return True
    else:
        print(f"✗ Transaction {transaction_id} denied")
        # Reject transaction
        return False

asyncio.run(approve_transaction("txn_456", 5000.00, "user_123", 0.3, False))
\`\`\`

### Example 3: Using check() for Rule-Only Decisions

Sometimes you don't want to escalate - you only want to check existing rules:

\`\`\`python
import asyncio
import signalops

signalops.configure(api_key="sk_live_your_api_key_here")

async def quick_check_refund(customer_tier: str, amount: float):
    """
    Check if we should refund without escalating.
    Returns None if no rule matches.
    """

    result = await signalops.check(
        action="refund_request",
        context={
            "customer_tier": customer_tier,
            "amount": amount
        },
        agent_id="customer-support-refunds"
    )

    if result.allowed:
        print(f"Refund allowed by rule {result.rule_id}")
        return True
    elif result.allowed is False:
        print(f"Refund denied by rule {result.rule_id}")
        return False
    else:
        print("No rule found - need to escalate")
        return None

asyncio.run(quick_check_refund("premium", 150.00))
\`\`\`

---

## API Reference

### signalops.configure()

Configure Signal globally. Call this once at the start of your application.

**Parameters:**
- \`api_key\` (str, required): Your Signal API key starting with \`sk_live_\`
- \`base_url\` (str, optional): Signal API URL. Default: \`https://signal-omega-tan.vercel.app\`
- \`dev_mode\` (bool, optional): Enable debug logging for development (default: False)
- \`auto_enrich\` (bool, optional): Automatically add timestamp and environment to context (default: True)

**Example:**
\`\`\`python
import signalops

signalops.configure(
    api_key="sk_live_your_api_key_here",
    base_url="https://signal-omega-tan.vercel.app",  # Optional
    dev_mode=False,  # Optional: Enable debug logging
    auto_enrich=True  # Optional: Auto-add environment metadata (default: True)
)
\`\`\`

---

### signalops.escalate()

Escalate a decision to Signal. This will either return a decision from an existing rule, or wait for human review.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| \`agent_id\` | str | Yes | Unique identifier for your agent (e.g., "customer-support-refunds") |
| \`question\` | str | Yes | Clear yes/no question (e.g., "Should I issue a refund?") |
| \`context\` | str | Yes | Decision context as field:value pairs on separate lines |
| \`action\` | str | No | Action identifier for grouping similar decisions (e.g., "refund_request") |
| \`metadata\` | dict | No | Additional structured data (not shown to humans, used for filtering) |
| \`timeout_seconds\` | int | No | How long to wait for a decision (default: 3600 seconds = 1 hour) |

**Returns:** \`EscalationResult\` object with:
- \`decision\` (str): The decision made (e.g., "approve", "reject", "yes", "no")
- \`rule_id\` (str | None): ID of the rule that made this decision (if auto-resolved)
- \`auto_resolved\` (bool): Whether this was resolved by a rule (True) or human (False)

**Example:**
\`\`\`python
result = await signalops.escalate(
    agent_id="customer-support-refunds",
    question="Should I issue a refund?",
    context={
        "customer_id": "cust_123",
        "order_amount": 150,
        "reason": "Product arrived damaged",
        "days_since_purchase": 3,
        "customer_tier": "premium"
    },
    action="refund_request",
    metadata={"customer_id": "cust_123", "order_amount": 150},
    timeout_seconds=600  # Wait up to 10 minutes
)

print(result.decision)       # "approve" or "reject"
print(result.auto_resolved)  # True if rule matched, False if human decided
print(result.rule_id)        # Rule ID if auto-resolved, None otherwise
\`\`\`

**Important Notes:**
- Your function must be \`async\` to use \`await escalate()\`
- Prefer passing \`context\` as a dict. Signal normalizes fields like \`author\`, \`author_name\`, and \`author.name\` before matching rules.
- Signal will block until a decision is made or timeout is reached

---

### signalops.check()

Check if an action should be allowed based on existing rules **without escalating**. This does not create an escalation or wait for human review.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| \`action\` | str | Yes | Action identifier (e.g., "refund_request") |
| \`context\` | dict | Yes | Context as a dictionary of key-value pairs |
| \`agent_id\` | str | Yes | Your agent identifier |

**Returns:** \`CheckResult\` object with:
- \`allowed\` (bool | None): \`True\` if approved, \`False\` if denied, \`None\` if no rule found
- \`rule_id\` (str | None): ID of the rule that matched

**Example:**
\`\`\`python
result = await signalops.check(
    action="refund_request",
    context={
        "customer_tier": "premium",
        "order_amount": 150,
        "days_since_purchase": 3
    },
    agent_id="customer-support-refunds"
)

if result.allowed is True:
    print(f"Approved by rule {result.rule_id}")
elif result.allowed is False:
    print(f"Denied by rule {result.rule_id}")
else:
    print("No rule found - would need to escalate")
\`\`\`

**When to use check():**
- You want to check rules without creating an escalation
- You'll handle the "no rule found" case yourself
- You want lower latency (no waiting for humans)

**When to use escalate():**
- You want to create an escalation if no rule exists
- You're okay with waiting for human review
- You want Signal to learn from this decision

---

## Common Patterns

### Pattern 1: Fallback to Default Action

If no rule exists and you can't wait, provide a safe default:

\`\`\`python
try:
    result = await signalops.escalate(
        agent_id="my-agent",
        question="Should I proceed?",
        context="...",
        timeout_seconds=30  # Only wait 30 seconds
    )
    proceed = result.decision == "approve"
except TimeoutError:
    # No decision in 30 seconds - use safe default
    proceed = False  # Default to denying risky actions
\`\`\`

### Pattern 2: Combine check() and escalate()

Check for a rule first, then escalate if needed:

\`\`\`python
# First try to check existing rules (fast)
check_result = await signalops.check(
    action="approve_transaction",
    context={"amount": 1000, "risk_score": 0.2},
    agent_id="transactions"
)

if check_result.allowed is not None:
    # Rule found - use it
    proceed = check_result.allowed
else:
    # No rule - escalate to human
    escalation_result = await signalops.escalate(
        agent_id="transactions",
        question="Should I approve this transaction?",
        context="Amount: $1000\\nRisk Score: 0.2",
        action="approve_transaction"
    )
    proceed = escalation_result.decision == "approve"
\`\`\`

### Pattern 3: Structured Context for Better Rules

Format context consistently for better rule matching:

\`\`\`python
def format_context(data: dict) -> str:
    """Format context in a consistent way"""
    return "\\n".join(f"{k}: {v}" for k, v in data.items())

context_data = {
    "Customer ID": "cust_123",
    "Order Amount": "$150",
    "Reason": "Product damaged",
    "Days Since Purchase": "3",
    "Customer Tier": "premium"
}

result = await signalops.escalate(
    agent_id="refunds",
    question="Should I issue a refund?",
    context=format_context(context_data),
    metadata=context_data  # Also pass as metadata
)
\`\`\`

### Pattern 4: Agent-Specific Rules

Use descriptive agent IDs to separate different decision types:

\`\`\`python
# Different agents for different decision types
refund_result = await signalops.escalate(
    agent_id="customer-support-refunds",  # Separate ruleset
    question="Should I issue a refund?",
    context="..."
)

account_result = await signalops.escalate(
    agent_id="customer-support-account-changes",  # Different ruleset
    question="Should I upgrade this account?",
    context="..."
)
\`\`\`

---

## Dashboard Guide

### Overview Tab

The Overview tab shows your agent's performance metrics:

**Metrics:**
- **Total Agent Decisions Today:** All decisions made by your agents in the last 24 hours
- **Handled Automatically:** Decisions resolved using existing rules (no human needed)
- **Escalations Today:** Decisions that required human review
- **Autonomy Score:** Percentage of decisions handled automatically (Automatic / Total × 100%)

**Other Components:**
- **Autonomy Trend Table:** Daily breakdown showing how autonomy changes over time
- **AI Suggestions:** Recommendations to consolidate similar rules
- **Active Rules:** List of approved rules with trigger counts
- **Recent Escalations:** Latest escalations with their status

**Goal:** As you approve more decisions and create rules, your autonomy score should increase from ~20-40% initially to 70-90% for well-trained agents.

---

### Review Tab

This is where you review escalations and create rules. The workflow has three stages:

#### Stage 1: Make a Decision

1. View the agent's question and context
2. See similar past decisions (if any)
3. Click **Approve** or **Reject**

The escalation is now responded to, and your agent receives the decision.

#### Stage 2: Choose Scope

After making a decision, choose:
- **Create a rule:** Future similar situations will be auto-resolved
- **One-time decision:** This decision applies only to this case

Choose "One-time" for edge cases or situations you don't want to automate.

#### Stage 3: Review the Rule

If you chose "Create a rule", Signal generates a rule using AI. You'll see:
- **Condition:** When this rule applies (extracted from context)
- **Action:** What decision to make (approve/reject)
- **Exceptions:** Edge cases where the rule shouldn't apply

**Options:**
- **Approve:** Activate the rule. Future matching decisions will be auto-resolved
- **Edit:** Provide feedback to refine the rule
- **Discard:** Delete the rule and keep this as a one-time decision

**Conflict Warnings:** If the new rule conflicts with an existing rule, you'll see a warning. Fix conflicts by editing or discarding one of the rules.

**Auto-refresh:** The review tab automatically refreshes every 5 seconds to show new escalations.

---

### Rules Tab

View and manage all your approved rules.

**Features:**
- **Status badges:** Active, Paused, or Pending
- **Confidence levels:** High, Medium, or Low (based on AI extraction confidence)
- **Trigger counts:** How many times each rule has been used
- **Search and filter:** Find rules by keyword or status
- **Bulk actions:** Pause/activate multiple rules at once

**Card Format:** Each rule shows:
- Condition description
- Action description
- Exceptions note
- Metadata (creation date, trigger count, confidence)

Click a rule to view full details.

---

### Escalations Tab

View the complete history of all escalations.

**Table Columns:**
- **Time:** When the escalation was created
- **Agent:** Which agent escalated (agent_id)
- **Context:** Summary of the decision context
- **Status:** pending, responded, or finalized
- **Decision:** approve, reject, or pending
- **Rule Created:** Yes/No - whether a rule was created from this escalation

**Actions:**
- Click any row to expand full details
- Search by agent ID, context, or decision
- Filter by status or date range

---

### Organization Settings

Manage API keys and review mode for the selected organization.

**API Keys:**
1. Click "Add new key"
2. Enter a name (e.g., "Production", "Staging")
3. Click "Create"
4. Copy the key immediately - Signal only shows it once
5. Store it securely (environment variable, secret manager)

**Review Mode:**
- **Dashboard-only:** All escalations appear in the dashboard
- **Slack + Dashboard:** Escalations also appear in Slack for faster review

To enable Slack:
1. Click "Enable Slack Integration"
2. Authorize Signal to access your Slack workspace
3. Choose a channel for escalations

---

### Account Settings

Manage your subscription tier.

**Plans:**
- **Free:** 1 organization, 2 API keys per org
- **Pro:** 3 organizations, 5 API keys per org
- **Enterprise:** Unlimited organizations and API keys

Upgrade or downgrade your plan here. Billing is monthly.

---

## Error Handling

### Common Errors

**Authentication Error:**
\`\`\`python
# Error: Invalid API key
# Fix: Check your API key in Organization Settings
signalops.configure(api_key="sk_live_correct_key_here")
\`\`\`

**Timeout Error:**
\`\`\`python
try:
    result = await signalops.escalate(
        agent_id="my-agent",
        question="Should I proceed?",
        context="...",
        timeout_seconds=60
    )
except TimeoutError:
    # No decision received in 60 seconds
    # Fallback to safe default
    result.decision = "reject"
\`\`\`

**Network Error:**
\`\`\`python
try:
    result = await signalops.escalate(...)
except Exception as e:
    print(f"Error escalating: {e}")
    # Fallback to safe default or retry
\`\`\`

**Organization Not Found:**
- Go to dashboard and ensure you've created an organization
- Make sure you're using an API key from the correct organization

---

## Troubleshooting

### "No organization selected" error

**Solution:**
1. Go to ${DASHBOARD_URL}
2. Click "Organizations" in the nav
3. Create an organization or open an existing one
4. Go to Organization Settings
5. Create an API key and use it in your code

---

### Agent escalations not appearing in dashboard

**Checklist:**
- ✓ API key is correct (starts with \`sk_live_\`)
- ✓ Base URL is \`https://signal-omega-tan.vercel.app\` (or your self-hosted URL)
- ✓ You're viewing the correct organization in the dashboard
- ✓ Your code is actually calling \`escalate()\` (add a \`print()\` to verify)
- ✓ No exceptions are being thrown (wrap in try/except to check)

---

### Rules not triggering (escalations not auto-resolved)

**Checklist:**
- ✓ Rule status is "Active" (check Rules tab)
- ✓ No conflict warnings (conflicts force escalation)
- ✓ Context matches the rule condition (check similarity)
- ✓ Action parameter matches the rule's action (if you specified \`action\`)

**Debug:** Look at the rule's condition description and compare it to your escalation's context. They need to be similar for the rule to match.

---

### Search not finding results

**Solution:**
1. Clear all filters first
2. Check for typos in search query
3. Search is case-insensitive but requires partial matches
4. Try searching for smaller fragments (e.g., "refund" instead of "refund request")

---

### High latency / slow responses

**Solutions:**
- Use \`check()\` instead of \`escalate()\` if you only need to check existing rules
- Reduce \`timeout_seconds\` if you can't wait long
- Enable Slack integration for faster human response times
- Pre-create rules for common decisions using the dashboard

---

## Best Practices

### 1. Write Clear Questions

Questions should be answerable with "approve"/"reject" or "yes"/"no":

✅ **Good:**
- "Should I issue a refund for this order?"
- "Should I approve this transaction?"
- "Should I publish this post?"

❌ **Bad:**
- "What should I do?" (too vague)
- "How should I handle this customer?" (open-ended)
- "Is this okay?" (unclear)

---

### 2. Use Structured Context

Pass context as a dictionary whenever possible:

✅ **Good:**
\`\`\`python
context = {
    "customer_id": "cust_123",
    "order_amount": 150,
    "reason": "Product damaged",
    "days_since_purchase": 3,
    "customer_tier": "premium"
}
\`\`\`

❌ **Bad:**
\`\`\`python
context = "Customer cust_123 wants a refund for $150 because product damaged, 3 days since purchase, premium tier"
\`\`\`

**Why:** Structured context is easier to read, gives Signal stable canonical fields, and prevents rule misses caused by names like \`author\` versus \`author.name\`.

---

### 3. Use Descriptive Agent IDs

Be specific about what each agent does:

✅ **Good:**
- \`customer-support-refunds\`
- \`content-moderator-posts\`
- \`transaction-fraud-detector\`
- \`hr-leave-approvals\`

❌ **Bad:**
- \`agent1\`
- \`bot\`
- \`my-agent\`

**Why:** Descriptive IDs make it easier to understand metrics and filter escalations in the dashboard.

---

### 4. Start with Low Autonomy

Don't expect 90% autonomy on day 1:
- **Initial:** 20-40% autonomy (most decisions escalate)
- **After 1 week:** 50-60% autonomy (common patterns have rules)
- **Well-trained:** 70-90% autonomy (only edge cases escalate)

**Goal:** Progressively increase autonomy while maintaining decision quality.

---

### 5. Review Escalations Regularly

Check the Review tab daily or enable Slack for real-time notifications. The faster you respond, the less your agent blocks.

---

### 6. Consolidate Similar Rules

Use the AI suggestions in the Overview tab to merge similar rules. This prevents rule bloat and conflicts.

---

### 7. Monitor Autonomy Trends

Track the Autonomy Trend Table in the Overview tab. If autonomy stops increasing, you might need to:
- Create more specific rules
- Handle more edge cases
- Consolidate conflicting rules

---

## Security

### API Key Management

**Best Practices:**
- ✓ Store API keys in environment variables, never in code
- ✓ Use different keys for development and production
- ✓ Rotate keys periodically (e.g., every 90 days)
- ✓ Revoke keys immediately if compromised
- ✓ Use a secret manager (AWS Secrets Manager, HashiCorp Vault) for production

**Example:**
\`\`\`python
import os
import signalops

# Load from environment variable
api_key = os.environ.get("SIGNAL_API_KEY")
if not api_key:
    raise ValueError("SIGNAL_API_KEY environment variable not set")

signalops.configure(api_key=api_key)
\`\`\`

**Environment File (.env):**
\`\`\`
SIGNAL_API_KEY=sk_live_your_api_key_here
\`\`\`

---

### Access Control

- ✓ Only share organization access with trusted team members
- ✓ Use separate organizations for different teams or projects
- ✓ Review escalation history regularly for unusual patterns
- ✓ Audit rules periodically to ensure they're still valid

---

### Data Privacy

- Signal stores escalation context and metadata for rule matching
- Don't include sensitive information (passwords, credit card numbers, SSNs) in context
- Use metadata for sensitive data if needed - it's not shown to humans but available for your filtering

---

## Support

### Documentation

Full docs: ${DASHBOARD_URL}

### Contact

Questions or issues? Email: support@signalops.com

### Status Page

Check API status: https://status.signalops.com

---

*Documentation version ${SIGNALOPS_VERSION} - Last updated ${new Date().toLocaleDateString()}*
`;
}

export default function Docs() {
  const [activeSection, setActiveSection] = useState("quickstart");
  const isNarrow = useIsNarrow(960);
  const isMobile = useIsNarrow(640);

  useEffect(() => {
    const handleScroll = () => {
      const sections = [
        "quickstart",
        "concepts",
        "installation",
        "examples",
        "api-reference",
        "patterns",
        "dashboard",
        "errors",
        "troubleshooting",
        "best-practices",
        "security"
      ];

      for (let i = 0; i < sections.length; i++) {
        const section = sections[i];
        const element = document.getElementById(section);
        if (element) {
          const rect = element.getBoundingClientRect();
          if (rect.top >= 0 && rect.top <= 200) {
            setActiveSection(section);
            break;
          }
        }
      }
    };

    window.addEventListener("scroll", handleScroll);
    return () => {
      window.removeEventListener("scroll", handleScroll);
    };
  }, []);

  const navItems = [
    { id: "quickstart", label: "Quickstart (5min)" },
    { id: "concepts", label: "Core Concepts" },
    { id: "installation", label: "Installation" },
    { id: "examples", label: "Complete Examples" },
    { id: "api-reference", label: "API Reference" },
    { id: "patterns", label: "Common Patterns" },
    { id: "dashboard", label: "Dashboard Guide" },
    { id: "errors", label: "Error Handling" },
    { id: "troubleshooting", label: "Troubleshooting" },
    { id: "best-practices", label: "Best Practices" },
    { id: "security", label: "Security" }
  ];

  const generateMarkdown = () => {
    return `# Signal Documentation v${SIGNALOPS_VERSION}

Signal is an operational intelligence system that helps AI agents make consistent decisions by learning from human judgment.

## Table of Contents

1. [Quickstart (5min)](#quickstart-5min)
2. [Core Concepts](#core-concepts)
3. [Installation](#installation)
4. [Complete Examples](#complete-examples)
5. [API Reference](#api-reference)
6. [Common Patterns](#common-patterns)
7. [Dashboard Guide](#dashboard-guide)
8. [Error Handling](#error-handling)
9. [Troubleshooting](#troubleshooting)
10. [Best Practices](#best-practices)
11. [Security](#security)

---

## Quickstart (5min)

### Step 1: Install Signal

\`\`\`bash
pip install signalops
\`\`\`

### Step 2: Get Your API Key

1. Go to ${DASHBOARD_URL}
2. Sign up and create an account
3. Create an organization (or open an existing one)
4. Go to Organization Settings
5. Click "Add new key", name it, and copy it
6. Save this key securely - it starts with \`sk_live_\`

### Step 3: Write Your First Agent

\`\`\`python
import asyncio
import signalops

# Configure Signal
signalops.configure(api_key="sk_live_your_api_key_here")

async def handle_refund_request(customer_id, amount, reason):
    # Ask Signal for a decision
    result = await signalops.escalate(
        agent_id="customer-support-refunds",
        question="Should I issue a refund?",
        context=f"""Customer ID: {customer_id}
Order Amount: $\${amount}
Reason: {reason}
Customer Tier: premium"""
    )

    # Act on the decision
    if result.decision == "approve":
        print(f"✓ Refund approved")
        return True
    else:
        print(f"✗ Refund denied")
        return False

# Run it
asyncio.run(handle_refund_request("cust_123", 150, "damaged"))
\`\`\`

---

## Core Concepts

### What is Signal?

Signal is an operational intelligence system that helps AI agents make consistent decisions by learning from human judgment. When your agent encounters a decision it's uncertain about, Signal handles the escalation, captures the human decision, and automatically creates rules so future similar situations are handled automatically.

### How It Works

1. **Agent Escalates:** Your agent calls signalops.escalate() with a question and context
2. **Signal Checks Rules:** If a matching rule exists, Signal returns the decision instantly
3. **Human Review (if needed):** If no rule matches, Signal sends the decision to Slack for human review
4. **Rule Creation:** After human approval, Signal creates a rule so future similar cases are auto-resolved
5. **Continuous Learning:** Your agents get smarter over time as more rules are created

### Key Features

- **Instant Decisions:** Rules are checked in milliseconds for auto-resolved cases
- **Slack Integration:** Human reviewers get notified in Slack with full context
- **Dashboard:** View all escalations, rules, and metrics in a web dashboard
- **Rule Management:** Edit, approve, or discard proposed rules before they go live
- **Analytics:** Track auto-resolution rates, response times, and decision trends

---

## Installation

### Python Package

Signal is available as a Python package. Install it using pip:

\`\`\`bash
pip install signalops
\`\`\`

Or add it to your requirements.txt:

\`\`\`
signalops>=0.2.1
\`\`\`

### Requirements

- Python 3.8 or higher
- asyncio support (Python 3.7+ includes this by default)
- Active internet connection for API calls
- A Signal account and API key

### Verify Installation

Check that Signal is installed correctly:

\`\`\`bash
python -c "import signalops; print(signalops.__version__)"
\`\`\`

---

## Complete Examples

### Content Moderation

\`\`\`python
async def moderate_user_content(post_id, content, user_history):
    result = await signalops.escalate(
        agent_id="content-moderation",
        question="Should this content be approved?",
        context=f"""Post ID: {post_id}
Content: {content}
User has {user_history["violations"]} prior violations
User tier: {user_history["tier"]}""",
        metadata={"post_id": post_id, "user_id": user_history["id"]}
    )

    if result.decision == "approve":
        publish_post(post_id)
    else:
        reject_post(post_id)

    return result.decision
\`\`\`

### Financial Approvals

\`\`\`python
async def approve_expense(expense_id, amount, category, employee_level):
    result = await signalops.escalate(
        agent_id="expense-approvals",
        question="Should this expense be approved?",
        context=f"""Expense ID: {expense_id}
Amount: $\${amount}
Category: {category}
Employee Level: {employee_level}""",
        action="approve_expense",
        timeout_seconds=1800  # 30 minutes
    )

    if result.auto_resolved:
        print(f"Auto-approved by rule {result.rule_id}")

    return result.decision == "approve"
\`\`\`

### Customer Support Routing

\`\`\`python
async def route_support_ticket(ticket_id, issue_type, customer_value):
    result = await signalops.escalate(
        agent_id="support-routing",
        question="Should this ticket be escalated to senior support?",
        context=f"""Ticket: {ticket_id}
Issue: {issue_type}
Customer LTV: $\${customer_value}
Priority: {"high" if customer_value > 10000 else "normal"}"""
    )

    if result.decision == "approve":
        assign_to_senior_team(ticket_id)
    else:
        assign_to_standard_team(ticket_id)

    return result
\`\`\`

---

## API Reference

### signalops.configure()

Configure Signal globally. Call this once at the start of your application.

\`\`\`python
signalops.configure(
    api_key="sk_live_your_api_key_here",
    base_url="https://signal-omega-tan.vercel.app",  # Optional
    dev_mode=False,  # Optional: Enable debug logging
    auto_enrich=True  # Optional: Auto-add environment metadata (default: True)
)
\`\`\`

**Parameters:**
- \`api_key\` (str, required): Your Signal API key
- \`base_url\` (str, optional): Custom API endpoint URL
- \`dev_mode\` (bool, optional): Enable debug logging for development (default: False)
- \`auto_enrich\` (bool, optional): Automatically add timestamp and environment to context (default: True)

### signalops.escalate()

Escalate a decision to Signal. Returns a decision from an existing rule, or waits for human review.

\`\`\`python
result = await signalops.escalate(
    agent_id="customer-support-refunds",
    question="Should I issue a refund?",
    context="Customer ID: cust_123\\nAmount: $150",
    action="refund_request",  # optional
    metadata={"customer_id": "cust_123"},  # optional
    timeout_seconds=600  # optional, default 3600
)
\`\`\`

**Parameters:**
- \`agent_id\` (str, required): Unique identifier for your agent
- \`question\` (str, required): The decision question
- \`context\` (str, required): Relevant context for the decision
- \`action\` (str, optional): Action being requested
- \`metadata\` (dict, optional): Additional structured data
- \`timeout_seconds\` (int, optional): Max wait time (default: 3600)

**Returns:**
- \`decision\` (str): The decision ("approve" or "reject")
- \`rule_id\` (str | None): ID of the matching rule (if auto-resolved)
- \`auto_resolved\` (bool): Whether decision was made by a rule

---

## Common Patterns

### Fallback on Timeout

Always have a safe fallback when decisions time out:

\`\`\`python
from signalops.exceptions import SignalTimeout

try:
    result = await signalops.escalate(
        agent_id="fraud-detection",
        question="Is this transaction fraudulent?",
        context=f"Amount: $\${amount}, Location: {location}",
        timeout_seconds=120
    )
    block_transaction = result.decision == "reject"
except SignalTimeout:
    # Default to blocking suspicious transactions
    block_transaction = amount > 10000 or is_high_risk_location(location)
\`\`\`

### Parallel Escalations

Make multiple independent decisions in parallel:

\`\`\`python
import asyncio

# Run multiple escalations concurrently
results = await asyncio.gather(
    signalops.escalate(
        agent_id="content-mod",
        question="Should this be approved?",
        context=f"Post: {post_text}"
    ),
    signalops.escalate(
        agent_id="user-verification",
        question="Should this user be verified?",
        context=f"User: {user_id}, History: {history}"
    ),
    return_exceptions=True
)

content_approved, user_verified = results
\`\`\`

### Conditional Escalation

Only escalate when needed based on confidence or thresholds:

\`\`\`python
async def handle_refund(amount, reason, customer_tier):
    # Auto-approve small refunds for premium customers
    if customer_tier == "premium" and amount < 50:
        return "approve"

    # Escalate everything else
    result = await signalops.escalate(
        agent_id="refunds",
        question="Should I approve this refund?",
        context=f"Amount: $\${amount}\\nReason: {reason}\\nTier: {customer_tier}"
    )

    return result.decision
\`\`\`

---

## Dashboard Guide

### Getting Started

1. Go to ${DASHBOARD_URL}
2. Sign in with your account
3. Select your organization from the dropdown
4. You'll see three main sections: Escalations, Rules, and Settings

### Escalations Page

The Escalations page shows all decisions your agents have requested. You can:

- View pending escalations waiting for human review
- See auto-resolved cases handled by existing rules
- Filter by agent, status, or time period
- Review the full context and metadata for each escalation
- Manually approve or reject pending decisions

### Rules Page

The Rules page shows all your active and proposed rules:

- Active rules that are currently handling decisions automatically
- Pending rules waiting for your approval
- View rule conditions, actions, and exceptions
- Edit rule descriptions before approving them
- See how many times each rule has been applied
- Deactivate or delete rules that are no longer needed

### Organization Settings

- Manage API keys (create, revoke, rotate)
- Configure Slack integration for notifications
- Set up webhooks for custom integrations
- Invite team members to your organization
- View usage metrics and billing information

---

## Error Handling

### Exception Types

Signal can raise the following exceptions:

- \`SignalTimeout\` - Decision took longer than timeout_seconds
- \`SignalAuthError\` - Invalid or missing API key
- \`SignalNetworkError\` - Network connectivity issues
- \`SignalError\` - Base exception for all Signal errors

### Handling Errors

\`\`\`python
import signalops
from signalops.exceptions import (
    SignalTimeout,
    SignalAuthError,
    SignalNetworkError,
    SignalError
)

try:
    result = await signalops.escalate(
        agent_id="my-agent",
        question="Should I proceed?",
        context="Important context",
        timeout_seconds=300
    )
except SignalTimeout:
    # Decision took too long - use safe default
    logger.warning("Signal timeout - using fallback")
    result = use_safe_default()
except SignalAuthError:
    # API key is invalid
    logger.error("Signal auth failed - check API key")
    raise
except SignalNetworkError as e:
    # Network issue - maybe retry
    logger.error(f"Signal network error: {e}")
    result = retry_with_backoff()
except SignalError as e:
    # Catch-all for other Signal errors
    logger.error(f"Signal error: {e}")
    result = use_safe_default()
\`\`\`

### Retry Logic

Implement retry logic for transient failures:

\`\`\`python
import asyncio
from signalops.exceptions import SignalNetworkError

async def escalate_with_retry(max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            return await signalops.escalate(**kwargs)
        except SignalNetworkError as e:
            if attempt == max_retries - 1:
                raise

            wait_time = 2 ** attempt  # Exponential backoff
            logger.warning(f"Retry {attempt + 1}/{max_retries} after {wait_time}s")
            await asyncio.sleep(wait_time)

# Usage
result = await escalate_with_retry(
    agent_id="my-agent",
    question="Should I proceed?",
    context="Context here"
)
\`\`\`

---

## Troubleshooting

### Escalations Not Appearing in Slack

1. Verify Slack integration is configured in Organization Settings
2. Check that the Signal app is installed in your Slack workspace
3. Ensure the notification channel exists and Signal bot is invited
4. Look for errors in the dashboard Escalations page

### Timeout Errors

If you're getting timeout errors:

- Increase timeout_seconds parameter (default is 3600 / 1 hour)
- Ensure humans are actively reviewing escalations in Slack
- Consider implementing a fallback decision for timeout cases
- Check if your network connection is stable

### Rules Not Auto-Resolving

- Check that the rule status is "active" in the Rules page
- Verify the context matches the rule conditions
- Ensure you're using the same agent_id as when the rule was created
- Review rule exceptions - they may be excluding your case
- Check if context format is consistent with previous escalations

---

## Best Practices

### Writing Good Context

The quality of your escalations depends on the context you provide. Good context should:

- Include all relevant information needed to make the decision
- Be structured consistently (use the same format each time)
- Include quantitative data (amounts, counts, percentages)
- Mention any relevant history or patterns
- Avoid including sensitive information like passwords or tokens

### Agent IDs

- Use descriptive agent_id names (e.g., "customer-support-refunds" not "agent1")
- Keep agent_id consistent for the same type of decisions
- Use hyphens to separate words (not underscores or spaces)
- Organize by department-function-subdomain if helpful

### Error Handling

\`\`\`python
import signalops
from signalops.exceptions import SignalTimeout, SignalError

try:
    result = await signalops.escalate(
        agent_id="my-agent",
        question="Should I proceed?",
        context="Important decision context",
        timeout_seconds=300
    )
except SignalTimeout:
    # Handle timeout - decision took too long
    result = default_safe_action()
except SignalError as e:
    # Handle other Signal errors
    logger.error(f"Signal error: {e}")
    result = fallback_decision()
\`\`\`

### Testing

- Use different API keys for development, staging, and production
- Test with real-looking data to ensure rules work correctly
- Review proposed rules carefully before approving them
- Start with small rollouts before applying rules broadly
- Monitor auto-resolution rates in the dashboard

---

## Security

### API Key Management

- Never commit API keys to version control
- Use environment variables to store keys
- Rotate keys regularly (every 90 days recommended)
- Use different keys for development, staging, and production
- Revoke keys immediately if compromised

\`\`\`python
import os
import signalops

# Load API key from environment
api_key = os.environ.get("SIGNAL_API_KEY")
if not api_key:
    raise ValueError("SIGNAL_API_KEY environment variable not set")

signalops.configure(api_key=api_key)
\`\`\`

### Sensitive Data

Be careful about what data you include in escalation context:

- Do not include passwords, tokens, or API keys
- Avoid including full credit card numbers or SSNs
- Redact or mask sensitive personal information
- Consider data retention policies - context is stored
- Review Slack channel permissions for escalations

\`\`\`python
# Bad - includes sensitive data
context = f"Card: {full_card_number}, CVV: {cvv}"

# Good - masks sensitive data
masked_card = f"****{full_card_number[-4:]}"
context = f"Card ending in: {masked_card}, Amount: $\${amount}"
\`\`\`

### Network Security

- All Signal API calls are made over HTTPS
- TLS 1.2 or higher is required
- API endpoints support certificate pinning
- Webhook signatures should be verified (if using webhooks)

### Compliance

Signal is designed with compliance in mind:

- SOC 2 Type II compliant infrastructure
- GDPR-compliant data handling
- Data residency options available (contact support)
- Audit logs for all escalations and decisions
- Data retention policies can be configured

---

Generated with Signal v${SIGNALOPS_VERSION}
Visit ${DASHBOARD_URL} for more information.
`;
  };

  const handleDownload = () => {
    try {
      const markdown = generateMarkdown();
      const blob = new Blob([markdown], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `signal-docs-v${SIGNALOPS_VERSION}.md`;
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 100);
    } catch (error) {
      console.error("Download failed:", error);
      alert("Download failed. Please try again.");
    }
  };

  return (
    <div style={{ minHeight: "100vh", maxWidth: "100%", overflowX: "hidden", background: "#f7f7f5", fontFamily: "'Manrope', sans-serif" }}>
      {/* Navigation */}
      <nav style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: isMobile ? "0.875rem 1rem" : "1rem 2rem",
        background: "rgba(247,247,245,0.8)",
        backdropFilter: "blur(12px)",
        borderBottom: "1px solid rgba(13,13,11,0.07)"
      }}>
        <Link to="/" style={{ display: "flex", alignItems: "center" }}>
          <img src="/signal-logo-black.png" alt="Signal" style={{ height: isMobile ? "1.75rem" : "2.25rem", width: "auto", filter: "invert(1) brightness(1.5)" }} />
        </Link>
        <div style={{ display: "flex", gap: isMobile ? "0.875rem" : "1.5rem", alignItems: "center" }}>
          <Link to="/" style={{ fontSize: "0.875rem", fontWeight: 500, color: "#0d0d0b", textDecoration: "none" }}>Home</Link>
          <a href={DASHBOARD_URL} target="_blank" rel="noopener noreferrer" style={{ fontSize: "0.875rem", fontWeight: 500, color: "#0d0d0b", textDecoration: "none" }}>Dashboard</a>
          <button
            onClick={handleDownload}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.375rem",
              padding: "0.5rem 0.875rem",
              fontSize: "0.875rem",
              fontWeight: 600,
              background: "#0d0d0b",
              color: "#f7f7f5",
              border: "none",
              borderRadius: "0.375rem",
              cursor: "pointer",
              transition: "all 0.2s ease"
            }}
            onMouseOver={(e) => {
              e.currentTarget.style.background = "#2d2d2b";
            }}
            onMouseOut={(e) => {
              e.currentTarget.style.background = "#0d0d0b";
            }}
          >
            <Download size={16} />
            Download
          </button>
        </div>
      </nav>

      <div style={{ paddingTop: isMobile ? "6rem" : "8rem", paddingBottom: "4rem" }}>
        <div style={{ maxWidth: "1400px", margin: "0 auto", padding: isMobile ? "0 1rem" : "0 2rem", position: "relative" }}>
          <div style={{ display: isNarrow ? "block" : "flex", gap: "4rem" }}>

          {/* Desktop Sidebar */}
          {!isNarrow && (
            <aside style={{
              position: "fixed",
              top: "7rem",
              width: "240px",
              maxHeight: "calc(100vh - 8rem)",
              overflowY: "auto",
              paddingRight: "1rem"
            }}>
              <p style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.1em", color: "#6a6a67", marginBottom: "1rem", fontFamily: "'Geist Mono', monospace", fontWeight: 600 }}>
                Contents
              </p>
              <nav style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                {navItems.map((item) => {
                  const isActive = activeSection === item.id;
                  return (
                    <a
                      key={item.id}
                      href={"#" + item.id}
                      style={{
                        fontSize: "0.875rem",
                        color: isActive ? "#0d0d0b" : "#6a6a67",
                        textDecoration: "none",
                        paddingLeft: "0.75rem",
                        paddingTop: "0.25rem",
                        paddingBottom: "0.25rem",
                        borderLeft: isActive ? "2px solid #0d0d0b" : "2px solid transparent",
                        fontWeight: isActive ? 600 : 400,
                        transition: "all 0.2s ease"
                      }}
                    >
                      {item.label}
                    </a>
                  );
                })}
              </nav>
            </aside>
          )}

          {/* Mobile sidebar */}
          {isNarrow && (
            <aside style={{ marginBottom: "2.5rem" }}>
              <p style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.1em", color: "#6a6a67", marginBottom: "1rem", fontFamily: "'Geist Mono', monospace", fontWeight: 600 }}>
                Contents
              </p>
              <nav style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: "0.625rem 1rem" }}>
                {navItems.map((item) => {
                  const isActive = activeSection === item.id;
                  return (
                    <a
                      key={item.id}
                      href={"#" + item.id}
                      style={{
                        fontSize: "0.875rem",
                        color: isActive ? "#0d0d0b" : "#6a6a67",
                        textDecoration: "none",
                        paddingTop: "0.25rem",
                        paddingBottom: "0.25rem",
                        borderBottom: isActive ? "1px solid #0d0d0b" : "1px solid transparent",
                        fontWeight: isActive ? 600 : 400,
                        transition: "all 0.2s ease"
                      }}
                    >
                      {item.label}
                    </a>
                  );
                })}
              </nav>
            </aside>
          )}

          {/* Main Content */}
          <article style={{ maxWidth: isNarrow ? "100%" : "56rem", marginLeft: isNarrow ? 0 : "calc(240px + 4rem)" }}>
            {/* Header */}
            <Reveal>
              <div style={{ marginBottom: "4rem" }}>
                <p style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.1em", color: "#6a6a67", marginBottom: "1.5rem", fontFamily: "'Geist Mono', monospace" }}>
                  Documentation v{SIGNALOPS_VERSION}
                </p>
                <h1 style={{ fontSize: isMobile ? "2.35rem" : "3.5rem", fontWeight: 800, lineHeight: 1.1, marginBottom: "1.5rem", color: "#0d0d0b" }}>
                  Signal Documentation
                </h1>
                <p style={{ fontSize: "1.125rem", fontWeight: 300, lineHeight: 1.6, color: "#6a6a67", marginBottom: "1.5rem" }}>
                  Complete guide to building autonomous AI agents with human-in-the-loop decision making.
                </p>
                <button
                  onClick={handleDownload}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    padding: "0.75rem 1.5rem",
                    fontSize: "0.9375rem",
                    fontWeight: 600,
                    background: "#0d0d0b",
                    color: "#f7f7f5",
                    border: "none",
                    borderRadius: "0.375rem",
                    cursor: "pointer",
                    transition: "all 0.2s ease"
                  }}
                  onMouseOver={(e) => {
                    e.currentTarget.style.background = "#2d2d2b";
                  }}
                  onMouseOut={(e) => {
                    e.currentTarget.style.background = "#0d0d0b";
                  }}
                >
                  <Download size={18} />
                  Download as Markdown
                </button>
              </div>
            </Reveal>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "4rem" }} />

            <section id="quickstart" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Quickstart (5 Minutes)</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Step 1: Install Signal</h3>
                  <CodeBlock language="bash" code="pip install signalops" />
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Step 2: Get Your API Key</h3>
                  <ol style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Go to <a href={DASHBOARD_URL} target="_blank" rel="noopener noreferrer" style={{ color: "#0d0d0b", fontWeight: 600 }}>{DASHBOARD_URL}</a></li>
                    <li>Sign up and create an account</li>
                    <li>Create an organization (or open an existing one)</li>
                    <li>Go to Organization Settings</li>
                    <li>Click "Add new key", name it, and copy it</li>
                    <li>Save this key securely - it starts with <code style={{ background: "#0d0d0b", color: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>sk_live_</code></li>
                  </ol>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Step 3: Write Your First Agent</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Here's a complete working example:</p>
                  <CodeBlock language="python" code={'import asyncio\nimport signalops\n\n# Configure Signal\nsignalops.configure(api_key="sk_live_your_api_key_here")\n\nasync def handle_refund_request(customer_id, amount, reason):\n    # Ask Signal for a decision. Dict context is safest because Signal normalizes field names.\n    result = await signalops.escalate(\n        agent_id="customer-support-refunds",\n        question="Should I issue a refund?",\n        context={\n            "customer_id": customer_id,\n            "order_amount": amount,\n            "reason": reason,\n            "customer_tier": "premium"\n        }\n    )\n\n    # Act on the decision\n    if result.decision == "approve":\n        print(f"✓ Refund approved")\n        return True\n    else:\n        print(f"✗ Refund denied")\n        return False\n\n# Run it\nasyncio.run(handle_refund_request("cust_123", 150, "damaged"))'} />
                </div>
              </Reveal>
            </section>

            <SectionDivider />

            <section id="concepts" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Core Concepts</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>What is Signal?</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    Signal is an operational intelligence system that helps AI agents make consistent decisions by learning from human judgment.
                    When your agent encounters a decision it's uncertain about, Signal handles the escalation, captures the human decision,
                    and automatically creates rules so future similar situations are handled automatically.
                  </p>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>How It Works</h3>
                  <ol style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li><strong>Agent Escalates:</strong> Your agent calls signalops.escalate() with a question and context</li>
                    <li><strong>Signal Checks Rules:</strong> If a matching rule exists, Signal returns the decision instantly</li>
                    <li><strong>Human Review (if needed):</strong> If no rule matches, Signal sends the decision to Slack for human review</li>
                    <li><strong>Rule Creation:</strong> After human approval, Signal creates a rule so future similar cases are auto-resolved</li>
                    <li><strong>Continuous Learning:</strong> Your agents get smarter over time as more rules are created</li>
                  </ol>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Key Features</h3>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li><strong>Instant Decisions:</strong> Rules are checked in milliseconds for auto-resolved cases</li>
                    <li><strong>Slack Integration:</strong> Human reviewers get notified in Slack with full context</li>
                    <li><strong>Dashboard:</strong> View all escalations, rules, and metrics in a web dashboard</li>
                    <li><strong>Rule Management:</strong> Edit, approve, or discard proposed rules before they go live</li>
                    <li><strong>Analytics:</strong> Track auto-resolution rates, response times, and decision trends</li>
                  </ul>
                </div>
              </Reveal>
            </section>

            <SectionDivider />

            <section id="installation" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Installation</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Python Package</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    Signal is available as a Python package. Install it using pip:
                  </p>
                  <CodeBlock language="bash" code="pip install signalops" />
                  <p style={{ marginTop: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    Or add it to your requirements.txt:
                  </p>
                  <CodeBlock language="text" code="signalops>=0.2.1" />
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Requirements</h3>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Python 3.8 or higher</li>
                    <li>asyncio support (Python 3.7+ includes this by default)</li>
                    <li>Active internet connection for API calls</li>
                    <li>A Signal account and API key</li>
                  </ul>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Verify Installation</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    Check that Signal is installed correctly:
                  </p>
                  <CodeBlock language="bash" code={'python -c "import signalops; print(signalops.__version__)"'} />
                </div>
              </Reveal>
            </section>

            <SectionDivider />

            <section id="examples" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Complete Examples</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Content Moderation</h3>
                  <CodeBlock language="python" code={'async def moderate_user_content(post_id, content, user_history):\n    result = await signalops.escalate(\n        agent_id="content-moderation",\n        question="Should this content be approved?",\n        context=f"""Post ID: {post_id}\nContent: {content}\nUser has {user_history["violations"]} prior violations\nUser tier: {user_history["tier"]}""",\n        metadata={"post_id": post_id, "user_id": user_history["id"]}\n    )\n    \n    if result.decision == "approve":\n        publish_post(post_id)\n    else:\n        reject_post(post_id)\n    \n    return result.decision'} />
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Financial Approvals</h3>
                  <CodeBlock language="python" code={'async def approve_expense(expense_id, amount, category, employee_level):\n    result = await signalops.escalate(\n        agent_id="expense-approvals",\n        question="Should this expense be approved?",\n        context=f"""Expense ID: {expense_id}\nAmount: ${amount}\nCategory: {category}\nEmployee Level: {employee_level}""",\n        action="approve_expense",\n        timeout_seconds=1800  # 30 minutes\n    )\n    \n    if result.auto_resolved:\n        print(f"Auto-approved by rule {result.rule_id}")\n    \n    return result.decision == "approve"'} />
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Customer Support Routing</h3>
                  <CodeBlock language="python" code={'async def route_support_ticket(ticket_id, issue_type, customer_value):\n    result = await signalops.escalate(\n        agent_id="support-routing",\n        question="Should this ticket be escalated to senior support?",\n        context=f"""Ticket: {ticket_id}\nIssue: {issue_type}\nCustomer LTV: ${customer_value}\nPriority: {"high" if customer_value > 10000 else "normal"}"""\n    )\n    \n    if result.decision == "approve":\n        assign_to_senior_team(ticket_id)\n    else:\n        assign_to_standard_team(ticket_id)\n    \n    return result'} />
                </div>
              </Reveal>
            </section>

            <SectionDivider />

            <section id="api-reference" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>API Reference</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1.5rem", color: "#0d0d0b" }}>signalops.configure()</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Configure Signal globally. Call this once at the start of your application.</p>
                  <CodeBlock language="python" code={'signalops.configure(\n    api_key="sk_live_your_api_key_here",\n    base_url="https://signal-omega-tan.vercel.app",  # Optional\n    dev_mode=False,  # Optional: Enable debug logging\n    auto_enrich=True  # Optional: Auto-add environment metadata (default: True)\n)'} />
                  <div style={{ marginTop: "1.5rem" }}>
                    <h4 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.75rem", color: "#0d0d0b" }}>Parameters:</h4>
                    <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>api_key</code> (str, required): Your Signal API key</li>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>base_url</code> (str, optional): Custom API endpoint URL</li>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>dev_mode</code> (bool, optional): Enable debug logging for development (default: False)</li>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>auto_enrich</code> (bool, optional): Automatically add timestamp and environment to context (default: True)</li>
                    </ul>
                  </div>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1.5rem", color: "#0d0d0b" }}>signalops.escalate()</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Escalate a decision to Signal. Returns a decision from an existing rule, or waits for human review.</p>
                  <CodeBlock language="python" code={'result = await signalops.escalate(\n    agent_id="customer-support-refunds",\n    question="Should I issue a refund?",\n    context={\n        "customer_id": "cust_123",\n        "order_amount": 150,\n        "author": "support-agent"\n    },\n    action="refund_request",  # optional\n    timeout_seconds=600  # optional, default 3600\n)'} />
                  <div style={{ marginTop: "1.5rem", marginBottom: "1.5rem" }}>
                    <h4 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.75rem", color: "#0d0d0b" }}>Parameters:</h4>
                    <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>agent_id</code> (str, required): Unique identifier for your agent</li>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>question</code> (str, required): The decision question</li>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>context</code> (dict or str, required): Relevant context for the decision. Dicts are recommended because Signal normalizes field names before matching rules.</li>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>action</code> (str, optional): Action being requested</li>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>metadata</code> (dict, optional): Additional structured data</li>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>timeout_seconds</code> (int, optional): Max wait time (default: 3600)</li>
                    </ul>
                  </div>
                  <div style={{ marginTop: "1.5rem" }}>
                    <h4 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.75rem", color: "#0d0d0b" }}>Returns:</h4>
                    <p style={{ marginBottom: "0.5rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Object with the following properties:</p>
                    <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>decision</code> (str): The decision ("approve" or "reject")</li>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>rule_id</code> (str | None): ID of the matching rule (if auto-resolved)</li>
                      <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>auto_resolved</code> (bool): Whether decision was made by a rule</li>
                    </ul>
                  </div>
                </div>
              </Reveal>
            </section>

            <SectionDivider />

            <section id="patterns" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Common Patterns</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Fallback on Timeout</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    Always have a safe fallback when decisions time out:
                  </p>
                  <CodeBlock language="python" code={'from signalops.exceptions import SignalTimeout\n\ntry:\n    result = await signalops.escalate(\n        agent_id="fraud-detection",\n        question="Is this transaction fraudulent?",\n        context=f"Amount: ${amount}, Location: {location}",\n        timeout_seconds=120\n    )\n    block_transaction = result.decision == "reject"\nexcept SignalTimeout:\n    # Default to blocking suspicious transactions\n    block_transaction = amount > 10000 or is_high_risk_location(location)'} />
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Parallel Escalations</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    Make multiple independent decisions in parallel:
                  </p>
                  <CodeBlock language="python" code={'import asyncio\n\n# Run multiple escalations concurrently\nresults = await asyncio.gather(\n    signalops.escalate(\n        agent_id="content-mod",\n        question="Should this be approved?",\n        context=f"Post: {post_text}"\n    ),\n    signalops.escalate(\n        agent_id="user-verification",\n        question="Should this user be verified?",\n        context=f"User: {user_id}, History: {history}"\n    ),\n    return_exceptions=True\n)\n\ncontent_approved, user_verified = results'} />
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Conditional Escalation</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    Only escalate when needed based on confidence or thresholds:
                  </p>
                  <CodeBlock language="python" code={'async def handle_refund(amount, reason, customer_tier):\n    # Auto-approve small refunds for premium customers\n    if customer_tier == "premium" and amount < 50:\n        return "approve"\n    \n    # Escalate everything else\n    result = await signalops.escalate(\n        agent_id="refunds",\n        question="Should I approve this refund?",\n        context=f"Amount: ${amount}\\nReason: {reason}\\nTier: {customer_tier}"\n    )\n    \n    return result.decision'} />
                </div>
              </Reveal>
            </section>

            <SectionDivider />

            <section id="dashboard" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Using the Dashboard</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Getting Started</h3>
                  <ol style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Go to <a href={DASHBOARD_URL} target="_blank" rel="noopener noreferrer" style={{ color: "#0d0d0b", fontWeight: 600 }}>{DASHBOARD_URL}</a></li>
                    <li>Sign in with your account</li>
                    <li>Select your organization from the dropdown</li>
                    <li>You'll see three main sections: Escalations, Rules, and Settings</li>
                  </ol>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Escalations Page</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    The Escalations page shows all decisions your agents have requested. You can:
                  </p>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>View pending escalations waiting for human review</li>
                    <li>See auto-resolved cases handled by existing rules</li>
                    <li>Filter by agent, status, or time period</li>
                    <li>Review the full context and metadata for each escalation</li>
                    <li>Manually approve or reject pending decisions</li>
                  </ul>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Rules Page</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    The Rules page shows all your active and proposed rules:
                  </p>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Active rules that are currently handling decisions automatically</li>
                    <li>Pending rules waiting for your approval</li>
                    <li>View rule conditions, actions, and exceptions</li>
                    <li>Edit rule descriptions before approving them</li>
                    <li>See how many times each rule has been applied</li>
                    <li>Deactivate or delete rules that are no longer needed</li>
                  </ul>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Organization Settings</h3>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Manage API keys (create, revoke, rotate)</li>
                    <li>Configure Slack integration for notifications</li>
                    <li>Set up webhooks for custom integrations</li>
                    <li>Invite team members to your organization</li>
                    <li>View usage metrics and billing information</li>
                  </ul>
                </div>
              </Reveal>
            </section>

            <SectionDivider />

            <section id="errors" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Error Handling</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Exception Types</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    Signal can raise the following exceptions:
                  </p>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>SignalTimeout</code> - Decision took longer than timeout_seconds</li>
                    <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>SignalAuthError</code> - Invalid or missing API key</li>
                    <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>SignalNetworkError</code> - Network connectivity issues</li>
                    <li><code style={{ background: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>SignalError</code> - Base exception for all Signal errors</li>
                  </ul>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Handling Errors</h3>
                  <CodeBlock language="python" code={'import signalops\nfrom signalops.exceptions import (\n    SignalTimeout,\n    SignalAuthError,\n    SignalNetworkError,\n    SignalError\n)\n\ntry:\n    result = await signalops.escalate(\n        agent_id="my-agent",\n        question="Should I proceed?",\n        context="Important context",\n        timeout_seconds=300\n    )\nexcept SignalTimeout:\n    # Decision took too long - use safe default\n    logger.warning("Signal timeout - using fallback")\n    result = use_safe_default()\nexcept SignalAuthError:\n    # API key is invalid\n    logger.error("Signal auth failed - check API key")\n    raise\nexcept SignalNetworkError as e:\n    # Network issue - maybe retry\n    logger.error(f"Signal network error: {e}")\n    result = retry_with_backoff()\nexcept SignalError as e:\n    # Catch-all for other Signal errors\n    logger.error(f"Signal error: {e}")\n    result = use_safe_default()'} />
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Retry Logic</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    Implement retry logic for transient failures:
                  </p>
                  <CodeBlock language="python" code={'import asyncio\nfrom signalops.exceptions import SignalNetworkError\n\nasync def escalate_with_retry(max_retries=3, **kwargs):\n    for attempt in range(max_retries):\n        try:\n            return await signalops.escalate(**kwargs)\n        except SignalNetworkError as e:\n            if attempt == max_retries - 1:\n                raise\n            \n            wait_time = 2 ** attempt  # Exponential backoff\n            logger.warning(f"Retry {attempt + 1}/{max_retries} after {wait_time}s")\n            await asyncio.sleep(wait_time)\n\n# Usage\nresult = await escalate_with_retry(\n    agent_id="my-agent",\n    question="Should I proceed?",\n    context="Context here"\n)'} />
                </div>
              </Reveal>
            </section>

            <SectionDivider />

            <section id="troubleshooting" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Troubleshooting</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Escalations Not Appearing in Slack</h3>
                  <ol style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Verify Slack integration is configured in Organization Settings</li>
                    <li>Check that the Signal app is installed in your Slack workspace</li>
                    <li>Ensure the notification channel exists and Signal bot is invited</li>
                    <li>Look for errors in the dashboard Escalations page</li>
                  </ol>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Timeout Errors</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    If you're getting timeout errors:
                  </p>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Increase timeout_seconds parameter (default is 3600 / 1 hour)</li>
                    <li>Ensure humans are actively reviewing escalations in Slack</li>
                    <li>Consider implementing a fallback decision for timeout cases</li>
                    <li>Check if your network connection is stable</li>
                  </ul>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Rules Not Auto-Resolving</h3>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Check that the rule status is "active" in the Rules page</li>
                    <li>Verify the context matches the rule conditions</li>
                    <li>Ensure you're using the same agent_id as when the rule was created</li>
                    <li>Review rule exceptions - they may be excluding your case</li>
                    <li>Check if context format is consistent with previous escalations</li>
                  </ul>
                </div>
              </Reveal>
            </section>

            <SectionDivider />

            <section id="best-practices" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Best Practices</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Writing Good Context</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    The quality of your escalations depends on the context you provide. Good context should:
                  </p>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Include all relevant information needed to make the decision</li>
                    <li>Be structured consistently (use the same format each time)</li>
                    <li>Include quantitative data (amounts, counts, percentages)</li>
                    <li>Mention any relevant history or patterns</li>
                    <li>Avoid including sensitive information like passwords or tokens</li>
                  </ul>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Agent IDs</h3>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Use descriptive agent_id names (e.g., "customer-support-refunds" not "agent1")</li>
                    <li>Keep agent_id consistent for the same type of decisions</li>
                    <li>Use hyphens to separate words (not underscores or spaces)</li>
                    <li>Organize by department-function-subdomain if helpful</li>
                  </ul>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Error Handling</h3>
                  <CodeBlock language="python" code={'import signalops\nfrom signalops.exceptions import SignalTimeout, SignalError\n\ntry:\n    result = await signalops.escalate(\n        agent_id="my-agent",\n        question="Should I proceed?",\n        context="Important decision context",\n        timeout_seconds=300\n    )\nexcept SignalTimeout:\n    # Handle timeout - decision took too long\n    result = default_safe_action()\nexcept SignalError as e:\n    # Handle other Signal errors\n    logger.error(f"Signal error: {e}")\n    result = fallback_decision()'} />
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Testing</h3>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Use different API keys for development, staging, and production</li>
                    <li>Test with real-looking data to ensure rules work correctly</li>
                    <li>Review proposed rules carefully before approving them</li>
                    <li>Start with small rollouts before applying rules broadly</li>
                    <li>Monitor auto-resolution rates in the dashboard</li>
                  </ul>
                </div>
              </Reveal>
            </section>

            <SectionDivider />

            <section id="security" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Security</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>API Key Management</h3>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Never commit API keys to version control</li>
                    <li>Use environment variables to store keys</li>
                    <li>Rotate keys regularly (every 90 days recommended)</li>
                    <li>Use different keys for development, staging, and production</li>
                    <li>Revoke keys immediately if compromised</li>
                  </ul>
                  <div style={{ marginTop: "1rem" }}>
                    <CodeBlock language="python" code={'import os\nimport signalops\n\n# Load API key from environment\napi_key = os.environ.get("SIGNAL_API_KEY")\nif not api_key:\n    raise ValueError("SIGNAL_API_KEY environment variable not set")\n\nsignalops.configure(api_key=api_key)'} />
                  </div>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Sensitive Data</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    Be careful about what data you include in escalation context:
                  </p>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Do not include passwords, tokens, or API keys</li>
                    <li>Avoid including full credit card numbers or SSNs</li>
                    <li>Redact or mask sensitive personal information</li>
                    <li>Consider data retention policies - context is stored</li>
                    <li>Review Slack channel permissions for escalations</li>
                  </ul>
                  <div style={{ marginTop: "1rem" }}>
                    <CodeBlock language="python" code={'# Bad - includes sensitive data\ncontext = f"Card: {full_card_number}, CVV: {cvv}"\n\n# Good - masks sensitive data\nmasked_card = f"****{full_card_number[-4:]}"\ncontext = f"Card ending in: {masked_card}, Amount: ${amount}"'} />
                  </div>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Network Security</h3>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>All Signal API calls are made over HTTPS</li>
                    <li>TLS 1.2 or higher is required</li>
                    <li>API endpoints support certificate pinning</li>
                    <li>Webhook signatures should be verified (if using webhooks)</li>
                  </ul>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Compliance</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem", lineHeight: 1.8 }}>
                    Signal is designed with compliance in mind:
                  </p>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>SOC 2 Type II compliant infrastructure</li>
                    <li>GDPR-compliant data handling</li>
                    <li>Data residency options available (contact support)</li>
                    <li>Audit logs for all escalations and decisions</li>
                    <li>Data retention policies can be configured</li>
                  </ul>
                </div>
              </Reveal>
            </section>

            <SectionDivider />

            <Reveal>
              <div style={{ padding: "3rem", borderRadius: "0.5rem", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)", textAlign: "center" }}>
                <h3 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "1rem", color: "#f7f7f5" }}>Want the Complete Guide?</h3>
                <p style={{ fontSize: "1.0625rem", marginBottom: "2rem", color: "#9a9a97" }}>
                  Download the full documentation including examples, patterns, troubleshooting, security best practices, and more.
                </p>
                <button
                  onClick={handleDownload}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    padding: "1rem 2rem",
                    fontSize: "0.9375rem",
                    fontWeight: 700,
                    background: "#f7f7f5",
                    color: "#0d0d0b",
                    border: "none",
                    borderRadius: "0.375rem",
                    cursor: "pointer"
                  }}
                >
                  <Download size={18} />
                  Download Complete Docs
                </button>
              </div>
            </Reveal>
          </article>
        </div>
      </div>
    </div>
  </div>
  );
}
