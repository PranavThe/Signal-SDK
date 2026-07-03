from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_account_billing_tiers"
down_revision = "0010_dashboard_org_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("owner_user_id", sa.Text()),
        sa.Column("owner_email", sa.Text()),
        sa.Column("plan_tier", sa.Text(), nullable=False, server_default="free"),
        sa.Column("billing_status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("stripe_customer_id", sa.Text()),
        sa.Column("stripe_subscription_id", sa.Text()),
        sa.Column("billing_current_period_end", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_accounts_owner_user", "accounts", ["owner_user_id"])
    op.create_index("idx_accounts_stripe_customer", "accounts", ["stripe_customer_id"])
    op.create_index("idx_accounts_stripe_subscription", "accounts", ["stripe_subscription_id"])

    op.create_table(
        "dashboard_account_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="owner"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_dashboard_account_memberships_account_user",
        "dashboard_account_memberships",
        ["account_id", "user_id"],
    )
    op.create_index(
        "idx_dashboard_account_memberships_user",
        "dashboard_account_memberships",
        ["user_id"],
    )

    op.add_column("organizations", sa.Column("account_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_organizations_account_id",
        "organizations",
        "accounts",
        ["account_id"],
        ["id"],
    )
    op.create_index("idx_organizations_account_id", "organizations", ["account_id"])

    op.execute(
        """
        WITH user_org_counts AS (
            SELECT
                dom.user_id,
                MIN(dom.email) AS email,
                COUNT(DISTINCT dom.org_id) AS org_count,
                BOOL_OR(o.billing_status IN ('active', 'trialing')) AS has_paid_status,
                MIN(o.stripe_customer_id) FILTER (WHERE o.stripe_customer_id IS NOT NULL) AS stripe_customer_id,
                MIN(o.stripe_subscription_id) FILTER (WHERE o.stripe_subscription_id IS NOT NULL) AS stripe_subscription_id,
                MAX(o.billing_current_period_end) AS billing_current_period_end
            FROM dashboard_org_memberships dom
            JOIN organizations o ON o.id = dom.org_id
            GROUP BY dom.user_id
        ),
        prepared AS (
            SELECT
                gen_random_uuid() AS account_id,
                user_id,
                email,
                CASE
                    WHEN POSITION('@' IN email) > 1 THEN SPLIT_PART(email, '@', 1) || '''s account'
                    ELSE 'Signal account'
                END AS name,
                CASE
                    WHEN org_count > 3 THEN 'scale'
                    WHEN has_paid_status THEN 'pro'
                    ELSE 'free'
                END AS plan_tier,
                CASE WHEN has_paid_status THEN 'active' ELSE 'active' END AS billing_status,
                stripe_customer_id,
                stripe_subscription_id,
                billing_current_period_end
            FROM user_org_counts
        ),
        inserted AS (
            INSERT INTO accounts (
                id,
                name,
                owner_user_id,
                owner_email,
                plan_tier,
                billing_status,
                stripe_customer_id,
                stripe_subscription_id,
                billing_current_period_end
            )
            SELECT
                account_id,
                name,
                user_id,
                email,
                plan_tier,
                billing_status,
                stripe_customer_id,
                stripe_subscription_id,
                billing_current_period_end
            FROM prepared
            RETURNING id
        )
        INSERT INTO dashboard_account_memberships (account_id, user_id, email, role)
        SELECT account_id, user_id, email, 'owner'
        FROM prepared
        """
    )

    op.execute(
        """
        WITH membership_choice AS (
            SELECT DISTINCT ON (dom.org_id)
                dom.org_id,
                dam.account_id
            FROM dashboard_org_memberships dom
            JOIN dashboard_account_memberships dam ON dam.user_id = dom.user_id
            ORDER BY dom.org_id, CASE WHEN dom.role = 'owner' THEN 0 ELSE 1 END, dom.created_at ASC
        )
        UPDATE organizations o
        SET account_id = membership_choice.account_id
        FROM membership_choice
        WHERE o.id = membership_choice.org_id
        """
    )

    op.execute(
        """
        WITH prepared AS (
            SELECT
                o.id AS org_id,
                gen_random_uuid() AS account_id,
                o.name || ' account' AS name,
                CASE WHEN o.billing_status IN ('active', 'trialing') THEN 'pro' ELSE 'free' END AS plan_tier,
                CASE WHEN o.billing_status IN ('active', 'trialing') THEN o.billing_status ELSE 'active' END AS billing_status,
                o.stripe_customer_id,
                o.stripe_subscription_id,
                o.billing_current_period_end
            FROM organizations o
            WHERE o.account_id IS NULL
        ),
        inserted AS (
            INSERT INTO accounts (
                id,
                name,
                plan_tier,
                billing_status,
                stripe_customer_id,
                stripe_subscription_id,
                billing_current_period_end
            )
            SELECT
                account_id,
                name,
                plan_tier,
                billing_status,
                stripe_customer_id,
                stripe_subscription_id,
                billing_current_period_end
            FROM prepared
            RETURNING id
        )
        UPDATE organizations o
        SET account_id = prepared.account_id
        FROM prepared
        WHERE o.id = prepared.org_id
        """
    )

    op.alter_column("organizations", "account_id", nullable=False)


def downgrade() -> None:
    op.drop_index("idx_organizations_account_id", table_name="organizations")
    op.drop_constraint("fk_organizations_account_id", "organizations", type_="foreignkey")
    op.drop_column("organizations", "account_id")
    op.drop_index("idx_dashboard_account_memberships_user", table_name="dashboard_account_memberships")
    op.drop_constraint(
        "uq_dashboard_account_memberships_account_user",
        "dashboard_account_memberships",
        type_="unique",
    )
    op.drop_table("dashboard_account_memberships")
    op.drop_index("idx_accounts_stripe_subscription", table_name="accounts")
    op.drop_index("idx_accounts_stripe_customer", table_name="accounts")
    op.drop_index("idx_accounts_owner_user", table_name="accounts")
    op.drop_table("accounts")
