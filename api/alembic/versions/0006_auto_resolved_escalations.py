from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_auto_resolved_escalations"
down_revision = "0005_lifecycle_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "escalations",
        sa.Column("auto_resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("escalations", "auto_resolved")
