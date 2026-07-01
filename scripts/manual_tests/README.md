# Manual Test Scripts

Set these once per terminal:

```bash
export SIGNAL_TEST_BASE_URL="https://signal-omega-tan.vercel.app"
export SIGNAL_TEST_API_KEY="sk_live_..."
```

Run from the project root.

## 1. Slack Approve / Reject

```bash
python scripts/manual_tests/slack_approve_flow.py --expect approve
python scripts/manual_tests/slack_approve_flow.py --expect reject
```

Follow the script prompt and click the matching Slack button.

## 2. Rule Proposal Edit Flow

```bash
python scripts/manual_tests/rule_edit_flow.py
```

The script will pause for:

1. Approve escalation.
2. Click `Yes, make it a rule`.
3. Click `Edit rule` and submit the printed edit instruction.
4. Click `Approve rule`.

## 3. Similar Past Decisions

```bash
python scripts/manual_tests/similar_decisions.py
```

Approve the first Slack card. The script creates a second similar escalation and verifies the backend similarity result. You still need to visually confirm the second Slack card shows `Similar past decisions`.

## 4. Semantic Conflict Detection

```bash
python scripts/manual_tests/conflict_detection.py
```

The script will pause for:

1. Approve the first escalation.
2. Click `Yes, make it a rule`.
3. Approve the first proposed rule.
4. Reject the second escalation.
5. Click `Yes, make it a rule`.

It verifies a `rule_conflicts` row and asks you to visually confirm the Slack warning.

## 5. Webhook Delivery

Create a webhook.site URL, then run:

```bash
python scripts/manual_tests/webhook_events.py \
  --url "https://webhook.site/<your-id>" \
  --secret "manual-test-secret"
```

The script temporarily registers the webhook, triggers `escalation.created`, waits for you to approve the Slack card to trigger `escalation.resolved`, then automatically triggers `rule.created` and `rule.triggered`. It restores the previous webhook settings unless you pass `--keep-webhook`.

## 6. Verify Webhook Signature

Copy the raw webhook body and `X-Signal-Signature` header from webhook.site:

```bash
python scripts/manual_tests/verify_webhook_signature.py \
  --secret "manual-test-secret" \
  --header "t=...,v1=..." \
  --body-file /path/to/raw-body.json
```

For small payloads, you can use `--body '{"event":"..."}'` instead of `--body-file`.
