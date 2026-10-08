"""report shortcuts

Revision ID: 0002_report_shortcuts
Revises: 0001_initial_schema
Create Date: 2026-10-08 00:00:00.000000

A report can be listed in more folders than the one it is filed in. A shortcut is only that placement -- it
carries no permissions of its own (see db/folders.py's ReportShortcut).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002_report_shortcuts'
down_revision: Union[str, Sequence[str], None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'report_shortcuts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('report_id', sa.String(), nullable=False),
        sa.Column('folder_id', sa.String(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['reports.report_id']),
        sa.ForeignKeyConstraint(['folder_id'], ['folders.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('report_id', 'folder_id', name='uq_report_shortcuts_report_folder'),
    )
    op.create_index('ix_report_shortcuts_report_id', 'report_shortcuts', ['report_id'])
    op.create_index('ix_report_shortcuts_folder_id', 'report_shortcuts', ['folder_id'])


def downgrade() -> None:
    op.drop_table('report_shortcuts')
