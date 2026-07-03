from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func, text
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
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalization_reason: Mapped[str | None] = mapped_column(Text)

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
