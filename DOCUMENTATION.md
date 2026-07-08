# Signal Documentation

## Overview

Signal is a human-in-the-loop decision framework for AI agents. It allows you to build autonomous agents that escalate critical decisions to humans, learn from those decisions, and progressively become more autonomous over time.

### Key Features

- **Smart Escalations**: Agents automatically escalate uncertain decisions to humans
- **Rule Learning**: Convert human decisions into reusable rules for similar situations
- **Progressive Autonomy**: Track how autonomous your agents become over time
- **Dashboard Management**: Web interface for reviewing decisions and managing rules
- **Real-time Monitoring**: See agent decisions as they happen

---

## Getting Started

### 1. Create Your Account

1. Visit the Signal dashboard at your deployment URL
2. Sign up with your email address
3. You'll receive a confirmation email

### 2. Set Up Your Organization

Navigate to **Settings** to configure your workspace:

1. **Create Organization**: Enter your organization name and create your workspace
2. **Start Subscription**: Set up billing (if required for your deployment)
3. **Generate API Key**: Click "Generate new API key" to create your first key
   - Copy and save this key securely - it's only shown once
   - The key starts with `sk_live_`

### 3. Install the SDK

```bash
pip install signalops
```

### 4. Integrate Signal into Your Agent

```python
import signalops

# Configure once (optional - can also use SIGNALOPS_API_KEY env var)
signalops.configure(api_key="sk_live_your_api_key_here")

# Escalate a decision to Signal
result = await signalops.escalate(
    agent_id="customer-support-bot",
    question="Should I issue a refund?",
    context=(
        "A customer is requesting a refund.\n\n"
        "Customer ID: cust_123\n"
        "Order Amount: $150\n"
        "Reason: Product arrived damaged\n"
        "Customer Tier: premium\n"
        "Days Since Purchase: 3"
    ),
    metadata={
        "customer_id": "cust_123",
        "order_amount": 150,
        "customer_tier": "premium",
        "days_since_purchase": 3
    }
)

# Use the decision
if result.decision in ["approve", "yes"]:
    issue_refund()
else:
    deny_refund()
```

Note: Signal uses async/await, so your function must be async.

---

## Dashboard Guide

### Overview Tab

The Overview tab shows your agent's autonomy metrics:

- **Total Agent Decisions Today**: All decisions made by your agents
- **Handled Automatically**: Decisions resolved using existing rules
- **Escalations Today**: Decisions that required human review
- **Autonomy Score**: Percentage of decisions handled automatically

**Autonomy Trend Table** shows daily metrics over time to track improvement.

**Suggestions** displays AI-generated ideas for consolidating similar rules.

**Active Rules** shows your most-used rules with trigger counts.

**Recent Escalations** displays the latest decisions requiring human review.

---

### Review Tab

The Review tab is where you make decisions on escalated requests. The workflow is structured in clear stages:

#### Stage 1: Decision

When an agent escalates a decision to you:

- **Context**: View structured information about the situation
  - Field-value pairs are displayed in a clean grid format
  - Example: "Amount: $150", "Customer tier: premium"
- **Similar Past Decisions**: See how you handled similar situations before
- **Actions**: Click **Approve** or **Reject**

#### Stage 2: Scope

After making a decision, choose how to apply it:

- **Create a Rule**: Your decision will automatically apply to similar future situations
- **One-time Only**: Just for this specific case

#### Stage 3: Review Rule

If you chose to create a rule, review the AI-generated rule:

- **WHEN**: The condition that triggers this rule
- **DO**: The action to take when triggered
- **Conflict Warnings**: If this rule conflicts with existing rules, you'll see an amber warning
  - You must edit the rule before approving when conflicts exist
- **Actions**:
  - **Approve rule**: Accept the rule as-is (disabled if conflicts exist)
  - **Edit rule**: Describe changes you want to make
  - **Discard**: Delete this proposed rule

#### Edit Mode

When editing a rule:

- The current rule is displayed for reference
- Enter instructions describing your desired changes
- Click **Update rule** to regenerate the rule
- Click **Cancel** to return without changes

#### Features

- **Auto-refresh**: New decisions appear automatically every 5 seconds
- **In-context Loading**: "Working..." messages appear next to the buttons you click
- **No Manual Refresh**: Background polling happens silently

---

### Rules Tab

The Rules tab displays all your approved rules in a visual card format.

