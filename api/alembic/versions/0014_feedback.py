"""feedback

Revision ID: 0014_feedback
Revises: 0013_product_improvements
Create Date: 2026-07-06

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0014_feedback"
down_revision = "0013_product_improvements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create feedback table
    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("feedback_text", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False, server_default="general"),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("page_url", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add indexes for performance
    op.create_index("idx_feedback_org_id", "feedback", ["org_id"])
    op.create_index("idx_feedback_account_id", "feedback", ["account_id"])
    op.create_index("idx_feedback_created_at", "feedback", ["created_at"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_feedback_created_at", table_name="feedback")
    op.drop_index("idx_feedback_account_id", table_name="feedback")
    op.drop_index("idx_feedback_org_id", table_name="feedback")

    # Drop table
    op.drop_table("feedback")
