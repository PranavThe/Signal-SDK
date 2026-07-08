"""context schema and historical imports

Revision ID: 0015_context_schema_and_history
Revises: 0014_feedback
Create Date: 2026-07-07

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0015_context_schema_and_history"
down_revision = "0014_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "escalations",
        sa.Column("normalized_context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "policy_check_log",
        sa.Column("normalized_context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_table(
        "context_fields",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("field_type", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sample_values", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "canonical_name", name="uq_context_fields_org_canonical"),
    )
    op.create_table(
        "context_field_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="observed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["field_id"], ["context_fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "alias", name="uq_context_field_aliases_org_alias"),
    )
    op.create_index("idx_context_fields_org", "context_fields", ["org_id"])
    op.create_index("idx_context_aliases_org", "context_field_aliases", ["org_id"])

    op.create_table(
        "historical_decision_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False, server_default="historical-decisions"),
        sa.Column("status", sa.Text(), nullable=False, server_default="completed"),
        sa.Column("rows_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fields_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("proposals_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "historical_rule_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("condition_description", sa.Text(), nullable=False),
        sa.Column("action_description", sa.Text(), nullable=False),
        sa.Column("exceptions_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("structured_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("structured_action", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["import_id"], ["historical_decision_imports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_historical_imports_org", "historical_decision_imports", ["org_id"])
    op.create_index("idx_historical_proposals_org_status", "historical_rule_proposals", ["org_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_historical_proposals_org_status", table_name="historical_rule_proposals")
    op.drop_index("idx_historical_imports_org", table_name="historical_decision_imports")
    op.drop_table("historical_rule_proposals")
    op.drop_table("historical_decision_imports")
    op.drop_index("idx_context_aliases_org", table_name="context_field_aliases")
    op.drop_index("idx_context_fields_org", table_name="context_fields")
    op.drop_table("context_field_aliases")
    op.drop_table("context_fields")
    op.drop_column("policy_check_log", "normalized_context")
    op.drop_column("escalations", "normalized_context")
