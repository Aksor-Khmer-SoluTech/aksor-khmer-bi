"""stylesheet formats

Revision ID: 0012_stylesheet_formats
Revises: 0011_projects
Create Date: 2026-10-14 00:00:00.000000

A stylesheet can be uploaded as SCSS, Sass (indented) or Less as well as CSS (app/style_compile.py). The source is
kept next to the compiled style.css that templates use; `source_format` says which it is -- null (or "css") for a
plain CSS file, as every stylesheet from before is.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0012_stylesheet_formats'
down_revision: Union[str, Sequence[str], None] = '0011_projects'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('stylesheet_resources') as batch:
        batch.add_column(sa.Column('source_format', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('stylesheet_resources') as batch:
        batch.drop_column('source_format')
