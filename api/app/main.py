import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, dev_env, totp
from .schema_check import check_schema_version
from .deployment_terms_sync import record_change as record_deployment_terms_change
from .deployment_terms_sync import snapshot as deployment_terms_snapshot
from .deployment_terms_sync import sync_deployment_terms
from .error_middleware import UnhandledErrorMiddleware
from .logging_config import configure_logging
from .report_ref import ReportRefMiddleware
from .rbac import seed_defaults
from .render_errors import RenderError, render_error_handler
from .routers import (
    audit,
    auth,
    clients,
    connections,
    example_lookups,
    folders,
    fonts,
    grants,
    images,
    jdbc,
    jobs,
    ldap,
    me,
    organizations,
    protected_term_sets,
    reports,
    roles,
    secrets,
    security,
    stylesheets,
    system,
    users,
)

# Runs at import time (before app/router setup) so every `_log.*` call made
# during startup, and every request afterwards, goes through a configured
# root logger -- see logging_config.py for why this is needed at all.
configure_logging(service="api")

if dev_env.loaded():
    logging.getLogger("aksor_khmer_bi.dev_env").info(
        "Filled from api/.env (names only, real environment variables win): %s", ", ".join(dev_env.loaded())
    )


@asynccontextmanager
async def _lifespan(_: FastAPI):
    # Say so, loudly and specifically, if the database is behind (or on a squashed-away migration) -- before
    # the first request trips over a missing table.
    check_schema_version()
    # Bootstrap the permission catalog, the system admin role, and the
    # default root organization's standard roles -- idempotent, see
    # app/rbac.py. Runs on every startup so a fresh database (or a fresh
    # Alembic-migrated-but-unseeded one) is immediately usable.
    with db.SessionLocal() as session:
        seed_defaults(session)
        # Authenticator-app secrets saved before they were encrypted at rest: encrypt them in place.
        totp.encrypt_legacy_secrets(session)
        # Read-only audit mirror of the deployment-wide protected-terms
        # floor (env-var-pointed files) -- does not affect rendering, see
        # deployment_terms_sync.py.
        before_terms = deployment_terms_snapshot(session)
        synced_terms = sync_deployment_terms(session)
        session.commit()
    record_deployment_terms_change(before_terms, synced_terms)
    yield


app = FastAPI(
    title="Aksor Khmer Document Generation API",
    description=(
        "Register your own .docx or .xlsx template (Jinja2 placeholders) "
        "via /api/v1/reports and render it against arbitrary JSON data, no "
        "fixed schema — manage templates via the separate portal service "
        "(../portal), or call the API directly. Khmer free-text fields are "
        "passed through ICU-based word segmentation before rendering, so "
        "line-breaking/justify hold up regardless of field length. Swagger "
        "UI at /docs, ReDoc at /redoc. See docs/building-a-report.md."
    ),
    version="1.0.0-beta.2",
    lifespan=_lifespan,
)

# Report codes: rewrites /api/v1/reports/<code>/... to the report's id before
# routing (see report_ref.py). Added before CORS so CORS ends up outermost and
# answers a preflight without this middleware ever touching the database.
app.add_middleware(ReportRefMiddleware)
# Added before CORS, so it sits inside it: an unhandled error still answers with the CORS headers (see error_middleware.py).
app.add_middleware(UnhandledErrorMiddleware)

# The portal is a separate deployable instance (its own origin), so its cross-origin fetch()
# calls need this -- see docs/deployment.md. Two things here exist for the sign-in flow
# (app/auth_tokens.py): `allow_credentials` so the browser may send the HttpOnly refresh
# cookie to /api/v1/auth/* (the portal asks for it only there), and the X-Aksor-Client header
# those two cookie-driven routes require. Credentials need an explicit origin list, never "*".
_cors_origins = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials="*" not in _cors_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Aksor-Client"],
        # Not readable cross-origin unless exposed: the portal reads the
        # download's file name and how many files a split report has.
        expose_headers=["Content-Disposition", "X-Report-Parts", "X-Report-Part", "X-Report-Name", "X-Report-Ext"],
    )

app.include_router(example_lookups.router)
app.include_router(reports.router)
app.include_router(auth.router)
app.include_router(organizations.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(clients.router)
app.include_router(connections.router)
app.include_router(grants.router)
app.add_exception_handler(RenderError, render_error_handler)
app.include_router(ldap.router)
app.include_router(jobs.router)
app.include_router(system.router)
app.include_router(folders.router)
app.include_router(images.router)
app.include_router(stylesheets.router)
app.include_router(security.router)
app.include_router(me.router)
app.include_router(audit.router)
app.include_router(protected_term_sets.router)
app.include_router(secrets.router)
app.include_router(jdbc.router)
app.include_router(fonts.router)


@app.get("/api/v1/health", tags=["health"], summary="Liveness check")
def health() -> dict:
    return {"status": "ok"}
