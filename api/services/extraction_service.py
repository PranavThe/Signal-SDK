from __future__ import annotations

import json
from typing import Any

from anthropic import AsyncAnthropic

from api.config import settings
from api.models import Escalation, Rule
from api.schemas import ExtractedRule


EXTRACTION_TOOL = {
    "name": "extract_rule",
    "description": "Extract a generalizable operational rule from a human decision",
    "input_schema": {
        "type": "object",
        "properties": {
            "condition_description": {
                "type": "string",
                "description": "Plain English. When does this rule apply? Be specific about the conditions. Example: 'When a Gold or Platinum tier customer requests a refund on an order that is between 31 and 60 days old'",
            },
            "action_description": {
                "type": "string",
                "description": "Plain English. What should the agent do? Example: 'Approve the refund automatically without escalating'",
            },
            "structured_conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "operator": {
                            "type": "string",
                            "enum": ["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "exists"],
                        },
                        "value": {},
                    },
                    "required": ["field", "operator", "value"],
                },
            },
            "structured_action": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["proceed", "block", "escalate", "modify"],
                    },
                    "parameters": {"type": "object"},
                },
                "required": ["action"],
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "How confident are you this rule correctly generalizes from the single example? Be conservative. Rarely above 0.8 for a single example.",
            },
        },
        "required": [
            "condition_description",
            "action_description",
            "structured_conditions",
            "structured_action",
            "confidence",
        ],
    },
}

REVISION_TOOL = {
    "name": "extract_rule",
    "description": "Revise a rule based on human feedback",
    "input_schema": {
        "type": "object",
        "properties": {
            "condition_description": {
                "type": "string",
                "description": "Plain English. When does this rule apply? Be specific about the conditions.",
            },
            "action_description": {
                "type": "string",
                "description": "Plain English. What should the agent do?",
            },
            "structured_conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "operator": {
                            "type": "string",
                            "enum": ["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "exists"],
                        },
                        "value": {},
                    },
                    "required": ["field", "operator", "value"],
                },
            },
            "structured_action": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["proceed", "block", "escalate", "modify"],
                    },
                    "parameters": {"type": "object"},
                },
                "required": ["action"],
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "How confident are you this rule correctly generalizes?",
            },
            "exceptions_note": {
                "type": "string",
                "description": "Optional. Specific situations where this rule should NOT apply even if conditions match. Only update if the human explicitly requested changes to exceptions.",
            },
        },
        "required": [
            "condition_description",
            "action_description",
            "structured_conditions",
            "structured_action",
            "confidence",
        ],
    },
}


SYSTEM_PROMPT = """You are a policy extraction system. Your job is to take a single human
decision made in response to an AI agent escalation and extract a
generalizable operational rule from it.

Be conservative. It is far better to extract a narrow, accurate rule
than a broad, incorrect one. Only generalize along dimensions that are
clearly relevant to the human's decision. Use only the metadata fields
that were actually provided."""


def _block_type(block: Any) -> str | None:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


def _block_name(block: Any) -> str | None:
    if isinstance(block, dict):
        return block.get("name")
    return getattr(block, "name", None)


def _block_input(block: Any) -> dict[str, Any] | None:
    if isinstance(block, dict):
        return block.get("input")
    return getattr(block, "input", None)


class ExtractionService:
    def __init__(self) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def extract_rule(self, escalation: Escalation) -> ExtractedRule:
        user_prompt = f"""An AI agent escalated this situation and a human made a decision.

CONTEXT: {escalation.context}
QUESTION: {escalation.question}
METADATA: {json.dumps(escalation.metadata_, indent=2)}
HUMAN DECISION: {escalation.human_decision}"""

        message = await self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "extract_rule"},
        )

        for block in message.content:
            if _block_type(block) == "tool_use" and _block_name(block) == "extract_rule":
                tool_input = _block_input(block)
                if tool_input is None:
                    break
                structured_action = tool_input.setdefault("structured_action", {})
                structured_action.setdefault("parameters", {})
                # Force exceptions to always be blank on initial extraction - user will add manually if needed
                tool_input["exceptions_note"] = ""
                return ExtractedRule.model_validate(tool_input)

        raise RuntimeError("Claude did not return the expected extract_rule tool response")

    async def revise_rule(self, escalation: Escalation, rule: Rule, edit_text: str) -> ExtractedRule:
        # Build prompt with current exceptions if they exist
        exceptions_line = f"EXCEPTIONS: {rule.exceptions_note}" if rule.exceptions_note else ""

        user_prompt = f"""A human reviewed a proposed operational rule and asked for an edit.

Original escalation:
CONTEXT: {escalation.context}
QUESTION: {escalation.question}
METADATA: {json.dumps(escalation.metadata_, indent=2)}
HUMAN DECISION: {escalation.human_decision}

Current proposed rule:
WHEN: {rule.condition_description}
DO: {rule.action_description}
{exceptions_line}
STRUCTURED CONDITIONS: {json.dumps(rule.structured_conditions, indent=2)}
STRUCTURED ACTION: {json.dumps(rule.structured_action, indent=2)}

Human requested edit:
{edit_text}

Revise the rule to incorporate the human's requested edit. Preserve the original decision intent unless the edit explicitly changes it."""

        message = await self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[REVISION_TOOL],
            tool_choice={"type": "tool", "name": "extract_rule"},
        )

        for block in message.content:
            if _block_type(block) == "tool_use" and _block_name(block) == "extract_rule":
                tool_input = _block_input(block)
                if tool_input is None:
                    break
                structured_action = tool_input.setdefault("structured_action", {})
                structured_action.setdefault("parameters", {})
                # Preserve existing exceptions if LLM didn't update them
                tool_input.setdefault("exceptions_note", rule.exceptions_note)
                return ExtractedRule.model_validate(tool_input)

        raise RuntimeError("Claude did not return the expected revised extract_rule tool response")
