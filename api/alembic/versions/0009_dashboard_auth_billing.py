from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_dashboard_auth_billing"
down_revision = "0008_dashboard_review_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("stripe_customer_id", sa.Text()))
    op.add_column("organizations", sa.Column("stripe_subscription_id", sa.Text()))
    op.add_column(
        "organizations",
        sa.Column("billing_status", sa.Text(), nullable=False, server_default="inactive"),
    )
    op.add_column("organizations", sa.Column("billing_current_period_end", sa.DateTime(timezone=True)))
    op.create_index("idx_organizations_stripe_customer", "organizations", ["stripe_customer_id"])
    op.create_index("idx_organizations_stripe_subscription", "organizations", ["stripe_subscription_id"])


def downgrade() -> None:
    op.drop_index("idx_organizations_stripe_subscription", table_name="organizations")
    op.drop_index("idx_organizations_stripe_customer", table_name="organizations")
    op.drop_column("organizations", "billing_current_period_end")
    op.drop_column("organizations", "billing_status")
    op.drop_column("organizations", "stripe_subscription_id")
    op.drop_column("organizations", "stripe_customer_id")
