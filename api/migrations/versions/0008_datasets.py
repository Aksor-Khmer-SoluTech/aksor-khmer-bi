"""datasets

Revision ID: 0008_datasets
Revises: 0007_job_deliveries
Create Date: 2026-10-13 00:00:00.000000

A dataset is one governed definition of a body of data -- source, filters, fields, measures -- that many reports
build on (a report's data_source {"type": "dataset", "dataset": <name>}). See app/datasets.py. With it, the
dataset's row-level access: datasets.access_mode ("open", the default, or "restricted") and dataset_access_grants (a
user or role, "run" or "build", optional filter limits and expiry). The new dataset:manage permission is added to the
catalog at start-up (rbac.seed_defaults), not here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008_datasets'
down_revision: Union[str, Sequence[str], None] = '0007_job_deliveries'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'datasets',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('parameters', sa.JSON(), nullable=False),
        sa.Column('data_source', sa.JSON(), nullable=False),
        sa.Column('fields', sa.JSON(), nullable=False),
        sa.Column('measures', sa.JSON(), nullable=False),
        sa.Column('access_mode', sa.String(), nullable=False, server_default='open'),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_datasets_org_name'),
    )
    op.create_index('ix_datasets_org_id', 'datasets', ['org_id'])
    op.create_table(
        'dataset_access_grants',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('dataset_id', sa.String(), nullable=False),
        sa.Column('subject_type', sa.String(), nullable=False),
        sa.Column('subject_id', sa.String(), nullable=False),
        sa.Column('level', sa.String(), nullable=False),
        sa.Column('parameter_limits', sa.JSON(), nullable=True),
        sa.Column('granted_at', sa.String(), nullable=False),
        sa.Column('granted_by', sa.String(), nullable=True),
        sa.Column('expires_at', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['granted_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dataset_access_grants_dataset_id', 'dataset_access_grants', ['dataset_id'])


def downgrade() -> None:
    op.drop_index('ix_dataset_access_grants_dataset_id', table_name='dataset_access_grants')
    op.drop_table('dataset_access_grants')
    op.drop_index('ix_datasets_org_id', table_name='datasets')
    op.drop_table('datasets')