#### Rule Cards

Each rule shows:

- **Header**:
  - Status badge (Active, Paused, Pending)
  - Confidence level (High, Medium, Low)
  - Trigger count
  - Pause/Activate and Delete buttons
- **Main Content**:
  - **WHEN**: The condition that triggers this rule
  - **→**: Visual arrow separator
  - **DO**: The action taken when triggered
- **Footer**:
  - Last triggered timestamp
  - Created date

#### Search and Filters

- **Search Bar**: Type to search rule conditions or actions in real-time
- **Status Filter**: Filter by Active, Paused, Pending Approval, or Pending Edit
- **Confidence Filter**: Filter by High, Medium, or Low confidence
- **Clear Filters**: Reset all filters at once

#### Bulk Actions

- Click checkboxes to select multiple rules
- When rules are selected, you'll see:
  - Count of selected rules
  - **Delete selected** button
  - **Select all** checkbox (selects all filtered results)

#### Clicking a Rule

Click any rule card to view detailed information including:
- Full rule logic
- Trigger history
- Policy compliance checks
- Metadata

---

### Escalations Tab

View the complete history of all agent escalations.

#### Table Columns

- **Time**: When the escalation occurred
- **Agent**: Agent ID that made the escalation
- **Context**: Brief summary (click to expand full details)
- **Status**: Resolved or Pending
- **Decision**: Your choice (Approve/Reject)
- **Rule Created**: Whether a rule was generated from this decision

#### Expandable Details

Click any row to expand and see:

- **Full Context**: Complete information about the decision
- **Metadata**: Raw JSON data associated with the escalation
- **Rule Details**: If a rule was created, view its condition and action

#### Search and Filters

- **Search Bar**: Search across context or agent ID
- **Status Filter**: Filter by Resolved or Pending
- **Decision Filter**: Filter by Approve or Reject
- **Rule Created Filter**: Filter by Yes or No
- **Clear Filters**: Reset all filters

---

### Settings Tab

Configure your organization and manage access.

#### Organization Setup

If you don't have an organization yet:

1. **Create Workspace**: Enter organization name
2. **Start Subscription**: Complete billing setup
3. **Generate API Keys**: Create keys for your agents

#### Switch Organizations

Use the dropdown to switch between organizations you're a member of.

#### API Key Management

- **View Existing Keys**: See all keys with their prefixes (e.g., `sk_live_abc...`)
- **Generate New Key**: Create additional API keys
  - Copy the full key immediately - it's only shown once
  - Keys are stored securely as SHA256 hashes
- **Security**: Never share your API keys publicly

---

## SDK Reference

### configure()

Configure Signal globally (optional - you can also set `SIGNALOPS_API_KEY` environment variable):

```python
import signalops

signalops.configure(
    api_key="sk_live_your_api_key_here",
    base_url="https://your-signal-deployment.com"  # Optional
)
```

### escalate()

Escalate a decision to Signal and wait for human review:

```python
result = await signalops.escalate(
    agent_id="your-agent-identifier",
    question="Should I perform this action?",
    context="Description of the situation with relevant details",
    metadata={"key": "value"},  # Optional structured data
    action="action_name",  # Optional action identifier
    timeout_seconds=3600,  # Optional, default 3600
    poll_interval_seconds=3  # Optional, default 3
)
```

**Parameters:**

- `agent_id` (str): Unique identifier for your agent
- `question` (str): Clear description of what decision is needed
- `context` (dict or str): Context for the situation
  - Prefer a dictionary so Signal can normalize fields before matching rules
  - Example: `{"amount": 150, "customer_tier": "premium"}`
- `metadata` (dict, optional): Additional structured data (stored but not displayed prominently)
- `action` (str, optional): Action identifier for this decision type
- `timeout_seconds` (int, optional): How long to wait for a decision (default: 3600)
- `poll_interval_seconds` (int, optional): Polling frequency (default: 3)
- `api_key` (str, optional): Override configured API key
- `base_url` (str, optional): Override configured base URL

**Returns:**

An `EscalationResult` object with:

- `decision` (str): The decision made ("approve", "reject", etc.)
- `rule_id` (str|None): ID of the rule that made this decision (if auto-resolved)
- `auto_resolved` (bool): Whether this was resolved by a rule without human review

### check()

Check if an action should be allowed based on existing rules (without escalating):

