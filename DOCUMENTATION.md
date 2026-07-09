# Signal Documentation

## Overview

Signal is a human-in-the-loop decision framework for AI agents. It allows you to build autonomous agents that escalate critical decisions to humans, learn from those decisions, and progressively become more autonomous over time.

### Key Features

- **Smart Escalations**: Agents automatically escalate uncertain decisions to humans
- **Rule Learning**: Convert human decisions into reusable rules for similar situations
- **Progressive Autonomy**: Track how autonomous your agents become over time
- **Dashboard Management**: Web interface for reviewing decisions and managing rules
- **Real-time Monitoring**: See agent decisions as they happen
- **Context Validation**: Intelligent warnings about missing fields and normalization
- **Auto-Enrichment**: Automatically adds environment metadata to context
- **Dev Mode**: Enhanced debugging with detailed logging
- **Health Monitoring**: Proactive alerts for stale rules and pending escalations

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

### Activity Tab

The Activity tab provides a chronological timeline of all agent activity, including policy checks, escalations, and rule changes.

#### Activity Types

Each activity is labeled and color-coded:

- **Auto-handled** (green): Decisions automatically resolved by existing rules
  - Shows for both policy checks and auto-resolved escalations
  - Displays the matched rule condition and action
  - Indicates successful automation
- **Checked** (neutral): Policy checks where no rule matched
  - Shows the action that was checked
  - Displays the reasoning (typically "No applicable rule found")
- **Escalated** (warning/yellow): Escalations waiting for human decision
  - Shows the escalation question
  - Remains until resolved
- **Resolved** (neutral): Escalations manually resolved by a human
  - Shows the human decision and reasoning
  - Distinguished from auto-resolved escalations
- **Rule created/updated** (success): Changes to your rule set

#### Features

- **Search**: Search across activity kinds, titles, summaries, and rule details
- **Filter by Kind**: Filter to show only specific activity types
- **Auto-refresh**: Updates every 7 seconds automatically
- **Rule Links**: Click "View rule" to jump to rule details
- **Expandable Details**: Click "Details" to see full context as formatted JSON
- **Auto-resolved Badge**: Auto-resolved escalations display a green badge

#### Understanding Auto-Resolution

When you see "Auto-handled" with an escalation:
- The escalation was created but immediately resolved by a matching rule
- No human intervention was required
- The agent received the decision instantly
- Your autonomy score increased

This is different from "Checked" activities, which use the `/v1/check` endpoint and don't create escalations.

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
from signalops import Field

signalops.configure(
    api_key="sk_live_your_api_key_here",
    base_url="https://your-signal-deployment.com",  # Optional
    dev_mode=False,  # Optional: Enable debug logging
    auto_enrich=True  # Optional: Auto-add environment metadata (default: True)
)

# Or use Signal class directly with schema
from signalops import Signal

signal = Signal(
    api_key="sk_live_...",
    schema=[
        Field("vulnerability.cvss.score", type="number"),
        Field("dependency.direct", type="boolean"),
    ],
    dev_mode=True,
    auto_enrich=True
)

# Then use signal.escalate() instead of signalops.escalate()
result = await signal.escalate(...)
```

**Parameters:**

- `api_key` (str): Your Signal API key
- `base_url` (str, optional): Custom deployment URL
- `dev_mode` (bool, optional): Enable debug logging for development (default: False)
- `auto_enrich` (bool, optional): Automatically add timestamp and environment to context (default: True)
- `schema` (list[Field], optional): Define your context schema for consistent normalization (v0.2.2+)

### Schema Definition (New in v0.2.2)

**Define your context schema upfront to ensure consistent field naming and types:**

```python
from signalops import Signal, Field

signal = Signal(
    api_key="sk_live_...",
    schema=[
        Field("vulnerability.cvss.score", type="number"),
        Field("vulnerability.severity", type="string"),
        Field("dependency.direct", type="boolean"),
        Field("dependency.ecosystem", type="string"),
        Field("cisa.kev.known.ransomware.campaign.use", type="boolean"),
    ]
)

