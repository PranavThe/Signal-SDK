from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from typing import Literal


class EscalationCreate(BaseModel):
    context: str
    question: str
    agent_id: str
    action: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EscalationCreateResponse(BaseModel):
    escalation_id: UUID
    status: str


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
