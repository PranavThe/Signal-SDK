"""LLM operation logging and observability service."""
from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from anthropic.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.models import LLMOperationLog


# Anthropic pricing per 1M tokens (as of 2026)
PRICING = {
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20240620": {"input": 3.00, "output": 15.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for an LLM call."""
    pricing = PRICING.get(model, {"input": 3.00, "output": 15.00})  # Default to Sonnet pricing
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


class LLMObserver:
    """Wrapper for Anthropic API calls with automatic logging."""

    def __init__(self, session: AsyncSession, org_id: UUID | None = None):
        self.session = session
        self.org_id = org_id
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def call(
        self,
        operation_type: str,
        prompt: str,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 4096,
        temperature: float = 1.0,
        tools: list[dict[str, Any]] | None = None,
        escalation_id: UUID | None = None,
        rule_id: UUID | None = None,
    ) -> tuple[Message, LLMOperationLog]:
        """
        Make an Anthropic API call with automatic logging.

        Returns:
            Tuple of (anthropic_response, log_entry)
        """
        start_time = time.time()
        log_entry = LLMOperationLog(
            org_id=self.org_id,
            operation_type=operation_type,
            prompt=prompt,
            model=model,
            response="",
            escalation_id=escalation_id,
            rule_id=rule_id,
        )

        try:
            # Make the API call
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            if tools:
                kwargs["tools"] = tools

            response = await self.client.messages.create(**kwargs)

            # Calculate metrics
            latency_ms = int((time.time() - start_time) * 1000)
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost_usd = calculate_cost(model, input_tokens, output_tokens)

            # Extract response text
            response_text = ""
            if response.content:
                for block in response.content:
                    if hasattr(block, "text"):
                        response_text += block.text

            # Update log entry
            log_entry.response = response_text or str(response.content)
            log_entry.tokens_input = input_tokens
            log_entry.tokens_output = output_tokens
            log_entry.latency_ms = latency_ms
            log_entry.cost_usd = cost_usd
            log_entry.validation_passed = True

            # Save log
            self.session.add(log_entry)
            await self.session.flush()

            return response, log_entry

        except Exception as e:
            # Log the error
            latency_ms = int((time.time() - start_time) * 1000)
            log_entry.response = ""
            log_entry.latency_ms = latency_ms
            log_entry.validation_passed = False
            log_entry.error_message = str(e)

            self.session.add(log_entry)
            await self.session.flush()

            raise

    async def update_log_quality(
        self,
        log: LLMOperationLog,
        confidence_score: float | None = None,
        parsed_output: dict[str, Any] | None = None,
        validation_passed: bool = True,
    ) -> None:
        """Update a log entry with quality metrics after parsing."""
        if confidence_score is not None:
            log.confidence_score = confidence_score
        if parsed_output is not None:
            log.parsed_output = parsed_output
        log.validation_passed = validation_passed
        await self.session.flush()
