"""report drafts

Revision ID: 0006_report_drafts
Revises: 0005_browser_brand
Create Date: 2026-10-10 00:00:00.000000

A report made with the New report wizard starts as a draft: only people who manage it see or run it until it's
published. Every existing report is published (false). See app/routers/report_wizard.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006_report_drafts'
down_revision: Union[str, Sequence[str], None] = '0005_browser_brand'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('reports') as batch:
        batch.add_column(sa.Column('is_draft', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('reports') as batch:
        batch.drop_column('is_draft')
