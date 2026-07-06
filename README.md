# Signal

Signal is an operational intelligence loop for AI agents. Agents escalate uncertain decisions to a human in Slack, the human responds, Signal can turn that decision into a reusable rule, and future agent calls are checked against saved rules.

## Stack

- Python 3.12
- FastAPI and Uvicorn
- SQLAlchemy 2.0 async with asyncpg
- Alembic migrations
- Supabase hosted Postgres
- Redis pub/sub for live escalation responses
- Slack interactivity through Slack Block Kit
- Anthropic tool use for rule extraction
- Installable async Python SDK and TypeScript SDK

## Supabase Setup

Create a Supabase project and use its Session Pooler connection string as `DATABASE_URL`. This is the best fit for Vercel because the direct Supabase host can require IPv6 networking.

Use the SQLAlchemy asyncpg form:

```text
postgresql+asyncpg://postgres.<project-ref>:<password>@<region>.pooler.supabase.com:5432/postgres?ssl=require
```

In Supabase, open **Connect** and choose **Session Pooler**. Keep the pooler port as `5432`; do not use the transaction pooler URL for this MVP.

The API runs Alembic migrations on startup, so the Supabase database will get these tables automatically:

- `escalations`
- `rules`
- `policy_check_log`
- `organizations`
- `api_keys`
- `rule_conflicts`

## Environment

Copy the example file and fill in your real values:

```bash
cp .env.example .env
```

Required variables:

```text
DATABASE_URL=postgresql+asyncpg://postgres.<project-ref>:<password>@<region>.pooler.supabase.com:5432/postgres?ssl=require
ANTHROPIC_API_KEY=sk-ant-...
VOYAGE_API_KEY=pa-...
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_CHANNEL_ID=C0123456789
API_BASE_URL=https://your-ngrok-url.ngrok.io
REDIS_URL=redis://localhost:6379/0
```

For Upstash, you can use the REST env vars instead of `REDIS_URL`; Signal derives the TLS Redis connection internally:

```text
UPSTASH_REDIS_REST_URL=https://your-instance.upstash.io
UPSTASH_REDIS_REST_TOKEN=...
```

## Lifecycle Management

Signal runs two lifecycle jobs:

- Daily at 2am: stale and unreliable rule review
- Mondays at 3am: consolidation suggestions for highly similar rules

You can run them manually:

```bash
curl -X POST "$API_BASE_URL/admin/lifecycle/run-staleness" \
  -H "Authorization: Bearer sk_live_..."

curl -X POST "$API_BASE_URL/admin/lifecycle/run-consolidation" \
  -H "Authorization: Bearer sk_live_..."
```

For test data that is not older than seven days, add `?include_new_rules=true` to the staleness endpoint.

Pending consolidation suggestions appear on `/dashboard`. Accepting a suggestion creates a merged active rule and archives the two originals.

## Webhooks

Register a webhook URL:

```bash
python api/manage.py set-webhook \
  --org-id <org-id> \
  --url https://example.com/signal-webhook \
  --secret mysecret
```

Signal sends these events:

- `escalation.created`
- `escalation.resolved`
- `rule.created`
- `rule.triggered`

Webhook bodies are signed with `X-Signal-Signature`:

```text
t=<unix_timestamp>,v1=<hmac_sha256>
```

Verify the signature by computing HMAC-SHA256 over `<timestamp>.<raw_body>` with the webhook secret.

`VOYAGE_API_KEY` powers semantic embeddings for similar past decisions and rule conflict detection.

API keys are created in the database and stored as SHA-256 hashes. Generate one after migrations:

```bash
python api/manage.py create-org --name "Acme Corp"
python api/manage.py create-api-key --org-id <org-id> --name "Production"
```

The raw key is shown once. API requests to `/v1/*` must include:

```text
Authorization: Bearer sk_live_...
```

## Slack App Setup

Create a Slack app, install it into your workspace, and add these bot token scopes:

- `chat:write`
- `channels:read`
- `channels:history`
- `groups:read` if you will post into private channels
- `groups:history` if you will post into private channels

Invite the bot to the channel whose ID is in `SLACK_CHANNEL_ID`.

Enable Interactivity & Shortcuts in the Slack app settings and set the Request URL to:

```text
<API_BASE_URL>/slack/interactions
```

Enable Event Subscriptions and set the Request URL to:

```text
<API_BASE_URL>/slack/events
```

Subscribe to this bot event:

```text
message.channels
```

If you use a private channel, also subscribe to:

```text
message.groups
```

For local development, expose the API with ngrok:

```bash
ngrok http 8000
```

Put the ngrok HTTPS URL in both `API_BASE_URL` and the Slack Interactivity Request URL.

## Deploy To Vercel

Vercel hosts the FastAPI app publicly through `api/index.py`. Set these environment variables in Vercel for Production, Preview, and Development:

```text
DATABASE_URL
ANTHROPIC_API_KEY
VOYAGE_API_KEY
SLACK_BOT_TOKEN
SLACK_SIGNING_SECRET
SLACK_CHANNEL_ID
API_BASE_URL
REDIS_URL
UPSTASH_REDIS_REST_URL
UPSTASH_REDIS_REST_TOKEN
```

Set `API_BASE_URL` to your Vercel production URL, for example:

```text
https://signal-your-team.vercel.app
```

Run Supabase migrations once before using the hosted app:

```bash
PYTHONPATH=. alembic -c api/alembic.ini upgrade head
```

Create an org and production API key:

