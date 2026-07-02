# Signal Rigorous Testing Plan

This plan covers the full Signal product surface: API, Slack loop, rule extraction, semantic intelligence, dashboard, multi-tenant auth, rate limiting, Redis/SSE, lifecycle management, webhooks, Python SDK, and TypeScript SDK.

## Test Environments

Use three environments:

- Local API with Supabase and Upstash: fast iteration and logs.
- Vercel production: public-hosting verification.
- Isolated QA organization: destructive or noisy tests should use a separate org/API key whenever possible.

Do not use the default org for destructive tests unless the expected behavior is to affect existing real rules.

## Data Strategy

Use prefixed test data:

- Agent id: `qa-agent`
- Context prefix: `[QA]`
- Rule condition prefix where practical: `[QA]`
- Metadata marker: `{ "qa_run_id": "<timestamp-or-uuid>" }`

Clean up or archive QA rules after destructive tests. Avoid running staleness checks repeatedly against production org data because they send Slack messages.

## Master QA Suite

Run the broad one-command suite:

```bash
python -u scripts/master_test.py
```

The master suite creates temporary QA organizations/API keys, verifies core behavior against those isolated orgs, and cleans them up by default.

It automatically covers:

- Health, pgvector schema, dashboard auth boundary, logo asset.
- API key auth, old dev-key rejection, org isolation.
- Policy matching for proceed/block/modify, agent scope, policy logs, trigger counters.
- Rule pause/activate/archive/delete.
- Runtime conflict handling and activation conflict `409` details.
- pgvector similar-rule lookup and similar past decision lookup.
- Escalation creation and polling fallback.
- Override detection, staleness scan, consolidation accept.
- Webhook HMAC signature shape.
- Python `signalops.check()` package API.

Optional deeper checks:

```bash
# Live Voyage/background embedding checks
python -u scripts/master_test.py --with-ai

# Dashboard login, org selection, settings, API-key paywall, logout
SIGNAL_DASHBOARD_EMAIL="you@example.com" \
SIGNAL_DASHBOARD_PASSWORD="password" \
python -u scripts/master_test.py

# Hosted Redis/SSE auto-finalization checks require the local runner to point at the same Redis as the hosted API.
UPSTASH_REDIS_REST_URL="..." \
UPSTASH_REDIS_REST_TOKEN="..." \
python -u scripts/master_test.py

# Stripe webhook simulation and checkout URL creation
python -u scripts/master_test.py --with-stripe-webhook --with-stripe-checkout

# TypeScript SDK build
python -u scripts/master_test.py --with-typescript

# Noisy rate-limit check
python -u scripts/master_test.py --include-rate-limit

# Human Slack/dashboard review checkpoint
python -u scripts/master_test.py --with-manual-review --interactive
```

Use `--strict-skips` when you want CI-like behavior where skipped optional coverage fails the run.

The runner prints a final PASS/FAIL/SKIP/CHECK summary. A normal hosted run may skip Redis/SSE auto-finalization unless local `REDIS_URL`/Upstash env matches production, because otherwise the test runner cannot publish the final event into the API server's Redis channel.

## Automated Smoke Suite

Run:

```bash
SIGNAL_TEST_BASE_URL=https://signal-omega-tan.vercel.app \
SIGNAL_TEST_API_KEY=sk_live_... \
python scripts/smoke_test.py
```

Optional:

```bash
SIGNAL_TEST_COMPLETED_ESCALATION_ID=<responded-escalation-id>
```

The smoke suite verifies:

- Health endpoint.
- Public dashboard pages render.
- Old hardcoded API key is rejected.
- New API key works.
- Admin summary is scoped and returns expected shape.
- Manual lifecycle endpoints are protected and callable.
- SSE returns the correct event format for an already-completed escalation when an id is provided.
- Python SDK `check()` works.
- Webhook signature implementation is valid locally.

## API And Auth Matrix

| Area | Test | Expected |
| --- | --- | --- |
| Health | `GET /health` | `200`, `{"status":"ok"}` |
| Missing auth | `POST /v1/check` without auth | `401` |
| Old dev key | `Bearer sk_dev_changeme` | `401` |
| Valid key | `POST /v1/check` | `200`, valid `CheckResponse` |
| Wrong org data | Access another org escalation/rule id | `404` |
| Invalid payload | Missing required fields | `422` |
| Rate limit | exceed endpoint limit | `429` plus `Retry-After` |

