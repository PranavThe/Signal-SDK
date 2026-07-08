"""llm operation logging

Revision ID: 0015_llm_operation_logging
Revises: 0014_feedback
Create Date: 2026-07-07

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0015_llm_operation_logging"
down_revision = "0014_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create llm_operation_logs table
    op.create_table(
        "llm_operation_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operation_type", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("parsed_output", postgresql.JSONB(), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("validation_passed", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("escalation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["escalation_id"], ["escalations.id"]),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add indexes for performance
    op.create_index("idx_llm_logs_org_id", "llm_operation_logs", ["org_id"])
    op.create_index("idx_llm_logs_operation_type", "llm_operation_logs", ["operation_type"])
    op.create_index("idx_llm_logs_created_at", "llm_operation_logs", ["created_at"])
    op.create_index("idx_llm_logs_escalation_id", "llm_operation_logs", ["escalation_id"])
    op.create_index("idx_llm_logs_rule_id", "llm_operation_logs", ["rule_id"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_llm_logs_rule_id", table_name="llm_operation_logs")
    op.drop_index("idx_llm_logs_escalation_id", table_name="llm_operation_logs")
    op.drop_index("idx_llm_logs_created_at", table_name="llm_operation_logs")
    op.drop_index("idx_llm_logs_operation_type", table_name="llm_operation_logs")
    op.drop_index("idx_llm_logs_org_id", table_name="llm_operation_logs")

    # Drop table
    op.drop_table("llm_operation_logs")
