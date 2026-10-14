"""dashboards

Revision ID: 0010_dashboards
Revises: 0009_analyses
Create Date: 2026-10-14 00:00:00.000000

Dashboards (app/dashboards.py): Analyze views as tiles on one page, filters shared across them, shared with roles.
Data alerts need no table: they're jobs (job_type "data_alert").
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0010_dashboards'
down_revision: Union[str, Sequence[str], None] = '0009_analyses'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dashboards',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('owner_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('tiles', sa.JSON(), nullable=False),
        sa.Column('filters', sa.JSON(), nullable=False),
        sa.Column('shared_role_ids', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dashboards_org_id', 'dashboards', ['org_id'])
    op.create_index('ix_dashboards_owner_id', 'dashboards', ['owner_id'])


def downgrade() -> None:
    op.drop_index('ix_dashboards_owner_id', table_name='dashboards')
    op.drop_index('ix_dashboards_org_id', table_name='dashboards')
    op.drop_table('dashboards')
