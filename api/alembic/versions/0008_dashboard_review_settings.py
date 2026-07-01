from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_dashboard_review_settings"
down_revision = "0007_escalation_finalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("slack_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("organizations", "slack_notifications_enabled")
