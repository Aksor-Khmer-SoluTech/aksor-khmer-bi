"""browser brand

Revision ID: 0005_browser_brand
Revises: 0004_signin_device
Create Date: 2026-10-10 00:00:00.000000

The browser a sign-in or session came from when its User-Agent can't tell -- Brave sends Chrome's User-Agent
unchanged, so it's named from the Sec-CH-UA client hint or the portal's own X-Aksor-Browser hint instead.
See app/auth_events.py's browser_brand.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005_browser_brand'
down_revision: Union[str, Sequence[str], None] = '0004_signin_device'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('auth_events') as batch:
        batch.add_column(sa.Column('browser_brand', sa.String(), nullable=True))
    with op.batch_alter_table('auth_sessions') as batch:
        batch.add_column(sa.Column('browser_brand', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('auth_sessions') as batch:
        batch.drop_column('browser_brand')
    with op.batch_alter_table('auth_events') as batch:
        batch.drop_column('browser_brand')
