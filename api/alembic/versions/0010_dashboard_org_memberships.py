from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_dashboard_org_memberships"
down_revision = "0009_dashboard_auth_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_org_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="owner"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_dashboard_org_memberships_org_user",
        "dashboard_org_memberships",
        ["org_id", "user_id"],
    )
    op.create_index(
        "idx_dashboard_org_memberships_user",
        "dashboard_org_memberships",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_dashboard_org_memberships_user", table_name="dashboard_org_memberships")
    op.drop_constraint(
        "uq_dashboard_org_memberships_org_user",
        "dashboard_org_memberships",
        type_="unique",
    )
    op.drop_table("dashboard_org_memberships")
