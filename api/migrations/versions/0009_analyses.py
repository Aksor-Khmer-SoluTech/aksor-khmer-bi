"""analyses

Revision ID: 0009_analyses
Revises: 0008_datasets
Create Date: 2026-10-14 00:00:00.000000

Saved Analyze views (app/analyze.py): a dataset, its filter values and a pivot layout, kept by the person who made
it. The analyze:use permission is added to the catalog at start-up (rbac.seed_defaults), not here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009_analyses'
down_revision: Union[str, Sequence[str], None] = '0008_datasets'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'analyses',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('owner_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('dataset', sa.String(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_analyses_org_id', 'analyses', ['org_id'])
    op.create_index('ix_analyses_owner_id', 'analyses', ['owner_id'])


def downgrade() -> None:
    op.drop_index('ix_analyses_owner_id', table_name='analyses')
    op.drop_index('ix_analyses_org_id', table_name='analyses')
    op.drop_table('analyses')
