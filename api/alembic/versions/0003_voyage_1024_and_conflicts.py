from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_voyage_1024_and_conflicts"
down_revision = "0002_add_pgvector_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_rules_embedding")
    op.execute("DROP INDEX IF EXISTS idx_escalations_embedding")
    op.execute(
        """
        ALTER TABLE escalations
        ALTER COLUMN context_embedding TYPE vector(1024)
        USING NULL
        """
    )
    op.execute(
        """
        ALTER TABLE rules
        ALTER COLUMN condition_embedding TYPE vector(1024)
        USING NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_escalations_embedding
        ON escalations USING ivfflat (context_embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_rules_embedding
        ON rules USING ivfflat (condition_embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )
    op.create_table(
        "rule_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_a_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rules.id"), nullable=False),
        sa.Column("rule_b_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rules.id"), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("rule_conflicts")
    op.execute("DROP INDEX IF EXISTS idx_rules_embedding")
    op.execute("DROP INDEX IF EXISTS idx_escalations_embedding")
    op.execute(
        """
        ALTER TABLE rules
        ALTER COLUMN condition_embedding TYPE vector(1536)
        USING NULL
        """
    )
    op.execute(
        """
        ALTER TABLE escalations
        ALTER COLUMN context_embedding TYPE vector(1536)
        USING NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_escalations_embedding
        ON escalations USING ivfflat (context_embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_rules_embedding
        ON rules USING ivfflat (condition_embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )

