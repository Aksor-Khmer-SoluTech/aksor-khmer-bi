"""font resources

Revision ID: 0003_font_resources
Revises: 0002_report_shortcuts
Create Date: 2026-10-08 00:00:00.000000

Fonts uploaded at runtime (Resources > Fonts), server-wide. The files live on disk (data/font_resources); this table
describes them. See db/fonts.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003_font_resources'
down_revision: Union[str, Sequence[str], None] = '0002_report_shortcuts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'font_resources',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('family', sa.String(), nullable=False),
        sa.Column('family_key', sa.String(), nullable=False),
        sa.Column('subfamily', sa.String(), nullable=False),
        sa.Column('subfamily_key', sa.String(), nullable=False),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('postscript_name', sa.String(), nullable=False),
        sa.Column('version', sa.String(), nullable=False),
        sa.Column('weight', sa.Integer(), nullable=False),
        sa.Column('italic', sa.Boolean(), nullable=False),
        sa.Column('glyph_count', sa.Integer(), nullable=False),
        sa.Column('khmer_coverage', sa.Float(), nullable=False),
        sa.Column('latin_coverage', sa.Float(), nullable=False),
        sa.Column('has_layout_tables', sa.Boolean(), nullable=False),
        sa.Column('copyright', sa.String(), nullable=False),
        sa.Column('license', sa.String(), nullable=False),
        sa.Column('license_url', sa.String(), nullable=False),
        sa.Column('embedding', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('file_ext', sa.String(), nullable=False),
        sa.Column('sha256', sa.String(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sha256', name='uq_font_resources_sha256'),
        sa.UniqueConstraint('family_key', 'subfamily_key', name='uq_font_resources_family_style'),
    )


def downgrade() -> None:
    op.drop_table('font_resources')
