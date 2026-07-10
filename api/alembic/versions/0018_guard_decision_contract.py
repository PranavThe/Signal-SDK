"""guard decision contract

Revision ID: 0018_guard_decision_contract
Revises: 0017_add_prescribed_action
Create Date: 2026-07-10

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0018_guard_decision_contract"
down_revision = "0017_add_prescribed_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("policy_check_log", sa.Column("decision_payload", postgresql.JSONB(), nullable=True))
    op.add_column("policy_check_log", sa.Column("escalation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_policy_check_log_escalation_id_escalations",
        "policy_check_log",
        "escalations",
        ["escalation_id"],
        ["id"],
    )
    op.create_index("idx_policy_check_log_escalation_id", "policy_check_log", ["escalation_id"])


def downgrade() -> None:
    op.drop_index("idx_policy_check_log_escalation_id", table_name="policy_check_log")
    op.drop_constraint("fk_policy_check_log_escalation_id_escalations", "policy_check_log", type_="foreignkey")
    op.drop_column("policy_check_log", "escalation_id")
    op.drop_column("policy_check_log", "decision_payload")
