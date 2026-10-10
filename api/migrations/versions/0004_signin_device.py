"""sign-in device

Revision ID: 0004_signin_device
Revises: 0003_font_resources
Create Date: 2026-10-09 00:00:00.000000

A sign-in remembers which browser it came from (a random id kept in a long-lived cookie, stored here only as its
SHA-256) and which session it opened, so a new-device alert means "this browser has never signed in to this account"
rather than "a new IP address or browser version", and "Not me" can sign exactly that session out.
See app/auth_events.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004_signin_device'
down_revision: Union[str, Sequence[str], None] = '0003_font_resources'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('auth_events') as batch:
        batch.add_column(sa.Column('device_hash', sa.String(), nullable=True))
        batch.add_column(sa.Column('session_id', sa.String(), nullable=True))
    op.create_index('ix_auth_events_user_device', 'auth_events', ['user_id', 'device_hash'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_auth_events_user_device', table_name='auth_events')
    with op.batch_alter_table('auth_events') as batch:
        batch.drop_column('session_id')
        batch.drop_column('device_hash')
