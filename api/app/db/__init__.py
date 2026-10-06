"""SQLAlchemy engine/session/models, one module per domain (reports,
rbac, ldap, jobs) instead of one growing db.py -- mirrors the same split
app/models/ just got. `Base`/`SessionLocal`/`engine`/every table class are
re-exported here so every existing `from .. import db` + `db.User` (or
`from app.db import User`) call site keeps working unchanged.

Scope, deliberately narrow: this isn't "move everything into Postgres" --
it's a real transactional store for the platform's own bookkeeping (which
reports/users/roles/jobs exist), not a data warehouse for report content
(callers still supply that JSON every render call -- see
docs/why-aksor-khmer-bi.md's "no data connectors" positioning). The
actual `.docx`/`.xlsx` template *files* stay on the filesystem under
report_store.STORE_DIR, untouched by this schema.

`DATABASE_URL` selects the backend:
  - unset -> `sqlite:///./aksor_khmer_bi.db` (zero-setup local dev -- no
    server to run just to try the API out)
  - `postgresql+psycopg://...` -> the real backend for anything beyond a
    laptop (see docker-compose.yml's `postgres` service)
Both dialects are exercised by the test suite (api/tests/conftest.py
points every test at its own throwaway SQLite file).

IMPORTANT for Alembic: every submodule is imported eagerly below (not
lazily on first attribute access) specifically so that `from app.db
import Base` -- what migrations/env.py does to get `target_metadata` --
registers every table on `Base.metadata`, not just whichever ones some
other import path happened to have touched first.
"""
from .base import Base, DATABASE_URL, SessionLocal, _gen_id, engine
from .audit import AuditEvent
from .clients import ApiClient, ApiClientReport
from .connections import DataConnection
from .jdbc_drivers import JdbcDriver
from .secrets import Secret
from .auth_events import AuthEvent
from .auth_sessions import AuthSession
from .deployment_terms import DeploymentProtectedTerms
from .folders import Folder, FolderAccessGrant, ImageResource, StylesheetResource
from .jobs import Job, JobRun
from .ldap import LdapConfig, LdapGroupRoleMapping
from .protected_terms import ProtectedTermSet
from .render_events import RenderEvent
from .security_events import AccessDeniedEvent
from .rbac import (
    Organization,
    Permission,
    ReportAccessGrant,
    Role,
    RolePermission,
    User,
    UserPermissionGrant,
    UserRoleAssignment,
)
from .report_versions import ReportVersion
from .reports import CodeReservation, ReportRow
from .user_settings import UserSetting

__all__ = [
    "AccessDeniedEvent",
    "ApiClient",
    "ApiClientReport",
    "AuditEvent",
    "AuthEvent",
    "AuthSession",
    "Base",
    "CodeReservation",
    "DATABASE_URL",
    "DataConnection",
    "Secret",
    "DeploymentProtectedTerms",
    "Folder",
    "FolderAccessGrant",
    "ImageResource",
    "Job",
    "JdbcDriver",
    "JobRun",
    "LdapConfig",
    "LdapGroupRoleMapping",
    "Organization",
    "Permission",
    "ProtectedTermSet",
    "RenderEvent",
    "ReportAccessGrant",
    "ReportRow",
    "ReportVersion",
    "Role",
    "RolePermission",
    "SessionLocal",
    "StylesheetResource",
    "User",
    "UserPermissionGrant",
    "UserRoleAssignment",
    "UserSetting",
    "_gen_id",
    "engine",
]
