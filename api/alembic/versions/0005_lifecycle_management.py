from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_lifecycle_management"
down_revision = "0004_multitenant_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rules",
        sa.Column("override_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("organizations", sa.Column("webhook_url", sa.Text()))
    op.add_column("organizations", sa.Column("webhook_secret", sa.Text()))
    op.create_table(
        "consolidation_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("rule_a_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rules.id"), nullable=False),
        sa.Column("rule_b_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rules.id"), nullable=False),
        sa.Column("merged_condition", sa.Text(), nullable=False),
        sa.Column("merged_action", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_consolidation_suggestions_org_status",
        "consolidation_suggestions",
        ["org_id", "status", "created_at"],
    )
    op.create_index(
        "idx_consolidation_suggestions_pair",
        "consolidation_suggestions",
        ["rule_a_id", "rule_b_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_consolidation_suggestions_pair", table_name="consolidation_suggestions")
    op.drop_index("idx_consolidation_suggestions_org_status", table_name="consolidation_suggestions")
    op.drop_table("consolidation_suggestions")
    op.drop_column("organizations", "webhook_secret")
    op.drop_column("organizations", "webhook_url")
    op.drop_column("rules", "override_count")