## Escalation Loop

| Test | Expected |
| --- | --- |
| `signal.escalate()` creates escalation | Slack card appears; API returns id/status pending |
| Approve | SDK resolves `decision=approve`; escalation status `responded`; SSE emits response |
| Reject | SDK resolves `decision=reject`; escalation status `responded`; SSE emits response |
| Apply broadly yes | Rule proposal posted |
| Rule edit modal | Edited proposal posts formatted revised rule |
| Rule approve | Rule becomes active |
| Rule discard | Proposed rule removed or ignored |
| Apply broadly no | No rule created |

## Rule Engine

| Test | Expected |
| --- | --- |
| Matching context | `signal.check()` returns rule action and rule id |
| Non-matching context | returns `proceed` and null rule id |
| Paused rule | no longer matches |
| Archived rule | no longer matches |
| Agent scope | only scoped agent matches |
| Override detection | check matches rule, then escalation for same agent/action within 60s increments `override_count` |

## Semantic Intelligence

| Test | Expected |
| --- | --- |
| Escalation embedding | `context_embedding` populated within seconds |
| Rule embedding | `condition_embedding` populated after proposal/approval |
| Similar past decisions | second similar escalation card includes similar decisions |
| Conflict detection | contradictory similar active rule yields Slack warning and `rule_conflicts` row |

## Dashboard

| Page | Test |
| --- | --- |
| `/dashboard` | stats, trend, active rules, recent escalations, suggestions render |
| `/dashboard/rules` | full rule table; pause/archive buttons work with API key |
| `/dashboard/escalations` | expandable rows show context, metadata, rule details |
| `/dashboard/rules/{id}` | rule details, checks, source escalation render |

## Lifecycle Management

| Test | Expected |
| --- | --- |
| Manual staleness | protected endpoint returns counts and sends Slack review warnings |
| Scheduled staleness | 2am job runs without crashing |
| Unreliable rule | `override_count / trigger_count > 20%` and `trigger_count >= 10` is flagged |
| Consolidation | similar active rules produce pending suggestion |
| Accept suggestion | creates merged rule, archives originals, marks suggestion accepted |

## Webhooks

| Event | Trigger | Expected |
| --- | --- | --- |
| `escalation.created` | create escalation | webhook receives signed payload |
| `escalation.resolved` | Slack approve/reject | webhook receives signed payload |
| `rule.created` | approve rule or accept consolidation | webhook receives signed payload |
| `rule.triggered` | matching `signal.check()` | webhook receives signed payload, max once per rule per minute |

Verify `X-Signal-Signature` by computing HMAC-SHA256 over `<timestamp>.<raw_body>` with the org webhook secret.

## SDKs

| SDK | Test |
| --- | --- |
| Python | `check()`, `escalate()` SSE, polling fallback |
| TypeScript | `check()`, `escalate()` SSE, polling fallback, package build |

## Manual Test Checklist

Manual intervention is required for Slack button clicks and external webhook delivery inspection:

1. Run a fresh `signal.escalate()` with `[QA]` context.
2. Confirm Slack card appears.
3. Click Approve; confirm SDK resolves.
4. Click “Yes, make it a rule”; confirm proposed rule appears.
5. Click Edit rule; submit an edit in the modal; confirm revised proposal appears.
6. Click Approve rule; confirm dashboard and `signal.check()` see it.
7. Register a webhook.site URL with `api/manage.py set-webhook`.
8. Trigger escalation/check/rule events and verify webhook.site receives signed payloads.

The scripts under `scripts/manual_tests/` drive these flows and pause at the exact points where you need to click Slack or inspect webhook.site. See `scripts/manual_tests/README.md` for commands.

## Release Gate

A build is releasable only when:

- Smoke suite passes locally and against Vercel.
- At least one fresh full Slack loop passes.
- At least one webhook.site event per webhook type is observed and signature-verified.
- Dashboard pages render after test data is created.
- No API endpoint returns unexpected `500`.
- Rate limit behavior is confirmed on a non-destructive route or isolated org.
