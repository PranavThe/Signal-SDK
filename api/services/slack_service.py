from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from slack_sdk.web.async_client import AsyncWebClient

from api.config import settings
from api.models import Escalation, Rule


def _format_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _chunked(values: list[Any], size: int) -> list[list[Any]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _relative_time(value: datetime | None) -> str:
    if value is None:
        return "unknown time"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    seconds = max(int((datetime.now(UTC) - value).total_seconds()), 0)
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


class SlackService:
    def __init__(self) -> None:
        self.client = AsyncWebClient(token=settings.slack_bot_token)

    async def send_escalation_card(
        self,
        escalation: Escalation,
        similar_decisions: list[dict[str, Any]] | None = None,
        channel_id: str | None = None,
    ) -> dict[str, str]:
        response = await self.client.chat_postMessage(
            channel=channel_id or settings.slack_channel_id,
            text="Agent needs a decision",
            blocks=self._escalation_blocks(
                escalation,
                include_buttons=escalation.status == "pending",
                similar_decisions=similar_decisions,
            ),
        )
        return {"channel": response["channel"], "ts": response["ts"]}

    async def update_escalation_with_decision(self, escalation: Escalation) -> None:
        if not escalation.slack_message_ts:
            return
        await self.client.chat_update(
            channel=escalation.slack_channel_id or settings.slack_channel_id,
            ts=escalation.slack_message_ts,
            text=f"Decision recorded: {escalation.human_decision}",
            blocks=self._escalation_blocks(escalation, include_buttons=False),
        )

    async def update_escalation_auto_resolved(self, escalation: Escalation, rule: Rule) -> None:
        if not escalation.slack_message_ts:
            return
        blocks = self._escalation_blocks(escalation, include_buttons=False)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Auto-resolved by newly approved rule*\n"
                        f"{rule.condition_description} → {rule.action_description}\n\n"
                        f"{escalation.human_reasoning or 'The approved rule matched this escalation exactly.'}"
                    ),
                },
            }
        )
        await self.client.chat_update(
            channel=escalation.slack_channel_id or settings.slack_channel_id,
            ts=escalation.slack_message_ts,
            text="Escalation auto-resolved by new rule",
            blocks=blocks,
        )

    async def send_apply_broadly_followup(self, escalation: Escalation) -> str:
        response = await self.client.chat_postMessage(
            channel=escalation.slack_channel_id or settings.slack_channel_id,
            thread_ts=escalation.slack_message_ts,
            text="Should this decision apply going forward?",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Got it. Should this decision apply in similar situations going forward?",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Yes, make it a rule"},
                            "action_id": "escalation_apply_broadly_yes",
                            "value": str(escalation.id),
                            "style": "primary",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "No, one-time only"},
                            "action_id": "escalation_apply_broadly_no",
                            "value": str(escalation.id),
                        },
                    ],
                },
            ],
        )
        return response["ts"]

    async def acknowledge_one_time_decision(self, escalation: Escalation) -> None:
        await self.client.chat_postMessage(
            channel=escalation.slack_channel_id or settings.slack_channel_id,
            thread_ts=escalation.slack_message_ts,
            text="Understood. This will stay a one-time decision.",
        )

    async def send_rule_proposal(
        self,
        escalation: Escalation,
        rule: Rule,
        conflict_warnings: list[Any] | None = None,
    ) -> str:
        response = await self.client.chat_postMessage(
            channel=escalation.slack_channel_id or settings.slack_channel_id,
            thread_ts=escalation.slack_message_ts,
            text="Proposed rule",
            blocks=self._rule_proposal_blocks(rule, conflict_warnings=conflict_warnings),
        )
        return response["ts"]

    async def send_rule_edit_prompt(self, escalation: Escalation, rule: Rule) -> str:
        response = await self.client.chat_postMessage(
            channel=escalation.slack_channel_id or settings.slack_channel_id,
            thread_ts=escalation.slack_message_ts,
            text="Reply in this thread with the rule change you want.",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "What should change about this rule? Reply in this thread with the edit, "
                            "and I’ll send back an updated proposal for approval."
                        ),
                    },
                }
            ],
        )
        return response["ts"]

    async def open_rule_edit_modal(self, trigger_id: str, rule_id: str) -> None:
        await self.client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "rule_edit_submission",
                "private_metadata": rule_id,
                "title": {"type": "plain_text", "text": "Edit rule"},
                "submit": {"type": "plain_text", "text": "Update rule"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "rule_edit",
                        "label": {"type": "plain_text", "text": "What should change?"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "edit_text",
                            "multiline": True,
                            "placeholder": {
                                "type": "plain_text",
                                "text": "Example: Only apply this when order value is under $250.",
                            },
                        },
                    }
                ],
            },
        )

    async def update_rule_proposal(
        self,
        escalation: Escalation,
        rule: Rule,
        outcome: str,
        conflict_warnings: list[Any] | None = None,
        include_buttons: bool = False,
    ) -> None:
        if not escalation.slack_rule_proposal_ts:
            return
        await self.client.chat_update(
            channel=escalation.slack_channel_id or settings.slack_channel_id,
            ts=escalation.slack_rule_proposal_ts,
            text=f"Rule {outcome}",
            blocks=self._rule_proposal_blocks(
                rule,
                include_buttons=include_buttons,
                outcome=outcome,
                conflict_warnings=conflict_warnings,
            ),
        )

    async def send_rule_review_warning(self, rule: Rule, channel_id: str | None = None, reason: str = "stale") -> str:
        if reason == "unreliable":
            body = (
                "⚠️ *Rule needs review*\n\n"
                "The following rule has been overridden frequently and may be unreliable:\n\n"
                f"\"{rule.condition_description} → {rule.action_description}\"\n\n"
                f"View in dashboard: {settings.api_base_url}/dashboard/rules/{rule.id}"
            )
        else:
            body = (
                "⚠️ *Rule needs review*\n\n"
                "The following rule hasn't been used in 60 days and may be outdated:\n\n"
                f"\"{rule.condition_description} → {rule.action_description}\"\n\n"
                f"View in dashboard: {settings.api_base_url}/dashboard/rules/{rule.id}"
            )

        response = await self.client.chat_postMessage(
            channel=channel_id or settings.slack_channel_id,
            text="Rule needs review",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": body}}],
        )
        return response["ts"]

    def _escalation_blocks(
        self,
        escalation: Escalation,
        include_buttons: bool = True,
        similar_decisions: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": "🤔 Agent needs a decision"}},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Context*\n{escalation.context}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Question*\n{escalation.question}"},
            },
        ]

        fields = [
            {"type": "mrkdwn", "text": f"*{key}*\n{_format_value(value)}"}
            for key, value in escalation.metadata_.items()
        ]
        for chunk in _chunked(fields, 10):
            blocks.append({"type": "section", "fields": chunk})

        if include_buttons and similar_decisions:
            lines = ["*Similar past decisions:*"]
            for decision in similar_decisions:
                score = float(decision.get("similarity") or 0) * 100
                lines.append(
                    f"- {decision.get('human_decision') or 'responded'} — "
                    f"{_relative_time(decision.get('responded_at'))} "
                    f"(similarity: {score:.0f}%)"
                )
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})

        if include_buttons:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "✅ Approve"},
                            "style": "primary",
                            "action_id": "escalation_approve",
                            "value": str(escalation.id),
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "❌ Reject"},
                            "style": "danger",
                            "action_id": "escalation_reject",
                            "value": str(escalation.id),
                        },
                    ],
                }
            )
        elif escalation.human_decision:
            decision_label = "Auto-resolved decision" if escalation.auto_resolved else "Human decision"
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{decision_label}*\n{escalation.human_decision}",
                    },
                }
            )

        return blocks

    def _rule_proposal_blocks(
        self,
        rule: Rule,
        include_buttons: bool = True,
        outcome: str | None = None,
        conflict_warnings: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        exceptions = f"\n\n{rule.exceptions_note}" if rule.exceptions_note else ""
        body = (
            "📋 *Proposed rule*\n\n"
            f"*WHEN*\n{rule.condition_description}\n\n"
            f"*DO*\n{rule.action_description}\n\n"
            f"*Confidence:* {rule.extraction_confidence * 100:.0f}%"
            f"{exceptions}"
        )
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        ]

        for warning in conflict_warnings or []:
            existing_condition = getattr(warning, "existing_condition", "")
            existing_action = getattr(warning, "existing_action", "")
            explanation = getattr(warning, "explanation", "")
            warning_text = (
                "⚠️ *Potential conflict with existing rule:*\n"
                f"\"{existing_condition} → {existing_action}\"\n\n"
                f"{explanation}\n\n"
                "Edit this proposal or pause/delete the existing rule before approving."
            )
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": warning_text}})

        if outcome:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Status:* {outcome}"}})

        if include_buttons:
            action_elements = []
            if not conflict_warnings:
                action_elements.append(
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve rule"},
                        "style": "primary",
                        "action_id": "rule_approve",
                        "value": str(rule.id),
                    }
                )
            action_elements.extend(
                [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✏️ Edit rule"},
                        "action_id": "rule_edit",
                        "value": str(rule.id),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Discard"},
                        "style": "danger",
                        "action_id": "rule_discard",
                        "value": str(rule.id),
                    },
                ]
            )
            blocks.append(
                {
                    "type": "actions",
                    "elements": action_elements,
                }
            )

        return blocks
