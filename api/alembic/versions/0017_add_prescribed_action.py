"""Add prescribed_action to escalations

Revision ID: 0017_add_prescribed_action
Revises: 0016_llm_operation_logging
Create Date: 2026-07-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0017_add_prescribed_action'
down_revision = '0016_llm_operation_logging'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add prescribed_action column to escalations table
    op.add_column('escalations', sa.Column('prescribed_action', sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove prescribed_action column from escalations table
    op.drop_column('escalations', 'prescribed_action')
