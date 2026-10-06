import base64
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import auth_tokens, db, report_store, secret_store
from app.rbac import ROOT_ORG_ID, SYSTEM_ADMIN_ROLE_NAME, seed_defaults
from app.security import hash_password

TEST_USERNAME = "testadmin"
TEST_PASSWORD = "testpass123"


@pytest.fixture(autouse=True)
def isolated_report_store(tmp_path, monkeypatch):
    """Point the report registry at a throwaway directory (for template
    files) and a throwaway SQLite database (for metadata/RBAC) for each
    test, instead of the real data/report_templates/ and DATABASE_URL —
    otherwise test runs would accumulate real reports, or race against
    each other on a shared database.

    A real file-backed SQLite database (not `:memory:`) — every DB
    consumer (report_store, rbac, ...) opens its own `with
    db.SessionLocal() as session:` block, i.e. a fresh connection per
    call, and an in-memory SQLite database is private to the connection
    that created it unless you opt into a shared/static pool. A tmp_path
    file sidesteps that entirely and is just as fast for a per-test
    schema this small.

    `SessionLocal` is patched on the `db` module itself (not on each
    consumer module) so every module that does `db.SessionLocal()`
    picks up the same throwaway engine, rather than needing a separate
    monkeypatch per module.
    """
    monkeypatch.setattr(report_store, "STORE_DIR", tmp_path / "report_templates")
    # Stored credentials are encrypted with a key that would otherwise be
    # generated into the repo's real data/secrets/ on first use.
    monkeypatch.setattr(secret_store, "KEY_FILE", tmp_path / "secrets" / "master.key")
    monkeypatch.delenv(secret_store.KEY_ENV, raising=False)
    # Same for the access-token signing key, and a fresh key per test.
    monkeypatch.setattr(auth_tokens, "KEY_FILE", tmp_path / "secrets" / "jwt.key")
    monkeypatch.setattr(auth_tokens, "_key_cache", None)
    # Sign-in throttling is per process and per (address, user name): a fresh slate for every test.
    from app.routers import auth as auth_routes

    auth_routes._per_account.reset()
    auth_routes._per_address.reset()
    for name in ("LOGIN_ATTEMPTS_PER_MINUTE", "JWT_SECRET", "AUTH_ALLOW_BASIC", "ACCESS_TOKEN_TTL_SECONDS", "AUTH_COOKIE_SECURE", "AUTH_COOKIE_SAMESITE"):
        monkeypatch.delenv(name, raising=False)

    test_engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.Base.metadata.create_all(test_engine)
    TestSessionLocal = sessionmaker(bind=test_engine, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", TestSessionLocal)

    with TestSessionLocal() as session:
        seed_defaults(session)
        session.commit()


@pytest.fixture(autouse=True)
def portal_auth_env(monkeypatch):
    """Configure portal credentials for every test by default, so tests
    that don't care about auth (most of them) don't have to think about
    it. Tests that specifically exercise the "auth not configured" path
    use monkeypatch.delenv themselves to override this.
    """
    monkeypatch.setenv("PORTAL_USERNAME", TEST_USERNAME)
    monkeypatch.setenv("PORTAL_PASSWORD", TEST_PASSWORD)


@pytest.fixture
def auth_headers():
    """Authorization header for TEST_USERNAME/TEST_PASSWORD, matching
    whatever portal_auth_env just configured."""
    token = base64.b64encode(f"{TEST_USERNAME}:{TEST_PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def make_local_user():
    """Factory fixture: create a `local`-auth database user (in
    ROOT_ORG_ID unless org_id is given) with the given standard role
    names already assigned (non-expiring), for tests that exercise
    database-backed auth/RBAC rather than the break-glass credential.
    Returns (user_id, auth_headers).
    """

    def _make(username: str, password: str, role_names: tuple[str, ...] = (), org_id: str = ROOT_ORG_ID) -> tuple[str, dict]:
        now = datetime.now(timezone.utc).isoformat()
        with db.SessionLocal() as session:
            user = db.User(
                org_id=org_id,
                username=username,
                auth_source="local",
                password_hash=hash_password(password),
                is_active=True,
                is_locked=False,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            session.flush()

            for role_name in role_names:
                query = select(db.Role).where(db.Role.name == role_name)
                query = (
                    query.where(db.Role.org_id.is_(None))
                    if role_name == SYSTEM_ADMIN_ROLE_NAME
                    else query.where(db.Role.org_id == org_id)
                )
                role = session.execute(query).scalar_one_or_none()
                assert role is not None, f"role {role_name!r} not seeded for org {org_id!r}"
                session.add(
                    db.UserRoleAssignment(user_id=user.id, role_id=role.id, granted_at=now, is_active=True)
                )

            session.commit()
            user_id = user.id

        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return user_id, {"Authorization": f"Basic {token}"}

    return _make
