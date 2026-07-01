from __future__ import annotations

from alembic import op


revision = "0002_add_pgvector_embeddings"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE escalations ADD COLUMN context_embedding vector(1536)")
    op.execute("ALTER TABLE rules ADD COLUMN condition_embedding vector(1536)")
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


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_rules_embedding")
    op.execute("DROP INDEX IF EXISTS idx_escalations_embedding")
    op.execute("ALTER TABLE rules DROP COLUMN IF EXISTS condition_embedding")
    op.execute("ALTER TABLE escalations DROP COLUMN IF EXISTS context_embedding")

