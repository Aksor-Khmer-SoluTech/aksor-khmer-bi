"""role assignment source

Revision ID: 0013_role_assignment_source
Revises: 0012_stylesheet_formats
Create Date: 2026-10-19 00:00:00.000000

LDAP group sync (app/auth_ldap.py) marked the role grants it makes with granted_by = "ldap-sync" -- but granted_by is
a foreign key to users.id, so a database that checks foreign keys (PostgreSQL) refused the insert, and an LDAP user
whose group maps to a role couldn't sign in. Those grants say where they came from in `source` instead ("ldap");
granted_by stays a real user or null. Rows already written with the old marker (a SQLite install) move over.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0013_role_assignment_source'
down_revision: Union[str, Sequence[str], None] = '0012_stylesheet_formats'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('user_role_assignments') as batch:
        batch.add_column(sa.Column('source', sa.String(), nullable=True))
    op.execute("UPDATE user_role_assignments SET source = 'ldap', granted_by = NULL WHERE granted_by = 'ldap-sync'")


def downgrade() -> None:
    op.execute("UPDATE user_role_assignments SET granted_by = 'ldap-sync' WHERE source = 'ldap'")
    with op.batch_alter_table('user_role_assignments') as batch:
        batch.drop_column('source')