# All field variations automatically map to canonical names:
result = await signal.escalate(
    agent_id="security-scanner",
    question="Should this vulnerability be escalated?",
    context={
        "cvss.score": 10,           # → vulnerability.cvss.score
        "cvssScore": 10,            # → vulnerability.cvss.score
        "CVSS Score": 10,           # → vulnerability.cvss.score
        "direct.dependency": "yes", # → dependency.direct (coerced to True)
    }
)
```

**Field Types:**
- `"string"` - Text values
- `"number"` - Floating point numbers
- `"integer"` - Whole numbers
- `"boolean"` - True/False values
- `"array"` - Lists of values
- `"object"` - Nested dictionaries

**Benefits:**
- ✅ No duplicate fields from naming variations
- ✅ Consistent types across all contexts
- ✅ Reliable rule matching
- ✅ Automatic type coercion (e.g., "yes" → True, single value → [array])

**Field Variation Mapping:**

Signal automatically generates and recognizes these variations for `"vulnerability.cvss.score"`:
- `vulnerability.cvss.score` (exact)
- `vulnerability_cvss_score` (underscore)
- `vulnerabilityCvssScore` (camelCase)
- `cvss.score` (partial path)
- `cvss_score` (partial underscore)
- `cvssScore` (partial camelCase)
- `score` (last part only)

### escalate()

Escalate a decision to Signal. **Automatically checks existing rules first** - if a rule matches, returns immediately with the decision. If no rule matches, waits for human review:

```python
result = await signalops.escalate(
    agent_id="your-agent-identifier",
    question="Should I perform this action?",
    context={"key": "value"},  # Prefer dict for schema normalization
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
  - **Prefer a dictionary** so Signal can normalize fields using your schema
  - Example: `{"amount": 150, "customer_tier": "premium"}`
  - If no schema defined, uses built-in field aliases
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
  - `True`: A matching rule was found and applied immediately (no waiting)
  - `False`: Required human review and decision

**Auto-Resolution:**

When `escalate()` is called, Signal first checks all active rules. If a rule matches the context:
- Returns **immediately** (typically < 1 second)
- Sets `auto_resolved=True`
- Provides the rule's decision in `decision`
- Does NOT create a pending escalation in the Review queue
- Increases your autonomy score

If no rule matches:
- Creates a pending escalation
- Waits for human decision (up to `timeout_seconds`)
- Sets `auto_resolved=False` when decision is made

**Context Warnings:**

Signal automatically validates your context and displays warnings via Python's logging module. These warnings include:

- Field normalization (e.g., "user_email" → "email")
- Missing important fields that appear in 80%+ of similar escalations
- Type mismatches with example values

Example warning:
```
WARNING: Context validation: Missing field 'customer_tier' - this field appears in 80%+ of similar escalations (example: premium)
```

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

- `result` (str): The decision - "proceed", "block", "reject", "deny", "escalate", "modify", etc.
- `rule_id` (str|None): ID of the matching rule (None if no rule matched)
- `reasoning` (str): Explanation for the result
- `modification` (dict|None): Modification parameters if result is "modify"
- `context_warnings` (list[str]): List of validation warnings about the context

**When to use check() vs escalate():**

Use **`escalate()`** when:
- You want decisions to learn over time (creates learning data)
- You're okay with waiting for human review when no rule exists
- You want the escalation to appear in the dashboard for analysis
- Most common use case - handles both auto-resolution AND human fallback

Use **`check()`** when:
- You only want to check existing rules (no escalation if no rule)
- You need to handle the "no rule" case yourself with custom logic
- You want to avoid creating escalation records
- You need lower latency for rule-only checks

**Example:**

```python
# ✅ RECOMMENDED: Use escalate() - handles both cases
result = await signalops.escalate(
    agent_id="refund-bot",
    question="Should I approve this refund?",
    context={"amount": 150, "customer_tier": "premium"}
)
# Auto-resolves if rule exists, OR waits for human if not
proceed = result.decision == "approve"

# ⚠️ ONLY if you need rule-only checking with custom fallback:
check_result = await signalops.check(
    action="approve_refund",
    context={"amount": 150, "customer_tier": "premium"},
    agent_id="refund-bot"
)
if check_result.result in ("proceed", "approve"):
    proceed = True
elif check_result.result in ("block", "reject"):
    proceed = False
else:
    # No rule exists - you must handle this yourself
    proceed = amount < 50  # Custom fallback logic
```

**Note:** Since `escalate()` now auto-checks rules first, you rarely need to use `check()` before `escalate()`.

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

## Advanced Features

### Dev Mode

Enable dev mode during development to see detailed logging of all Signal operations:

```python
import signalops
import logging

# Configure logging to see Signal debug output
logging.basicConfig(level=logging.DEBUG)

# Enable dev mode
signalops.configure(
    api_key="sk_live_...",
    dev_mode=True
)

# Now you'll see debug logs for all operations
result = await signalops.escalate(...)
# DEBUG: Creating escalation: agent_id=support-bot, action=approve_refund
# DEBUG: Context: {"customer_tier": "premium", "amount": 150}...
# WARNING: Context validation: Missing field 'email' - appears in 80%+ of escalations
# DEBUG: Received 1 context warnings from API
```

Dev mode is automatically disabled in production and only logs to stdout/stderr.

### Auto-Enrichment

By default, Signal automatically enriches your context with environment metadata:

```python
# You send:
context = {"customer_id": "cust_123", "amount": 150}

# Signal automatically adds:
{
    "customer_id": "cust_123",
    "amount": 150,
    "_signal_timestamp": "2026-07-07T18:30:00Z",
    "_signal_environment": "production"  # from ENVIRONMENT env var
}
```

This helps with debugging and provides additional context for rule matching. To disable:

```python
signalops.configure(
    api_key="sk_live_...",
    auto_enrich=False  # Disable automatic enrichment
)
```

### Schema-First Normalization (v0.2.2)

**The Problem:**
Without a schema, sloppy field names create duplicate fields in your database:
- Agent 1 sends `{"cvss.score": 10}` → creates "cvss.score" field
- Agent 2 sends `{"vulnerability.cvss.score": 10}` → creates DIFFERENT "vulnerability.cvss.score" field
- Rules don't match across agents!

**The Solution:**
Define your schema once, and Signal normalizes ALL variations to canonical names:

```python
from signalops import Signal, Field

# Define schema once
signal = Signal(
    api_key="sk_live_...",
    schema=[
        Field("vulnerability.cvss.score", type="number"),
        Field("vulnerability.cves", type="array"),
        Field("dependency.direct", type="boolean"),
    ]
)

# ALL these map to vulnerability.cvss.score:
await signal.escalate(
    context={
        "cvss.score": 10,      # ✓ Normalized
        "cvssScore": 10,       # ✓ Normalized
        "CVSS Score": 10,      # ✓ Normalized
    }
)
```

**Automatic Type Coercion:**

| Input | Expected Type | Output |
|-------|--------------|--------|
| `"yes"` | `boolean` | `True` |
| `"Known"` | `boolean` | `True` |
| `10` | `array` | `[10]` |
| `"CWE-20"` | `array` | `["CWE-20"]` |
| `10` | `string` | `"10"` |

**Schema Syncing:**
- Schema automatically synced to server on first escalate()/check() call
- Server stores canonical fields and generates all aliases
- User-defined fields override learned fields

### Context Validation

Signal validates your context and provides warnings:

**Field Normalization:**
```python
# With schema: Field variations normalized to canonical names
# Without schema: Uses built-in aliases (e.g., user_email → email)
# Warning: "Normalized context field 'cvss.score' to 'vulnerability.cvss.score'"
```

**Missing Schema Fields:**
```python
# With schema: Warns if field not in schema
# Warning: "Field 'unknown_field' not found in schema. Skipping."
```

**Type Mismatches:**
```python
# Automatic coercion happens, but warns if types don't match
# Warning: "Field 'direct.dependency' expected type 'boolean', got 'string', coerced to True"
```

These warnings help you maintain consistent context across your agents and improve rule matching.

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

### Latest Release (July 2026)

**Robustness & Developer Experience:**
- Context validation with intelligent warnings
- Missing field detection (learns from 80%+ occurrence in escalations)
- Automatic field normalization (e.g., user_email → email)
- Type validation with example values
- Dev mode with detailed debug logging
- Auto-enrichment of context with timestamps and environment
- Health check endpoint (`/admin/health`) for monitoring
- Rule quality validation endpoint for confidence scoring

**SDK Enhancements:**
- Python SDK: `dev_mode` and `auto_enrich` parameters
- TypeScript SDK: `devMode` and `autoEnrich` options
- Automatic warning display via logging
- Better error messages with actionable suggestions

**Dashboard:**
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