```bash
python api/manage.py create-org --name "Acme Corp"
python api/manage.py create-api-key --org-id <org-id> --name "Production"
```

Then deploy:

```bash
vercel --prod
```

In Slack, enable Interactivity & Shortcuts and set the Request URL to:

```text
https://your-vercel-domain.vercel.app/slack/interactions
```

Also enable Event Subscriptions and set the Request URL to:

```text
https://your-vercel-domain.vercel.app/slack/events
```

Check the public health endpoint:

```bash
curl https://your-vercel-domain.vercel.app/health
```

Expected response:

```json
{"status":"ok"}
```

Open the admin dashboard:

```text
https://your-vercel-domain.vercel.app/dashboard
```

Dashboard pages are served directly by FastAPI with Jinja2 templates:

```text
/dashboard
/dashboard/rules
/dashboard/escalations
/dashboard/rules/<rule_id>
```

The pages are readable without auth for the MVP. Rule pause/archive buttons call the protected API and require a generated `sk_live_...` API key.

## Run Locally

```bash
docker compose up --build
```

Docker Compose starts Redis, runs migrations, then starts the API on port `8000`. The app still uses Supabase for Postgres.

Check health:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## SDK

Install the SDK in editable mode:

```bash
pip install -e ./sdk
```

### Understanding the `context` Parameter

The `context` parameter is **always a string** in the API. There are two recommended formats:

#### Simple String (for basic cases)
```python
context="Customer Jane Smith is requesting a refund on order #1234. Order is 47 days old."
```

#### Structured JSON String (recommended for rule matching)
```python
import json

# ✅ CORRECT - Convert dict to JSON string
context_data = {
    "customer": {
        "name": "Jane Smith",
        "tier": "gold"
    },
    "order": {
        "id": "#1234",
        "age_days": 47,
        "value": 189.00
    }
}
context = json.dumps(context_data)

# ❌ WRONG - Passing dict directly will cause validation error
# context = context_data  # This will fail!
```

**Why use structured JSON?**
- Rules can match specific fields (e.g., `customer.tier == "gold"`)
- More precise than parsing free text
- Easier to debug when rules don't match

### Python SDK Example

```python
import asyncio
import json
from signal_sdk import Signal


async def main():
    signal = Signal(api_key="sk_live_...", base_url="http://localhost:8000")

    # Example 1: Simple string context
    result = await signal.escalate(
        context="Customer Jane Smith is requesting a refund on order #1234. Order is 47 days old.",
        question="Should I approve or reject this refund?",
        agent_id="support-agent",
        metadata={
            "customer_tier": "gold",
            "order_age_days": 47,
            "order_value": 189.00,
        },
    )
    print(f"Decision: {result.decision}")

    # Example 2: Structured JSON context (recommended)
    context_data = {
        "deployment_id": "deploy-007",
        "change_type": "hotfix",
        "author": {
            "email": "alice@company.com",
            "experience": "senior"
        },
        "files_changed": 3,
        "test_coverage": 95.0
    }

    result = await signal.escalate(
        context=json.dumps(context_data),  # Convert to JSON string
        question="Should this deployment be approved?",
        agent_id="deploy-agent",
        metadata={"risk_level": "low"},
    )
    print(f"Decision: {result.decision}")

    # Check against saved rules
    check = await signal.check(
        action="approve_deployment",
        agent_id="deploy-agent",
        context=context_data,  # SDK handles JSON conversion
    )
    print(f"Result: {check.result} - {check.reasoning}")


asyncio.run(main())
```

The Python SDK uses Server-Sent Events for escalations and falls back to polling if streaming is unavailable.

## TypeScript SDK

Build the Node SDK:

```bash
cd sdk-ts
npm install
npm run build
```

### TypeScript SDK Example

```typescript
import { Signal } from "@signal-sdk/node";

const signal = new Signal({
  apiKey: "sk_live_...",
  baseUrl: "http://localhost:8000",
});

// Example 1: Simple string context
const result1 = await signal.escalate({
  context: "Customer Jane Smith is requesting a refund on order #1234.",
  question: "Should I approve or reject this refund?",
  agentId: "support-agent",
  metadata: { customerTier: "gold", orderValue: 189.0 },
});

// Example 2: Structured JSON context (recommended)
const contextData = {
  deployment_id: "deploy-007",
  change_type: "hotfix",
  author: {
    email: "alice@company.com",
    experience: "senior"
  },
  files_changed: 3,
  test_coverage: 95.0
};

// ✅ CORRECT - Convert object to JSON string
const result2 = await signal.escalate({
  context: JSON.stringify(contextData),
  question: "Should this deployment be approved?",
  agentId: "deploy-agent",
  metadata: { riskLevel: "low" },
});

// ❌ WRONG - Passing object directly
// context: contextData  // This will cause a validation error!

// Check against saved rules
const check = await signal.check({
  action: "approve_deployment",
  agentId: "deploy-agent",
  context: contextData,  // SDK handles conversion
});
```

## Verification Checklist

1. `docker compose up --build` starts without errors.
2. `GET http://localhost:8000/health` returns `{"status":"ok"}`.
3. Running the SDK example creates a Slack escalation message.
4. Clicking `Approve` in Slack makes the SDK print `Decision: approve`.
5. Clicking `Yes, make it a rule` triggers Claude extraction and sends a rule proposal.
6. Clicking `Approve rule` activates the saved rule. Verify it in Supabase with `SELECT * FROM rules;`.
7. Running `signal.check()` with matching context returns the saved rule action.
8. Running `signal.check()` with non-matching context returns `proceed`.