```python
result = await signalops.check(
    action="action_name",
    context={"key": "value"},
    agent_id="your-agent-identifier"
)
```

**Parameters:**

- `action` (str): Action identifier to check
- `context` (dict): Structured data about the situation
- `agent_id` (str): Unique identifier for your agent
- `api_key` (str, optional): Override configured API key
- `base_url` (str, optional): Override configured base URL

**Returns:**

A `CheckResult` object with:

- `result` (str): "allow", "block", or "escalate"
- `rule_id` (str|None): ID of the matching rule (if any)
- `reasoning` (str): Explanation for the result
- `modification` (dict|None): Any suggested modifications to the action

### Context Best Practices

Structure your context for readability in the dashboard:

```python
# Good - field: value pairs
context = (
    "User ID: user_12345\n"
    "Request Type: Password Reset\n"
    "Account Age: 30 days\n"
    "Previous Resets: 0\n"
    "IP Location: New York, US"
)

# Also good - using newlines to separate
context = """
User ID: user_12345
Request Type: Password Reset
Account Age: 30 days
Previous Resets: 0
IP Location: New York, US
"""

# Less optimal - paragraph format
context = "User user_12345 is requesting a password reset. Account is 30 days old with 0 previous resets from New York, US."
```

The field: value format displays as a clean grid in the dashboard, while paragraph format shows as plain text.

Use the `metadata` parameter for structured data you want to store but don't need prominently displayed.

---

## Use Cases

### Customer Support Automation

```python
import signalops

async def handle_refund_request(order, customer, refund_reason):
    result = await signalops.escalate(
        agent_id="support-bot",
        question="Should I approve this refund request?",
        context=(
            f"Order Amount: ${order.total}\n"
            f"Days Since Purchase: {days_ago}\n"
            f"Reason: {refund_reason}\n"
            f"Customer Lifetime Value: ${customer.ltv}\n"
            f"Previous Refunds: {customer.refund_count}"
        ),
        metadata={
            "order_id": order.id,
            "customer_id": customer.id
        }
    )

    if result.decision == "approve":
        process_refund(order)
    else:
        send_refund_denial(customer)
```

### Content Moderation

```python
async def moderate_content(content, flag, user):
    result = await signalops.escalate(
        agent_id="content-moderator",
        question="Should this content be removed?",
        context=(
            f"Content Type: {content.type}\n"
            f"Flag Reason: {flag.reason}\n"
            f"User Reputation Score: {user.reputation}\n"
            f"Previous Violations: {user.violations}\n"
            f"Community Reports: {flag.report_count}"
        ),
        metadata={
            "content_id": content.id,
            "user_id": user.id,
            "flag_id": flag.id
        }
    )

    if result.decision == "approve":
        remove_content(content)
```

### Financial Approvals

```python
async def approve_transaction(transaction, account, merchant):
    result = await signalops.escalate(
        agent_id="transaction-monitor",
        question="Should this transaction be approved?",
        context=(
            f"Transaction Amount: ${transaction.amount}\n"
            f"Account Balance: ${account.balance}\n"
            f"Merchant Category: {merchant.category}\n"
            f"Transaction Location: {transaction.location}\n"
            f"Risk Score: {risk_model.score}"
        ),
        metadata={
            "transaction_id": transaction.id,
            "account_id": account.id
        }
    )

    return result.decision == "approve"
```

### HR Automation

```python
async def approve_leave_request(request, employee, coverage_status):
    result = await signalops.escalate(
        agent_id="hr-assistant",
        question="Should this leave request be approved?",
        context=(
            f"Leave Type: {request.type}\n"
            f"Duration: {request.days} days\n"
            f"Remaining Balance: {employee.leave_balance} days\n"
            f"Team Coverage: {coverage_status}\n"
            f"Notice Period: {notice_days} days"
        ),
        metadata={
            "request_id": request.id,
            "employee_id": employee.id
        }
    )

    return result.decision == "approve"
```

---

## Best Practices

### 1. Clear Questions

Write questions that can be answered with approve/reject:

✅ Good: "Should I issue a refund for this order?"
❌ Bad: "What should I do about this customer?"

### 2. Structured Context

Provide context as field: value pairs for dashboard readability:

```python
context = (
    "Field Name: value\n"
    "Another Field: another value"
)
```

### 3. Consistent Agent IDs

Use consistent, descriptive agent identifiers:

- `customer-support-refunds`
- `content-moderator-posts`
- `transaction-fraud-detector`

This helps with filtering and analytics.

### 4. Appropriate Escalations

Only escalate decisions that truly need human judgment:

- High-value transactions
- Edge cases not covered by rules
- Situations requiring empathy or nuance
- New scenarios your agent hasn't seen before

### 5. Regular Rule Review

Periodically review your rules in the Rules tab:

- Pause rules that are no longer relevant
- Merge similar rules (use the Suggestions feature)
- Update confidence levels based on performance

### 6. Monitor Autonomy Trends

Track your autonomy score over time:

- Initial deployments: 20-40% autonomy is normal
- Well-trained agents: 70-90% autonomy
- Goal: Increase autonomy while maintaining quality

---

## Security

### API Key Management

- Store API keys in environment variables, never in code
- Use different keys for development and production
- Rotate keys periodically
- Revoke keys immediately if compromised

### Access Control

- Only invite trusted team members to your organization
- Use the Settings tab to manage organization access
- Review escalation history for unusual patterns

---

## Troubleshooting

### "No organization selected" error

**Solution**: Go to Settings and create or select an organization, then generate an API key.

### Agent escalations not appearing in dashboard

**Check**:
1. API key is correct
2. Organization is selected in dashboard
3. Base URL matches your deployment
4. Check browser console for errors

### Rules not triggering

**Check**:
1. Rule status is "Active" (not Paused)
2. Rule condition matches your context format exactly
3. Review rule confidence level

### Search not finding results

**Try**:
- Clear all filters first
- Check for typos in search query
- Search is case-insensitive but requires partial matches

---

## Support

For questions, issues, or feature requests:

1. Check this documentation
2. Review the dashboard Overview tab for metrics
3. Contact your Signal administrator
4. Report issues at your Signal support channel

---

## Changelog

### Latest Release

- Card-based rule visualization
- Real-time search and filtering on Rules and Escalations
- Structured context display with field-value pairs
- Auto-refresh on Review queue
- Button-specific loading states
- User info in sidebar footer
- Improved mobile responsiveness

---

## Example Workflow

Here's a complete example of Signal in action:

### 1. Agent Makes Request

```python
import signalops

signalops.configure(api_key="sk_live_...")

result = await signalops.escalate(
    agent_id="refund-bot",
    question="Should I approve this refund?",
    context=(
        "Amount: $75\n"
        "Reason: Wrong size ordered\n"
        "Customer Tier: Gold\n"
        "Order Age: 5 days"
    )
)
```

### 2. No Matching Rule Exists

Signal escalates to human (shows in Review tab).

### 3. Human Reviews

You see the structured context and decide to **Approve**.

### 4. Create Rule

You choose "Create a rule" for similar situations.

### 5. AI Generates Rule

```
WHEN: Customer tier is Gold AND order age is less than 30 days AND amount is less than $100
DO: Approve refund
```

### 6. You Review

Rule looks good, you click **Approve rule**.

### 7. Next Time

Another Gold customer requests a $60 refund after 3 days:

```python
result = await signalops.escalate(
    agent_id="refund-bot",
    question="Should I approve this refund?",
    context=(
        "Amount: $60\n"
        "Reason: Different issue\n"
        "Customer Tier: Gold\n"
        "Order Age: 3 days"
    )
)
# Returns immediately: result.decision="approve", result.auto_resolved=True
```

Your autonomy score increases!

---

## Metrics Explained

### Total Agent Decisions

Sum of auto-handled decisions and escalations today. Every decision is either handled automatically by a rule or escalated to a human, so:

```
Total Decisions = Auto-Handled + Escalations
```

### Auto-Handled

Decisions resolved by existing rules without human intervention.

### Escalations

Decisions that required human review (no matching rule found).

### Autonomy Score

```
Autonomy Score = (Auto-Handled / Total Decisions) × 100
```

Higher scores mean your agent is learning and handling more decisions independently.

---

## Next Steps

1. ✅ Generate your API key in Settings
2. ✅ Install the SDK: `pip install signalops`
3. ✅ Integrate `await signalops.escalate()` into your agent
4. ✅ Review your first escalation in the Review tab
5. ✅ Create your first rule
6. ✅ Monitor autonomy growth in Overview

Welcome to Signal! Your agents are about to get a lot smarter.
