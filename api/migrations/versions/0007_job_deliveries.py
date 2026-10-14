"""job deliveries

Revision ID: 0007_job_deliveries
Revises: 0006_report_drafts
Create Date: 2026-10-12 00:00:00.000000

Where each file a job run produced went: emailed, saved to a folder, failed (and why) or skipped -- one row per
file, so a job split by a filter (one file per branch) shows each branch. See app/job_delivery.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007_job_deliveries'
down_revision: Union[str, Sequence[str], None] = '0006_report_drafts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'job_deliveries',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('burst_value', sa.String(), nullable=True),
        sa.Column('burst_label', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('file_name', sa.String(), nullable=True),
        sa.Column('file_path', sa.String(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('saved_to', sa.String(), nullable=True),
        sa.Column('email_to', sa.JSON(), nullable=True),
        sa.Column('email_cc', sa.JSON(), nullable=True),
        sa.Column('subject', sa.String(), nullable=True),
        sa.Column('body', sa.String(), nullable=True),
        sa.Column('sent_at', sa.String(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['job_runs.id']),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_job_deliveries_run_id', 'job_deliveries', ['run_id'])
    op.create_index('ix_job_deliveries_job_id', 'job_deliveries', ['job_id'])


def downgrade() -> None:
    op.drop_index('ix_job_deliveries_job_id', table_name='job_deliveries')
    op.drop_index('ix_job_deliveries_run_id', table_name='job_deliveries')
    op.drop_table('job_deliveries')
