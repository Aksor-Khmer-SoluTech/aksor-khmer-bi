from datetime import datetime, timedelta, timezone

from app import db
from app.rbac import (
    ROOT_ORG_ID,
    SYSTEM_ADMIN_ROLE_NAME,
    find_user_for_login,
    get_effective_permissions,
    has_report_access,
    parse_login_identifier,
    user_holds_system_admin_role,
)
from app.security import hash_password


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def _past() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _make_user(session, username="alice", org_id=ROOT_ORG_ID) -> db.User:
    user = db.User(
        org_id=org_id,
        username=username,
        auth_source="local",
        password_hash=hash_password("pw"),
        is_active=True,
        is_locked=False,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(user)
    session.flush()
    return user


def _get_role(session, name, org_id=ROOT_ORG_ID) -> db.Role:
    from sqlalchemy import select

    return session.execute(select(db.Role).where(db.Role.org_id == org_id, db.Role.name == name)).scalar_one()


# --- seeding -------------------------------------------------------------


def test_seed_defaults_is_idempotent():
    from app.rbac import seed_defaults

    with db.SessionLocal() as session:
        seed_defaults(session)
        seed_defaults(session)
        session.commit()
        permission_count = session.query(db.Permission).count()
        role_count = session.query(db.Role).count()
    assert permission_count > 0
    assert role_count > 0


def test_root_org_has_standard_roles_seeded():
    with db.SessionLocal() as session:
        names = {
            r.name
            for r in session.query(db.Role).filter(db.Role.org_id == ROOT_ORG_ID).all()
        }
    assert names == {"ROLE_ORG_ADMIN", "ROLE_REPORT_ADMIN", "ROLE_REPORT_VIEWER", "ROLE_JOB_OPERATOR", "ROLE_USER"}


def test_system_admin_role_is_org_less_and_has_every_permission():
    with db.SessionLocal() as session:
        from sqlalchemy import select

        role = session.execute(
            select(db.Role).where(db.Role.org_id.is_(None), db.Role.name == SYSTEM_ADMIN_ROLE_NAME)
        ).scalar_one()
        granted = {
            rp.permission_code
            for rp in session.query(db.RolePermission).filter(db.RolePermission.role_id == role.id).all()
        }
        all_codes = {p.code for p in session.query(db.Permission).all()}
    assert granted == all_codes


# --- login identifier parsing -------------------------------------------


def test_parse_login_identifier_plain():
    assert parse_login_identifier("alice") == ("alice", None)


def test_parse_login_identifier_with_org():
    assert parse_login_identifier("alice|acme") == ("alice", "acme")


def test_find_user_for_login_disambiguates_by_org():
    with db.SessionLocal() as session:
        org2 = db.Organization(id="org2", name="Org Two", is_active=True, created_at=_now())
        session.add(org2)
        session.flush()
        _make_user(session, "shared_name", org_id=ROOT_ORG_ID)
        _make_user(session, "shared_name", org_id="org2")
        session.commit()

        # Same username in two orgs, unqualified -> ambiguous -> None.
        assert find_user_for_login(session, "shared_name") is None
        # Qualified -> resolves to exactly the right one.
        found = find_user_for_login(session, "shared_name|org2")
        assert found is not None
        assert found.org_id == "org2"


def test_find_user_for_login_unknown_user_returns_none():
    with db.SessionLocal() as session:
        assert find_user_for_login(session, "nobody") is None


def test_find_user_for_login_ignores_inactive_users():
    with db.SessionLocal() as session:
        user = _make_user(session, "disabled_user")
        user.is_active = False
        session.commit()
        assert find_user_for_login(session, "disabled_user") is None


# --- effective permission resolution + expiry ---------------------------


def test_get_effective_permissions_via_role():
    with db.SessionLocal() as session:
        user = _make_user(session)
        role = _get_role(session, "ROLE_REPORT_VIEWER")
        session.add(db.UserRoleAssignment(user_id=user.id, role_id=role.id, granted_at=_now(), is_active=True))
        session.commit()
        perms = get_effective_permissions(session, user)
    assert perms == {"report:view", "report:render"}


def test_get_effective_permissions_excludes_expired_role_grant():
    with db.SessionLocal() as session:
        user = _make_user(session)
        role = _get_role(session, "ROLE_REPORT_VIEWER")
        session.add(
            db.UserRoleAssignment(user_id=user.id, role_id=role.id, granted_at=_now(), expires_at=_past(), is_active=True)
        )
        session.commit()
        perms = get_effective_permissions(session, user)
    assert perms == set()


def test_get_effective_permissions_includes_unexpired_role_grant():
    with db.SessionLocal() as session:
        user = _make_user(session)
        role = _get_role(session, "ROLE_REPORT_VIEWER")
        session.add(
            db.UserRoleAssignment(
                user_id=user.id, role_id=role.id, granted_at=_now(), expires_at=_future(), is_active=True
            )
        )
        session.commit()
        perms = get_effective_permissions(session, user)
    assert "report:view" in perms


def test_get_effective_permissions_excludes_revoked_grant():
    with db.SessionLocal() as session:
        user = _make_user(session)
        role = _get_role(session, "ROLE_REPORT_VIEWER")
        session.add(db.UserRoleAssignment(user_id=user.id, role_id=role.id, granted_at=_now(), is_active=False))
        session.commit()
        perms = get_effective_permissions(session, user)
    assert perms == set()


def test_get_effective_permissions_via_direct_grant():
    with db.SessionLocal() as session:
        user = _make_user(session)
        session.add(
            db.UserPermissionGrant(user_id=user.id, permission_code="job:trigger", granted_at=_now(), is_active=True)
        )
        session.commit()
        perms = get_effective_permissions(session, user)
    assert perms == {"job:trigger"}


def test_get_effective_permissions_excludes_expired_direct_grant():
    with db.SessionLocal() as session:
        user = _make_user(session)
        session.add(
            db.UserPermissionGrant(
                user_id=user.id, permission_code="job:trigger", granted_at=_now(), expires_at=_past(), is_active=True
            )
        )
        session.commit()
        perms = get_effective_permissions(session, user)
    assert perms == set()


def test_user_holds_system_admin_role_true_only_for_that_role():
    with db.SessionLocal() as session:
        user = _make_user(session)
        assert user_holds_system_admin_role(session, user) is False

        from sqlalchemy import select

        admin_role = session.execute(
            select(db.Role).where(db.Role.org_id.is_(None), db.Role.name == SYSTEM_ADMIN_ROLE_NAME)
        ).scalar_one()
        session.add(
            db.UserRoleAssignment(user_id=user.id, role_id=admin_role.id, granted_at=_now(), is_active=True)
        )
        session.commit()
        assert user_holds_system_admin_role(session, user) is True


# --- report-specific access grants ---------------------------------------


def _make_report(session, report_id="rep1", org_id=ROOT_ORG_ID) -> db.ReportRow:
    row = db.ReportRow(
        report_id=report_id,
        org_id=org_id,
        name="Test",
        template_ext="docx",
        version=1,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(row)
    session.flush()
    return row


def test_has_report_access_direct_user_grant():
    with db.SessionLocal() as session:
        user = _make_user(session)
        report = _make_report(session)
        session.add(
            db.ReportAccessGrant(
                subject_type="user",
                subject_id=user.id,
                report_id=report.report_id,
                permission_level="manage",
                granted_at=_now(),
                is_active=True,
            )
        )
        session.commit()

        from app.rbac import AuthContext

        ctx = AuthContext(username=user.username, is_superuser=False, user=user)
        assert has_report_access(session, ctx, report.report_id, "manage") is True
        assert has_report_access(session, ctx, report.report_id, "view") is True  # manage covers view too


def test_has_report_access_view_grant_does_not_cover_manage():
    with db.SessionLocal() as session:
        user = _make_user(session)
        report = _make_report(session)
        session.add(
            db.ReportAccessGrant(
                subject_type="user",
                subject_id=user.id,
                report_id=report.report_id,
                permission_level="view",
                granted_at=_now(),
                is_active=True,
            )
        )
        session.commit()

        from app.rbac import AuthContext

        ctx = AuthContext(username=user.username, is_superuser=False, user=user)
        assert has_report_access(session, ctx, report.report_id, "view") is True
        assert has_report_access(session, ctx, report.report_id, "manage") is False


def test_has_report_access_expired_grant_is_ignored():
    with db.SessionLocal() as session:
        user = _make_user(session)
        report = _make_report(session)
        session.add(
            db.ReportAccessGrant(
                subject_type="user",
                subject_id=user.id,
                report_id=report.report_id,
                permission_level="manage",
                granted_at=_now(),
                expires_at=_past(),
                is_active=True,
            )
        )
        session.commit()

        from app.rbac import AuthContext

        ctx = AuthContext(username=user.username, is_superuser=False, user=user)
        assert has_report_access(session, ctx, report.report_id, "view") is False


def test_has_report_access_public_report_grants_view_within_org():
    with db.SessionLocal() as session:
        user = _make_user(session)
        report = _make_report(session)
        report.is_public = True
        session.commit()

        from app.rbac import AuthContext

        ctx = AuthContext(username=user.username, is_superuser=False, user=user, org_id=ROOT_ORG_ID)
        assert has_report_access(session, ctx, report.report_id, "view") is True
        assert has_report_access(session, ctx, report.report_id, "render") is False
        assert has_report_access(session, ctx, report.report_id, "manage") is False


def test_has_report_access_public_report_in_another_org_does_not_grant_view():
    with db.SessionLocal() as session:
        session.add(db.Organization(id="other-org", name="Other", is_active=True, created_at=_now()))
        session.flush()
        user = _make_user(session, org_id="other-org")
        report = _make_report(session)  # org_id=ROOT_ORG_ID
        report.is_public = True
        session.commit()

        from app.rbac import AuthContext

        ctx = AuthContext(username=user.username, is_superuser=False, user=user, org_id="other-org")
        assert has_report_access(session, ctx, report.report_id, "view") is False


def test_has_report_access_non_public_report_grants_nothing_by_default():
    with db.SessionLocal() as session:
        user = _make_user(session)
        report = _make_report(session)
        session.commit()

        from app.rbac import AuthContext

        ctx = AuthContext(username=user.username, is_superuser=False, user=user, org_id=ROOT_ORG_ID)
        assert has_report_access(session, ctx, report.report_id, "view") is False


def test_has_report_access_via_role_grant():
    with db.SessionLocal() as session:
        user = _make_user(session)
        report = _make_report(session)
        role = _get_role(session, "ROLE_REPORT_VIEWER")
        session.add(db.UserRoleAssignment(user_id=user.id, role_id=role.id, granted_at=_now(), is_active=True))
        session.add(
            db.ReportAccessGrant(
                subject_type="role",
                subject_id=role.id,
                report_id=report.report_id,
                permission_level="render",
                granted_at=_now(),
                is_active=True,
            )
        )
        session.commit()

        from app.rbac import AuthContext

        ctx = AuthContext(username=user.username, is_superuser=False, user=user)
        assert has_report_access(session, ctx, report.report_id, "render") is True
