"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-28 00:00:00.000000

The whole schema in one migration. It replaces the twenty-one incremental
migrations that grew alongside the code before the first deployment -- with no
installed base there was nothing to upgrade *from*, so a fresh database now
gets the finished tables directly instead of replaying their history -- and,
since then, the four that followed it (report version labels and their
uniqueness, uploaded JDBC drivers, sign-in sessions), folded in the same way
before any release. From here on, every schema change is a new migration on
top of this one.

A database created by one of those earlier revisions can't be upgraded from
this file: see docs/deployment.md ("Migrations were squashed").

Tables are grouped by concern, parents before the tables that reference them.
Columns follow one order everywhere: primary key, references to other tables,
the table's own attributes, status flags, then timestamps last (`created_by`,
`created_at`, `updated_at`).

Nothing is seeded here. The permission catalog, the system administrator role,
the root organization and each organization's standard roles are created (and
kept current) by app/rbac.py's seed_defaults() on every API startup, so a
database migrated by this file is empty until the API first starts.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # ---- tenancy & identity -------------------------------------------------
    op.create_table(
        'organizations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('parent_org_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['parent_org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'users',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('display_name', sa.String(), nullable=True),
        sa.Column('auth_source', sa.String(), nullable=False),
        sa.Column('external_dn', sa.String(), nullable=True),
        sa.Column('password_hash', sa.String(), nullable=True),
        sa.Column('must_change_password', sa.Boolean(), nullable=False),
        sa.Column('totp_secret', sa.String(), nullable=True),
        sa.Column('totp_enabled', sa.Boolean(), nullable=False),
        sa.Column('totp_last_used_step', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_locked', sa.Boolean(), nullable=False),
        sa.Column('notify_new_signin', sa.Boolean(), nullable=False),
        sa.Column('avatar_content_type', sa.String(), nullable=True),
        sa.Column('last_login_at', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'username', name='uq_users_org_username'),
    )

    op.create_table(
        'user_settings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'code', name='uq_user_settings_user_code'),
    )

    # ---- roles & permissions ------------------------------------------------
    op.create_table(
        'permissions',
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('code'),
    )

    op.create_table(
        'roles',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_roles_org_name'),
    )

    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('permission_code', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id']),
        sa.ForeignKeyConstraint(['permission_code'], ['permissions.code']),
        sa.PrimaryKeyConstraint('role_id', 'permission_code'),
    )

    op.create_table(
        'user_role_assignments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.String(), nullable=True),
        sa.Column('granted_by', sa.String(), nullable=True),
        sa.Column('granted_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id']),
        sa.ForeignKeyConstraint(['granted_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'user_permission_grants',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('permission_code', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.String(), nullable=True),
        sa.Column('granted_by', sa.String(), nullable=True),
        sa.Column('granted_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['permission_code'], ['permissions.code']),
        sa.ForeignKeyConstraint(['granted_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ---- directory (LDAP / Active Directory) login --------------------------
    op.create_table(
        'ldap_configs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('server_uri', sa.String(), nullable=False),
        sa.Column('bind_method', sa.String(), nullable=False),
        sa.Column('base_dn', sa.String(), nullable=False),
        sa.Column('direct_bind_dn_template', sa.String(), nullable=True),
        sa.Column('service_bind_dn', sa.String(), nullable=True),
        sa.Column('service_bind_password_env', sa.String(), nullable=True),
        sa.Column('user_search_filter', sa.String(), nullable=True),
        sa.Column('upn_domain', sa.String(), nullable=True),
        sa.Column('group_search_base', sa.String(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'ldap_group_role_mappings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('ldap_config_id', sa.String(), nullable=False),
        sa.Column('group_dn', sa.String(), nullable=False),
        sa.Column('role_id', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['ldap_config_id'], ['ldap_configs.id']),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ---- folders & report templates -----------------------------------------
    op.create_table(
        'folders',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('parent_folder_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['parent_folder_id'], ['folders.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'reports',
        sa.Column('report_id', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=True),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('folder_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('template_ext', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('is_public', sa.Boolean(), nullable=False),
        sa.Column('sample_context', sa.JSON(), nullable=True),
        sa.Column('resource_bindings', sa.JSON(), nullable=True),
        sa.Column('parameters', sa.JSON(), nullable=True),
        sa.Column('data_source', sa.JSON(), nullable=True),
        sa.Column('protected_terms_config', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['folder_id'], ['folders.id']),
        sa.PrimaryKeyConstraint('report_id'),
    )
    op.create_index('ix_reports_code', 'reports', ['code'], unique=True)

    op.create_table(
        'report_code_reservations',
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('code'),
    )

    op.create_table(
        'report_versions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('report_id', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('version_label', sa.String(), nullable=True),
        sa.Column('template_ext', sa.String(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(), nullable=False),
        sa.Column('original_filename', sa.String(), nullable=True),
        sa.Column('fields', sa.JSON(), nullable=True),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('backfilled', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_by_user_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['reports.report_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('report_id', 'version', name='uq_report_versions_report_version'),
        sa.UniqueConstraint('report_id', 'version_label', name='uq_report_versions_report_label'),
    )
    op.create_index('ix_report_versions_report_id', 'report_versions', ['report_id'], unique=False)

    op.create_table(
        'image_resources',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('folder_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=False),
        sa.Column('file_ext', sa.String(), nullable=False),
        sa.Column('width_px', sa.Integer(), nullable=False),
        sa.Column('height_px', sa.Integer(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['folder_id'], ['folders.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'stylesheet_resources',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('folder_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['folder_id'], ['folders.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ---- who may open which folder / report ---------------------------------
    op.create_table(
        'folder_access_grants',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('folder_id', sa.String(), nullable=False),
        sa.Column('subject_type', sa.String(), nullable=False),
        sa.Column('subject_id', sa.String(), nullable=False),
        sa.Column('permission_level', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.String(), nullable=True),
        sa.Column('granted_by', sa.String(), nullable=True),
        sa.Column('granted_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['folder_id'], ['folders.id']),
        sa.ForeignKeyConstraint(['granted_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'report_access_grants',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('report_id', sa.String(), nullable=False),
        sa.Column('subject_type', sa.String(), nullable=False),
        sa.Column('subject_id', sa.String(), nullable=False),
        sa.Column('permission_level', sa.String(), nullable=False),
        sa.Column('parameter_limits', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.String(), nullable=True),
        sa.Column('granted_by', sa.String(), nullable=True),
        sa.Column('granted_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['reports.report_id']),
        sa.ForeignKeyConstraint(['granted_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ---- data sources, embedding clients, protected terms -------------------
    op.create_table(
        'data_connections',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_data_connections_org_name'),
    )
    op.create_index('ix_data_connections_org_id', 'data_connections', ['org_id'], unique=False)

    op.create_table(
        'secrets',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('value_encrypted', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_secrets_org_name'),
    )
    op.create_index('ix_secrets_org_id', 'secrets', ['org_id'], unique=False)

    op.create_table(
        'jdbc_drivers',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('engine', sa.String(), nullable=False),
        sa.Column('driver_class', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('sha256', sa.String(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_jdbc_drivers_org_name'),
    )
    op.create_index('ix_jdbc_drivers_org_id', 'jdbc_drivers', ['org_id'], unique=False)

    op.create_table(
        'auth_sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('refresh_hash', sa.String(), nullable=False),
        sa.Column('previous_hash', sa.String(), nullable=True),
        sa.Column('rotated_at', sa.String(), nullable=True),
        sa.Column('remember', sa.Boolean(), nullable=False),
        sa.Column('ip_address', sa.String(), nullable=True),
        sa.Column('user_agent', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('last_used_at', sa.String(), nullable=False),
        sa.Column('expires_at', sa.String(), nullable=False),
        sa.Column('revoked_at', sa.String(), nullable=True),
        sa.Column('revoked_reason', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('refresh_hash'),
    )
    op.create_index('ix_auth_sessions_previous_hash', 'auth_sessions', ['previous_hash'], unique=False)
    op.create_index('ix_auth_sessions_user_active', 'auth_sessions', ['user_id', 'revoked_at'], unique=False)

    op.create_table(
        'api_clients',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('secret_hash', sa.String(), nullable=False),
        sa.Column('secret_prefix', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('secret_rotated_at', sa.String(), nullable=True),
        sa.Column('last_used_at', sa.String(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_api_clients_client_id', 'api_clients', ['client_id'], unique=True)

    op.create_table(
        'api_client_reports',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('client_pk', sa.String(), nullable=False),
        sa.Column('report_id', sa.String(), nullable=False),
        sa.Column('granted_by', sa.String(), nullable=True),
        sa.Column('granted_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['client_pk'], ['api_clients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['report_id'], ['reports.report_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['granted_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_pk', 'report_id', name='uq_api_client_reports'),
    )
    op.create_index('ix_api_client_reports_client_pk', 'api_client_reports', ['client_pk'], unique=False)
    op.create_index('ix_api_client_reports_report_id', 'api_client_reports', ['report_id'], unique=False)

    op.create_table(
        'protected_term_sets',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('terms', sa.JSON(), nullable=False),
        sa.Column('exclude_terms', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'deployment_protected_terms',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('terms', sa.JSON(), nullable=False),
        sa.Column('exclude_terms', sa.JSON(), nullable=False),
        sa.Column('source_paths', sa.JSON(), nullable=False),
        sa.Column('synced_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # ---- scheduled jobs -----------------------------------------------------
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('job_type', sa.String(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('trigger_type', sa.String(), nullable=False),
        sa.Column('cron_expression', sa.String(), nullable=True),
        sa.Column('interval_seconds', sa.Integer(), nullable=True),
        sa.Column('run_at', sa.String(), nullable=True),
        sa.Column('start_date', sa.String(), nullable=True),
        sa.Column('end_date', sa.String(), nullable=True),
        sa.Column('max_retries', sa.Integer(), nullable=False),
        sa.Column('retry_backoff_seconds', sa.Integer(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('apscheduler_job_id', sa.String(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'job_runs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('triggered_by', sa.String(), nullable=False),
        sa.Column('triggered_by_user_id', sa.String(), nullable=True),
        sa.Column('celery_task_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.String(), nullable=True),
        sa.Column('finished_at', sa.String(), nullable=True),
        sa.Column('result_summary', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id']),
        sa.ForeignKeyConstraint(['triggered_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ---- activity & audit trails --------------------------------------------
    op.create_table(
        'auth_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('ip_address', sa.String(), nullable=True),
        sa.Column('user_agent', sa.String(), nullable=True),
        sa.Column('is_new_device', sa.Boolean(), nullable=False),
        sa.Column('acknowledged', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('last_seen_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'access_denied_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('permission_code', sa.String(), nullable=False),
        sa.Column('resource', sa.String(), nullable=True),
        sa.Column('ip_address', sa.String(), nullable=True),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'report_render_log',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('report_id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('format', sa.String(), nullable=False),
        sa.Column('backend', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('triggered_by', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['reports.report_id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'audit_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('actor_user_id', sa.String(), nullable=True),
        sa.Column('actor_username', sa.String(), nullable=False),
        sa.Column('ip_address', sa.String(), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('entity_id', sa.String(), nullable=False),
        sa.Column('entity_label', sa.String(), nullable=True),
        sa.Column('summary', sa.String(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_events_action', 'audit_events', ['action'], unique=False)
    op.create_index('ix_audit_events_created', 'audit_events', ['created_at'], unique=False)
    op.create_index('ix_audit_events_entity', 'audit_events', ['entity_type', 'entity_id', 'created_at'], unique=False)
    op.create_index('ix_audit_events_org_created', 'audit_events', ['org_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Reverse of upgrade(); dropping a table drops its indexes with it.
    for table in (
        'audit_events',
        'auth_sessions',
        'jdbc_drivers',
        'secrets',
        'report_render_log',
        'access_denied_events',
        'auth_events',
        'job_runs',
        'jobs',
        'deployment_protected_terms',
        'protected_term_sets',
        'api_client_reports',
        'api_clients',
        'data_connections',
        'report_access_grants',
        'folder_access_grants',
        'stylesheet_resources',
        'image_resources',
        'report_versions',
        'report_code_reservations',
        'reports',
        'folders',
        'ldap_group_role_mappings',
        'ldap_configs',
        'user_permission_grants',
        'user_role_assignments',
        'role_permissions',
        'roles',
        'permissions',
        'user_settings',
        'users',
        'organizations',
    ):
        op.drop_table(table)
