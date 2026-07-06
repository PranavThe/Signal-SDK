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
const SIGNALOPS_VERSION = "0.1.2";

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
        context=f"""Customer ID: {customer_id}
Order Amount: ${order_amount}
Reason: {reason}
Days Since Purchase: {days_since_purchase}
Customer Tier: premium""",
        metadata={
            "customer_id": customer_id,
            "order_amount": order_amount,
            "reason": reason
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
print(signalops.__version__)  # Should print ${SIGNALOPS_VERSION}
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

**Example:**
\`\`\`python
import signalops

signalops.configure(
    api_key="sk_live_your_api_key_here",
    base_url="https://signal-omega-tan.vercel.app"  # Optional
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
    context=\"\"\"Customer ID: cust_123
Order Amount: $150
Reason: Product arrived damaged
Days Since Purchase: 3
Customer Tier: premium\"\"\",
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
- The \`context\` parameter should be formatted as \`Field: value\` on separate lines for best dashboard readability
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

Format context as \`Field: value\` on separate lines:

✅ **Good:**
\`\`\`python
context = \"\"\"Customer ID: cust_123
Order Amount: $150
Reason: Product damaged
Days Since Purchase: 3
Customer Tier: premium\"\"\"
\`\`\`

❌ **Bad:**
\`\`\`python
context = "Customer cust_123 wants a refund for $150 because product damaged, 3 days since purchase, premium tier"
\`\`\`

**Why:** Structured context is easier to read in the dashboard and helps AI extract better rules.

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

            {/* Quickstart */}
            <section id="quickstart" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Quickstart (5 Minutes)</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Step 1: Install Signal</h3>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>bash</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.9375rem", fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>pip install signalops</pre>
                  </div>
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

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Step 3: Write Your First Agent</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Here's a complete working example:</p>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>python</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.875rem", lineHeight: 1.6, fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>{`import asyncio
import signalops

# Configure Signal
signalops.configure(api_key="sk_live_your_api_key_here")

async def handle_refund_request(customer_id, amount, reason):
    # Ask Signal for a decision
    result = await signalops.escalate(
        agent_id="customer-support-refunds",
        question="Should I issue a refund?",
        context=f"""Customer ID: {customer_id}
Order Amount: ${amount}
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
asyncio.run(handle_refund_request("cust_123", 150, "damaged"))`}</pre>
                  </div>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>What Happens Next</h3>
                  <div style={{ display: "grid", gap: "0.75rem" }}>
                    {[
                      "Your agent calls escalate()",
                      "Signal checks if any existing rules match",
                      "If a rule matches → Returns decision immediately",
                      "If no rule → Shows in dashboard for human review",
                      "Human approves/rejects and optionally creates a rule",
                      "Your agent receives the decision and acts on it"
                    ].map((step, i) => (
                      <div key={i} style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
                        <div style={{ width: "1.5rem", height: "1.5rem", borderRadius: "50%", background: "#0d0d0b", color: "#f7f7f5", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.75rem", fontWeight: 600, flexShrink: 0 }}>{i + 1}</div>
                        <p style={{ margin: 0, color: "#4a4a47", fontSize: "0.9375rem" }}>{step}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* Core Concepts */}
            <section id="concepts" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Core Concepts</h2>

                <div style={{ marginBottom: "2.5rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>What is Signal?</h3>
                  <p style={{ fontSize: "1.0625rem", lineHeight: 1.7, color: "#4a4a47" }}>
                    Signal is a human-in-the-loop decision framework for AI agents. Instead of hard-coding rules or letting your agent make risky decisions alone, Signal lets you escalate uncertain decisions to humans, learn from those decisions, and progressively automate as your agent builds up a rulebook.
                  </p>
                </div>

                <div style={{ marginBottom: "2.5rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1.5rem", color: "#0d0d0b" }}>Key Terms</h3>
                  <div style={{ display: "grid", gap: "1rem" }}>
                    {[
                      { term: "Escalation", def: "A decision your agent asks Signal to make" },
                      { term: "Rule", def: "A policy that auto-resolves future similar escalations" },
                      { term: "Agent ID", def: "Identifier for your agent (e.g., \"customer-support-refunds\")" },
                      { term: "Action", def: "Type of decision being made (e.g., \"refund_request\")" },
                      { term: "Context", def: "Information about the decision (formatted as field:value pairs)" },
                      { term: "Auto-resolved", def: "Decision was made by a rule without human input" },
                      { term: "Autonomy Score", def: "Percentage of decisions handled automatically by rules" }
                    ].map((item, i) => (
                      <div key={i} style={{ padding: "1rem", background: "#ffffff", border: "1px solid rgba(13,13,11,0.07)", borderRadius: "0.375rem" }}>
                        <strong style={{ color: "#0d0d0b", fontSize: "0.9375rem", fontFamily: "'Geist Mono', monospace" }}>{item.term}</strong>
                        <p style={{ margin: "0.5rem 0 0 0", color: "#6a6a67", fontSize: "0.9375rem" }}>{item.def}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* Installation */}
            <section id="installation" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Installation</h2>

                <div style={{ marginBottom: "2.5rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Requirements</h3>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Python 3.8 or higher</li>
                    <li>An async-compatible environment (Signal uses async/await)</li>
                  </ul>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Install via pip</h3>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)", marginBottom: "1.5rem" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>bash</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.9375rem", fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>pip install signalops</pre>
                  </div>
                  <p style={{ fontSize: "0.9375rem", color: "#6a6a67" }}>Latest version: <strong>{SIGNALOPS_VERSION}</strong></p>
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* Examples */}
            <section id="examples" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Complete Examples</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Content Moderation Agent</h3>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>python</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.875rem", lineHeight: 1.6, fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>{`import asyncio
import signalops

signalops.configure(api_key="sk_live_your_api_key_here")

async def moderate_post(post_id, content, user_reputation):
    result = await signalops.escalate(
        agent_id="content-moderator",
        question="Should I approve this post?",
        context=f"""Post ID: {post_id}
Content: {content[:200]}...
User Reputation: {user_reputation}
Contains URLs: {'yes' if 'http' in content else 'no'}"""
    )
    return result.decision == "approve"

asyncio.run(moderate_post("post_789", "Great article!", 0.85))`}</pre>
                  </div>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Transaction Approval Agent</h3>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>python</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.875rem", lineHeight: 1.6, fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>{`import asyncio
import signalops

signalops.configure(api_key="sk_live_your_api_key_here")

async def approve_transaction(txn_id, amount, risk_score):
    result = await signalops.escalate(
        agent_id="transaction-approvals",
        question="Should I approve this transaction?",
        context=f"""Transaction ID: {txn_id}
Amount: $150.00
Risk Score: {risk_score}
International: no"""
    )

    if result.auto_resolved:
        print(f"Auto-approved by rule {result.rule_id}")

    return result.decision == "approve"

asyncio.run(approve_transaction("txn_456", 5000.00, 0.3))`}</pre>
                  </div>
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* API Reference */}
            <section id="api-reference" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>API Reference</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1.5rem", color: "#0d0d0b" }}>signalops.configure()</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Configure Signal globally. Call this once at the start of your application.</p>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)", marginBottom: "1.5rem" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>python</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.875rem", lineHeight: 1.6, fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>{`signalops.configure(
    api_key="sk_live_your_api_key_here",
    base_url="https://signal-omega-tan.vercel.app"  # Optional
)`}</pre>
                  </div>
                  <div style={{ display: "grid", gap: "0.75rem" }}>
                    {[
                      { param: "api_key", type: "str, required", desc: "Your Signal API key starting with sk_live_" },
                      { param: "base_url", type: "str, optional", desc: "Signal API URL (default: hosted Signal)" }
                    ].map((p, i) => (
                      <div key={i} style={{ padding: "1rem", background: "#ffffff", border: "1px solid rgba(13,13,11,0.07)", borderRadius: "0.375rem" }}>
                        <code style={{ fontSize: "0.875rem", fontWeight: 600, fontFamily: "'Geist Mono', monospace", color: "#0d0d0b" }}>{p.param}</code>
                        <span style={{ fontSize: "0.875rem", marginLeft: "0.5rem", color: "#6a6a67" }}>({p.type}) — {p.desc}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1.5rem", color: "#0d0d0b" }}>signalops.escalate()</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Escalate a decision to Signal. Returns a decision from an existing rule, or waits for human review.</p>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)", marginBottom: "1.5rem" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>python</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.875rem", lineHeight: 1.6, fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>{`result = await signalops.escalate(
    agent_id="customer-support-refunds",
    question="Should I issue a refund?",
    context="Customer ID: cust_123\\nAmount: $150",
    action="refund_request",  # optional
    metadata={"customer_id": "cust_123"},  # optional
    timeout_seconds=600  # optional, default 3600
)`}</pre>
                  </div>
                  <h4 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Parameters</h4>
                  <div style={{ display: "grid", gap: "0.75rem", marginBottom: "1.5rem" }}>
                    {[
                      { param: "agent_id", type: "str, required", desc: "Unique identifier for your agent" },
                      { param: "question", type: "str, required", desc: "Clear yes/no question" },
                      { param: "context", type: "str, required", desc: "Decision context as field:value pairs" },
                      { param: "action", type: "str, optional", desc: "Action identifier for grouping decisions" },
                      { param: "metadata", type: "dict, optional", desc: "Additional structured data" },
                      { param: "timeout_seconds", type: "int, optional", desc: "Wait time for decision (default: 3600)" }
                    ].map((p, i) => (
                      <div key={i} style={{ padding: "1rem", background: "#ffffff", border: "1px solid rgba(13,13,11,0.07)", borderRadius: "0.375rem" }}>
                        <code style={{ fontSize: "0.875rem", fontWeight: 600, fontFamily: "'Geist Mono', monospace", color: "#0d0d0b" }}>{p.param}</code>
                        <span style={{ fontSize: "0.875rem", marginLeft: "0.5rem", color: "#6a6a67" }}>({p.type}) — {p.desc}</span>
                      </div>
                    ))}
                  </div>
                  <h4 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Returns</h4>
                  <p style={{ marginBottom: "0.75rem", color: "#4a4a47", fontSize: "1.0625rem" }}>EscalationResult object with:</p>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "0.9375rem" }}>
                    <li><code style={{ fontFamily: "'Geist Mono', monospace" }}>decision</code> (str) — The decision made (e.g., "approve", "reject")</li>
                    <li><code style={{ fontFamily: "'Geist Mono', monospace" }}>rule_id</code> (str | None) — ID of the rule that made this decision</li>
                    <li><code style={{ fontFamily: "'Geist Mono', monospace" }}>auto_resolved</code> (bool) — Whether resolved by a rule (True) or human (False)</li>
                  </ul>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1.5rem", color: "#0d0d0b" }}>signalops.check()</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Check existing rules without escalating. Does not create an escalation or wait for humans.</p>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>python</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.875rem", lineHeight: 1.6, fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>{`result = await signalops.check(
    action="refund_request",
    context={"customer_tier": "premium", "amount": 150},
    agent_id="customer-support-refunds"
)

# Returns: allowed (bool | None), rule_id (str | None)
if result.allowed is True:
    print("Approved by rule")
elif result.allowed is False:
    print("Denied by rule")
else:
    print("No rule found")`}</pre>
                  </div>
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* Best Practices */}
            <section id="best-practices" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Best Practices</h2>

                <div style={{ display: "grid", gap: "2rem" }}>
                  <div>
                    <h3 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>1. Write Clear Questions</h3>
                    <div style={{ display: "grid", gap: "0.75rem" }}>
                      <div style={{ padding: "1rem", borderRadius: "0.375rem", borderLeft: "4px solid #22c55e", background: "#f0fdf4" }}>
                        <p style={{ fontSize: "0.9375rem", margin: 0, color: "#166534" }}><strong>✓ Good:</strong> "Should I issue a refund for this order?"</p>
                      </div>
                      <div style={{ padding: "1rem", borderRadius: "0.375rem", borderLeft: "4px solid #ef4444", background: "#fef2f2" }}>
                        <p style={{ fontSize: "0.9375rem", margin: 0, color: "#991b1b" }}><strong>✗ Bad:</strong> "What should I do about this customer?"</p>
                      </div>
                    </div>
                  </div>

                  <div>
                    <h3 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>2. Use Structured Context</h3>
                    <p style={{ color: "#4a4a47", fontSize: "1.0625rem", marginBottom: "0.75rem" }}>Format context as field:value pairs on separate lines:</p>
                    <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)" }}>
                      <pre style={{ padding: "1.25rem", fontSize: "0.875rem", lineHeight: 1.6, fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>{`context="""Customer ID: cust_123
Order Amount: $150
Reason: Product damaged
Customer Tier: premium"""`}</pre>
                    </div>
                  </div>

                  <div>
                    <h3 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>3. Use Descriptive Agent IDs</h3>
                    <p style={{ marginBottom: "0.75rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Be specific about what each agent does:</p>
                    <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                      {["customer-support-refunds", "content-moderator-posts", "transaction-fraud-detector"].map((id, i) => (
                        <li key={i} style={{ paddingLeft: "1rem", borderLeft: "2px solid rgba(13,13,11,0.1)", color: "#4a4a47", fontSize: "0.9375rem" }}>
                          <code style={{ fontFamily: "'Geist Mono', monospace", background: "#0d0d0b", color: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem" }}>{id}</code>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div>
                    <h3 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>4. Monitor Autonomy Trends</h3>
                    <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                      <li>Initial deployments: 20-40% autonomy is normal</li>
                      <li>Well-trained agents: 70-90% autonomy</li>
                      <li>Goal: Increase autonomy while maintaining quality</li>
                    </ul>
                  </div>
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* Download CTA */}
            <Reveal>
              <div style={{ padding: "3rem", borderRadius: "0.5rem", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)", textAlign: "center" }}>
                <h3 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "1rem", color: "#f7f7f5" }}>Want the Complete Guide?</h3>
                <p style={{ fontSize: "1.0625rem", marginBottom: "2rem", color: "#9a9a97" }}>
                  Download the full documentation as markdown including API reference, error handling, troubleshooting, security best practices, and more.
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
                    cursor: "pointer",
                    transition: "all 0.2s ease"
                  }}
                  onMouseOver={(e) => {
                    e.currentTarget.style.background = "#ffffff";
                  }}
                  onMouseOut={(e) => {
                    e.currentTarget.style.background = "#f7f7f5";
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
