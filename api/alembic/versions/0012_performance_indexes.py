"""performance indexes

Revision ID: 0012_performance_indexes
Revises: 0011_account_billing_tiers
Create Date: 2026-07-03

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0012_performance_indexes"
down_revision = "0011_account_billing_tiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # policy_check_log indexes
    op.create_index(
        "idx_policy_check_log_rule_id",
        "policy_check_log",
        ["rule_id"],
    )

    # escalations indexes
    op.create_index(
        "idx_escalations_status",
        "escalations",
        ["status"],
    )
    op.create_index(
        "idx_escalations_org_status",
        "escalations",
        ["org_id", "status"],
    )
    op.create_index(
        "idx_escalations_org_finalized",
        "escalations",
        ["org_id", "finalized_at"],
    )
    op.create_index(
        "idx_escalations_rule_id",
        "escalations",
        ["rule_id"],
    )
    op.create_index(
        "idx_escalations_auto_resolved",
        "escalations",
        ["auto_resolved"],
    )

    # rules indexes
    op.create_index(
        "idx_rules_org_status_trigger",
        "rules",
        ["org_id", "status", "trigger_count"],
    )
    op.create_index(
        "idx_rules_source_escalation",
        "rules",
        ["source_escalation_id"],
    )


def downgrade() -> None:
    # Drop in reverse order
    op.drop_index("idx_rules_source_escalation", table_name="rules")
    op.drop_index("idx_rules_org_status_trigger", table_name="rules")
    op.drop_index("idx_escalations_auto_resolved", table_name="escalations")
    op.drop_index("idx_escalations_rule_id", table_name="escalations")
    op.drop_index("idx_escalations_org_finalized", table_name="escalations")
    op.drop_index("idx_escalations_org_status", table_name="escalations")
    op.drop_index("idx_escalations_status", table_name="escalations")
    op.drop_index("idx_policy_check_log_rule_id", table_name="policy_check_log")
