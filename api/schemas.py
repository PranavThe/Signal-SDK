from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from typing import Literal


class EscalationCreate(BaseModel):
    context: str = Field(
        ...,
        description=(
            "Context for the decision. Must be a string. "
            "For structured data, use json.dumps() to convert dict to JSON string. "
            "Example: json.dumps({'author': {'email': 'alice@company.com'}})"
        ),
        examples=[
            "Customer Jane Smith is requesting a refund on order #1234.",
            '{"deployment_id": "deploy-007", "author": {"email": "alice@company.com"}}',
        ],
    )
    question: str = Field(
        ...,
        description="The decision question to escalate to a human",
        examples=["Should this deployment be approved?", "Should I approve this refund?"],
    )
    agent_id: str = Field(
        ...,
        description="Unique identifier for the agent making the decision",
        examples=["support-agent", "deploy-agent"],
    )
    action: str | None = Field(
        None,
        description="The action the agent wants to take",
        examples=["approve_deployment", "send_refund"],
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata about the escalation",
    )

    @field_validator("context", mode="before")
    @classmethod
    def validate_context_is_string(cls, v):
        if isinstance(v, dict):
            raise ValueError(
                "context must be a string. If you have a dict, convert it to JSON first: "
                "json.dumps(your_dict). "
                f"Received type: {type(v).__name__}"
            )
        if not isinstance(v, str):
            raise ValueError(
                f"context must be a string. Received type: {type(v).__name__}. "
                "For structured data, use json.dumps() to convert to a JSON string."
            )
        return v


class EscalationCreateResponse(BaseModel):
    escalation_id: UUID
    status: str
    context_warnings: list[str] = Field(default_factory=list, description="Warnings about context validation and normalization")


class EscalationStateResponse(BaseModel):
    escalation_id: UUID
    status: str
    human_decision: str | None
    rule_id: UUID | None
    auto_resolved: bool = False
    finalized: bool = False
    finalization_reason: str | None = None


class CheckRequest(BaseModel):
    action: str
    agent_id: str
    context: dict[str, Any]


class CheckResponse(BaseModel):
    result: str
    rule_id: UUID | None
    reasoning: str
    modification: dict[str, Any] | None = None
    context_warnings: list[str] = Field(default_factory=list)


class ExtractedRule(BaseModel):
    condition_description: str
    action_description: str
    structured_conditions: list[dict[str, Any]]
    structured_action: dict[str, Any]
    confidence: float
    exceptions_note: str


class RuleStatusUpdate(BaseModel):
    status: Literal["active", "paused", "archived"]


class RuleDeleteRequest(BaseModel):
    rule_ids: list[UUID] = Field(min_length=1)
