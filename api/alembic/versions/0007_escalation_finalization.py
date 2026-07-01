from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_escalation_finalization"
down_revision = "0006_auto_resolved_escalations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("escalations", sa.Column("finalized_at", sa.DateTime(timezone=True)))
    op.add_column("escalations", sa.Column("finalization_reason", sa.Text()))
    op.execute(
        """
        UPDATE escalations
        SET finalized_at = COALESCE(responded_at, created_at),
            finalization_reason = CASE
                WHEN auto_resolved IS TRUE THEN 'auto_resolved'
                WHEN apply_broadly IS FALSE THEN 'one_time'
                WHEN rule_id IS NOT NULL THEN 'rule_approved'
                ELSE 'legacy_responded'
            END
        WHERE status = 'responded'
          AND finalized_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("escalations", "finalization_reason")
    op.drop_column("escalations", "finalized_at")
