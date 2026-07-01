from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "escalations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("slack_channel_id", sa.Text()),
        sa.Column("slack_message_ts", sa.Text()),
        sa.Column("slack_followup_ts", sa.Text()),
        sa.Column("slack_rule_proposal_ts", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("human_decision", sa.Text()),
        sa.Column("human_reasoning", sa.Text()),
        sa.Column("apply_broadly", sa.Boolean()),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("condition_description", sa.Text(), nullable=False),
        sa.Column("action_description", sa.Text(), nullable=False),
        sa.Column("exceptions_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("structured_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("structured_action", postgresql.JSONB(), nullable=False),
        sa.Column("agent_scope", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]")),
        sa.Column("extraction_confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("source_escalation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("escalations.id")),
        sa.Column("trigger_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_foreign_key("fk_rule", "escalations", "rules", ["rule_id"], ["id"])

    op.create_table(
        "policy_check_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rules.id")),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("policy_check_log")
    op.drop_constraint("fk_rule", "escalations", type_="foreignkey")
    op.drop_table("rules")
    op.drop_table("escalations")

