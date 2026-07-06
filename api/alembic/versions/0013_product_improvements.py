"""product improvements

Revision ID: 0013_product_improvements
Revises: 0012_performance_indexes
Create Date: 2026-07-05

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0013_product_improvements"
down_revision = "0012_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add tags column to escalations table
    op.add_column(
        "escalations",
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )

    # Create rule_comments table
    op.create_table(
        "rule_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("comment_text", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Text(), nullable=False),
        sa.Column("created_by_email", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create rule_versions table
    op.create_table(
        "rule_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("condition_description", sa.Text(), nullable=False),
        sa.Column("action_description", sa.Text(), nullable=False),
        sa.Column("exceptions_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("structured_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("structured_action", postgresql.JSONB(), nullable=False),
        sa.Column("changed_by_user_id", sa.Text()),
        sa.Column("changed_by_email", sa.Text()),
        sa.Column("change_description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add indexes for performance
    op.create_index("idx_rule_comments_rule_id", "rule_comments", ["rule_id"])
    op.create_index("idx_rule_versions_rule_id", "rule_versions", ["rule_id"])
    op.create_index("idx_rule_versions_rule_version", "rule_versions", ["rule_id", "version_number"])
    op.create_index("idx_escalations_tags", "escalations", ["tags"], postgresql_using="gin")


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_escalations_tags", table_name="escalations")
    op.drop_index("idx_rule_versions_rule_version", table_name="rule_versions")
    op.drop_index("idx_rule_versions_rule_id", table_name="rule_versions")
    op.drop_index("idx_rule_comments_rule_id", table_name="rule_comments")

    # Drop tables
    op.drop_table("rule_versions")
    op.drop_table("rule_comments")

    # Drop tags column
    op.drop_column("escalations", "tags")
