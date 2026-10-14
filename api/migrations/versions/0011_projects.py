"""projects

Revision ID: 0011_projects
Revises: 0010_dashboards
Create Date: 2026-10-14 00:00:00.000000

Projects (app/projects.py): a top-level Resources folder marked as a project -- its templates, images and
stylesheets move between environments as one package. Images and stylesheets get a content fingerprint (sha256), so
an import recognises a file that is already there, and an upload can say "this exact image already exists". Rows
from before are fingerprinted the first time they're needed (null until then).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0011_projects'
down_revision: Union[str, Sequence[str], None] = '0010_dashboards'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('folders') as batch:
        batch.add_column(sa.Column('is_project', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('image_resources') as batch:
        batch.add_column(sa.Column('sha256', sa.String(), nullable=True))
    with op.batch_alter_table('stylesheet_resources') as batch:
        batch.add_column(sa.Column('sha256', sa.String(), nullable=True))
    op.create_index('ix_image_resources_sha256', 'image_resources', ['sha256'])
    op.create_index('ix_stylesheet_resources_sha256', 'stylesheet_resources', ['sha256'])


def downgrade() -> None:
    op.drop_index('ix_stylesheet_resources_sha256', table_name='stylesheet_resources')
    op.drop_index('ix_image_resources_sha256', table_name='image_resources')
    with op.batch_alter_table('stylesheet_resources') as batch:
        batch.drop_column('sha256')
    with op.batch_alter_table('image_resources') as batch:
        batch.drop_column('sha256')
    with op.batch_alter_table('folders') as batch:
        batch.drop_column('is_project')
