from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(Text)
    owner_email: Mapped[str | None] = mapped_column(Text)
    plan_tier: Mapped[str] = mapped_column(Text, nullable=False, default="free", server_default="free")
    billing_status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default="active")
    stripe_customer_id: Mapped[str | None] = mapped_column(Text)
    stripe_subscription_id: Mapped[str | None] = mapped_column(Text)
    billing_current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    organizations: Mapped[list["Organization"]] = relationship("Organization", back_populates="account")
    dashboard_memberships: Mapped[list["DashboardAccountMembership"]] = relationship(
        "DashboardAccountMembership",
        back_populates="account",
    )


class DashboardAccountMembership(Base):
    __tablename__ = "dashboard_account_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="owner", server_default="owner")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    account: Mapped[Account] = relationship("Account", back_populates="dashboard_memberships")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"))
    slack_channel_id: Mapped[str | None] = mapped_column(Text)
    slack_notifications_enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    webhook_url: Mapped[str | None] = mapped_column(Text)
    webhook_secret: Mapped[str | None] = mapped_column(Text)
    stripe_customer_id: Mapped[str | None] = mapped_column(Text)
    stripe_subscription_id: Mapped[str | None] = mapped_column(Text)
    billing_status: Mapped[str] = mapped_column(Text, nullable=False, default="inactive", server_default="inactive")
    billing_current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="organization")
    account: Mapped[Account | None] = relationship("Account", back_populates="organizations")
    dashboard_memberships: Mapped[list["DashboardOrgMembership"]] = relationship(
        "DashboardOrgMembership",
        back_populates="organization",
    )


class DashboardOrgMembership(Base):
    __tablename__ = "dashboard_org_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="owner", server_default="owner")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="dashboard_memberships")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="Default", server_default="Default")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped[Organization] = relationship("Organization", back_populates="api_keys")


class ContextField(Base):
    __tablename__ = "context_fields"
    __table_args__ = (
        UniqueConstraint("org_id", "canonical_name", name="uq_context_fields_org_canonical"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    field_type: Mapped[str] = mapped_column(Text, nullable=False, default="unknown", server_default="unknown")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    sample_values: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    aliases: Mapped[list["ContextFieldAlias"]] = relationship("ContextFieldAlias", back_populates="field")


class ContextFieldAlias(Base):
    __tablename__ = "context_field_aliases"
    __table_args__ = (
        UniqueConstraint("org_id", "alias", name="uq_context_field_aliases_org_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    field_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("context_fields.id"), nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="observed", server_default="observed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    field: Mapped[ContextField] = relationship("ContextField", back_populates="aliases")


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    context: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    normalized_context: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))

    slack_channel_id: Mapped[str | None] = mapped_column(Text)
    slack_message_ts: Mapped[str | None] = mapped_column(Text)
    slack_followup_ts: Mapped[str | None] = mapped_column(Text)
    slack_rule_proposal_ts: Mapped[str | None] = mapped_column(Text)
    context_embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))

    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    human_decision: Mapped[str | None] = mapped_column(Text)
    human_reasoning: Mapped[str | None] = mapped_column(Text)
    apply_broadly: Mapped[bool | None]
    auto_resolved: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    prescribed_action: Mapped[str | None] = mapped_column(Text)  # Action prescribed by matched rule
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalization_reason: Mapped[str | None] = mapped_column(Text)

    # Tags for organization and filtering
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("ARRAY[]::TEXT[]"),
    )

    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("rules.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    rule: Mapped["Rule | None"] = relationship(
        "Rule",
        foreign_keys=[rule_id],
        post_update=True,
    )


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    condition_description: Mapped[str] = mapped_column(Text, nullable=False)
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    exceptions_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    structured_conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    structured_action: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    condition_embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    agent_scope: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("ARRAY[]::TEXT[]"),
    )
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default="active")
    source_escalation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("escalations.id"),
    )
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    override_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    source_escalation: Mapped[Escalation | None] = relationship(
        "Escalation",
        foreign_keys=[source_escalation_id],
    )


class PolicyCheckLog(Base):
    __tablename__ = "policy_check_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    normalized_context: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    result: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("rules.id"))
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    cache_hit: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class RuleConflict(Base):
    __tablename__ = "rule_conflicts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    rule_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rules.id"), nullable=False)
    rule_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rules.id"), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ConsolidationSuggestion(Base):
    __tablename__ = "consolidation_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    rule_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rules.id"), nullable=False)
    rule_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rules.id"), nullable=False)
    merged_condition: Mapped[str] = mapped_column(Text, nullable=False)
    merged_action: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    rule_a: Mapped[Rule] = relationship("Rule", foreign_keys=[rule_a_id])
    rule_b: Mapped[Rule] = relationship("Rule", foreign_keys=[rule_b_id])


class RuleComment(Base):
    __tablename__ = "rule_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rules.id"), nullable=False)
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_email: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    rule: Mapped[Rule] = relationship("Rule", foreign_keys=[rule_id])


class RuleVersion(Base):
    __tablename__ = "rule_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rules.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    condition_description: Mapped[str] = mapped_column(Text, nullable=False)
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    exceptions_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    structured_conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    structured_action: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changed_by_user_id: Mapped[str | None] = mapped_column(Text)
    changed_by_email: Mapped[str | None] = mapped_column(Text)
    change_description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    rule: Mapped[Rule] = relationship("Rule", foreign_keys=[rule_id])


class HistoricalDecisionImport(Base):
    __tablename__ = "historical_decision_imports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False, default="historical-decisions", server_default="historical-decisions")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="completed", server_default="completed")
    rows_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    fields_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    proposals_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class HistoricalRuleProposal(Base):
    __tablename__ = "historical_rule_proposals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    import_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("historical_decision_imports.id"))
    condition_description: Mapped[str] = mapped_column(Text, nullable=False)
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    exceptions_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    structured_conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    structured_action: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, default="general", server_default="general")
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"))
    page_url: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class LLMOperationLog(Base):
    __tablename__ = "llm_operation_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    operation_type: Mapped[str] = mapped_column(Text, nullable=False)

    # Inputs
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)

    # Outputs
    response: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Metrics
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")

    # Quality
    confidence_score: Mapped[float | None] = mapped_column(Float)
    validation_passed: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    error_message: Mapped[str | None] = mapped_column(Text)

    # References
    escalation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("escalations.id"))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("rules.id"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
