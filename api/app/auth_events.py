"""Login auditing: parses a User-Agent into (browser, os, device_type)
with no third-party dependency, and records success/failure rows into
AuthEvent -- see app/db/auth_events.py for the table shape and why a
"session" here is really a throttled (user, ip_address, user_agent)
fingerprint rather than a literal server-side session.

Hooked from exactly one place, routers/auth.py's /auth/verify -- the
portal calls that once per page load and once per login-form submit
(see that router's own docstring), not on every single API request the
way app/auth.py's Basic Auth check runs. Recording there instead of in
get_current_user keeps this off the hot path of every report render/list
call, at the cost of only auditing "the portal noticed you were signed
in" rather than literally every authenticated request -- the right
trade-off for a human-readable sign-in log instead of a request log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import AuthEvent, User

# A returning device's fingerprint (user_id, ip_address, user_agent)
# renews its existing row's last_seen_at instead of inserting a new one
# as long as it was last seen within this window -- keeps "sign-in
# activity" readable (roughly one row per real sitting at the console)
# instead of one row per page load/tab.
SESSION_RENEW_WINDOW = timedelta(minutes=15)


@dataclass(frozen=True)
class ParsedUserAgent:
    browser: str
    os: str
    device_type: str  # "desktop" | "mobile" | "tablet"


# Order matters: Edge/Opera/Chrome all include "Safari" and/or "Chrome"
# tokens in their UA string for compatibility, so the more specific
# browser must be checked first or everything misreports as Chrome.
_BROWSER_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("Edge", re.compile(r"Edg(?:A|iOS)?/([\d.]+)")),
    ("Opera", re.compile(r"(?:OPR|Opera)/([\d.]+)")),
    ("Chrome", re.compile(r"Chrome/([\d.]+)")),
    ("Firefox", re.compile(r"Firefox/([\d.]+)")),
    ("Safari", re.compile(r"Version/([\d.]+).*Safari")),
)

_OS_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("Windows", re.compile(r"Windows NT ([\d.]+)")),
    ("iPadOS", re.compile(r"CPU OS ([\d_]+) like Mac OS X")),
    ("iOS", re.compile(r"iPhone OS ([\d_]+)")),
    ("macOS", re.compile(r"Mac OS X ([\d_.]+)")),
    ("Android", re.compile(r"Android ([\d.]+)")),
    ("Linux", re.compile(r"Linux")),
)


def parse_user_agent(user_agent: str | None) -> ParsedUserAgent:
    """Small, dependency-free UA sniff -- covers the handful of browsers/
    OSes an internal reporting portal's users actually show up with.
    Falls back to "Unknown" rather than guessing when nothing matches,
    same spirit as security.verify_password treating a malformed hash as
    "doesn't match" rather than raising.
    """
    ua = user_agent or ""

    browser = "Unknown"
    for name, pattern in _BROWSER_PATTERNS:
        m = pattern.search(ua)
        if m:
            browser = f"{name} {m.group(1)}"
            break

    os_name = "Unknown"
    for name, pattern in _OS_PATTERNS:
        if pattern.search(ua):
            os_name = name
            break

    if "iPad" in ua or "Tablet" in ua:
        device_type = "tablet"
    elif "Mobile" in ua:
        device_type = "mobile"
    else:
        device_type = "desktop"

    return ParsedUserAgent(browser=browser, os=os_name, device_type=device_type)


def client_ip(request: Request) -> str | None:
    """The direct peer, unless a reverse proxy set X-Forwarded-For (see
    docs/deployment.md's "add a reverse proxy" note) -- takes its first
    hop, the original client, not the proxy itself.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def record_login_success(session: Session, user: User, ip_address: str | None, user_agent: str | None) -> AuthEvent:
    """Renew the matching fingerprint's row if one's still within
    SESSION_RENEW_WINDOW, else insert a new one -- flagged is_new_device
    if this exact fingerprint has genuinely never succeeded for this user
    before (any age), which is what the Notifications bell surfaces.
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - SESSION_RENEW_WINDOW).isoformat()
    existing = (
        session.execute(
            select(AuthEvent)
            .where(
                AuthEvent.user_id == user.id,
                AuthEvent.success.is_(True),
                AuthEvent.ip_address == ip_address,
                AuthEvent.user_agent == user_agent,
                AuthEvent.last_seen_at >= cutoff,
            )
            .order_by(AuthEvent.last_seen_at.desc())
        )
        .scalars()
        .first()
    )
    if existing is not None:
        existing.last_seen_at = now.isoformat()
        session.commit()
        return existing

    # `.first()`, not `.scalar_one_or_none()` -- over time a real device
    # naturally accumulates *many* prior success rows for the same
    # fingerprint (a fresh row opens each time SESSION_RENEW_WINDOW
    # lapses between sign-ins), so "more than one match" is the normal
    # case here, not an error -- this only ever asks "does at least one
    # exist," never "exactly one."
    seen_before = session.execute(
        select(AuthEvent.id)
        .where(
            AuthEvent.user_id == user.id,
            AuthEvent.success.is_(True),
            AuthEvent.ip_address == ip_address,
            AuthEvent.user_agent == user_agent,
        )
        .limit(1)
    ).scalar_one_or_none()

    event = AuthEvent(
        user_id=user.id,
        org_id=user.org_id,
        username=user.username,
        success=True,
        ip_address=ip_address,
        user_agent=user_agent,
        is_new_device=seen_before is None,
        created_at=now.isoformat(),
        last_seen_at=now.isoformat(),
    )
    session.add(event)
    session.commit()
    return event


def record_login_failure(
    session: Session, username: str, org_id: str | None, ip_address: str | None, user_agent: str | None
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    session.add(
        AuthEvent(
            user_id=None,
            org_id=org_id,
            username=username,
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=now,
            last_seen_at=now,
        )
    )
    session.commit()
