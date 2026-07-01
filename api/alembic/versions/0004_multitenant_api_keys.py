from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_multitenant_api_keys"
down_revision = "0003_voyage_1024_and_conflicts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slack_channel_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False, server_default="Default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )

    op.add_column("escalations", sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("rules", sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("policy_check_log", sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_escalations_org", "escalations", "organizations", ["org_id"], ["id"])
    op.create_foreign_key("fk_rules_org", "rules", "organizations", ["org_id"], ["id"])
    op.create_foreign_key("fk_policy_check_log_org", "policy_check_log", "organizations", ["org_id"], ["id"])
    op.create_index("idx_escalations_org_created", "escalations", ["org_id", "created_at"])
    op.create_index("idx_rules_org_status", "rules", ["org_id", "status"])
    op.create_index("idx_policy_check_log_org_created", "policy_check_log", ["org_id", "created_at"])

    op.execute(
        """
        DO $$
        DECLARE
            default_org_id uuid;
        BEGIN
            INSERT INTO organizations (name)
            VALUES ('Default')
            RETURNING id INTO default_org_id;

            UPDATE escalations SET org_id = default_org_id WHERE org_id IS NULL;
            UPDATE rules SET org_id = default_org_id WHERE org_id IS NULL;
            UPDATE policy_check_log SET org_id = default_org_id WHERE org_id IS NULL;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("idx_policy_check_log_org_created", table_name="policy_check_log")
    op.drop_index("idx_rules_org_status", table_name="rules")
    op.drop_index("idx_escalations_org_created", table_name="escalations")
    op.drop_constraint("fk_policy_check_log_org", "policy_check_log", type_="foreignkey")
    op.drop_constraint("fk_rules_org", "rules", type_="foreignkey")
    op.drop_constraint("fk_escalations_org", "escalations", type_="foreignkey")
    op.drop_column("policy_check_log", "org_id")
    op.drop_column("rules", "org_id")
    op.drop_column("escalations", "org_id")
    op.drop_table("api_keys")
    op.drop_table("organizations")
