"""Login auditing: parses a User-Agent into (browser, os, device_type)
with no third-party dependency, and records success/failure rows into
AuthEvent -- see app/db/auth_events.py for the table shape and why a
"session" here is really a throttled (user, ip_address, user_agent)
fingerprint rather than a literal server-side session.

Hooked from routers/auth.py: the portal's /auth/login (one row per
sign-in, tied to the session it opened and the browser's device cookie)
and the older HTTP Basic /auth/verify that scripts use -- not from every
authenticated API request, so this stays a human-readable sign-in log
rather than a request log.
"""
from __future__ import annotations

import hashlib
import re
import secrets
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


# Browsers that send another browser's User-Agent but name themselves in the Sec-CH-UA client hint
# ('"Brave";v="152", "Chromium";v="152", "Not_A Brand";v="24"'). Chrome's own brand, Chromium and the deliberately
# junk "Not A Brand" entries are skipped: the User-Agent already says as much.
_HINT_BRANDS = {"Brave": "Brave", "Microsoft Edge": "Edge", "Opera": "Opera", "Vivaldi": "Vivaldi", "Samsung Internet": "Samsung Internet"}
# What the portal itself may report (X-Aksor-Browser) where client hints aren't sent -- plain http on a LAN address.
# Only names a page can actually detect (Brave exposes navigator.brave); anything else is ignored.
_PORTAL_BRANDS = {"brave": "Brave"}
_SEC_CH_UA_ENTRY = re.compile(r'"([^"]+)"\s*;\s*v="')


def browser_brand(request: Request) -> str | None:
    """The browser's real name when its User-Agent hides it (Brave's is Chrome's, unchanged), else None. For
    display only: like the User-Agent, it's whatever the browser says."""
    for name in _SEC_CH_UA_ENTRY.findall(request.headers.get("sec-ch-ua", "")):
        if name in _HINT_BRANDS:
            return _HINT_BRANDS[name]
    return _PORTAL_BRANDS.get(request.headers.get("x-aksor-browser", "").strip().lower())


def parse_user_agent(user_agent: str | None, brand: str | None = None) -> ParsedUserAgent:
    """Small, dependency-free UA sniff -- covers the handful of browsers/
    OSes an internal reporting portal's users actually show up with.
    Falls back to "Unknown" rather than guessing when nothing matches,
    same spirit as security.verify_password treating a malformed hash as
    "doesn't match" rather than raising. `brand` (see browser_brand) names
    the browser when the User-Agent can't. Versions are major only: Chrome
    and its relatives now report "152.0.0.0" whatever the real build.
    """
    ua = user_agent or ""

    browser = "Unknown"
    for name, pattern in _BROWSER_PATTERNS:
        m = pattern.search(ua)
        if m:
            browser = f"{brand or name} {m.group(1).split('.')[0]}"
            break
    else:
        if brand:
            browser = brand

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


# The browser's device id: a random value in a long-lived HttpOnly cookie (scoped to the auth routes, like the refresh
# cookie), stored server-side only as its SHA-256. It is what makes a device "known" -- not the IP address, which
# changes with every network, nor the User-Agent, which changes with every browser update.
DEVICE_COOKIE = "aksor_device"
DEVICE_COOKIE_MAX_AGE = 400 * 24 * 3600  # browsers cap cookie lifetimes at 400 days


def new_device_token() -> str:
    return secrets.token_urlsafe(32)


def device_hash(token: str | None) -> str | None:
    if not token or len(token) > 200:
        return None
    return hashlib.sha256(token.encode()).hexdigest()


def _is_new_device(session: Session, user: User, ip_address: str | None, user_agent: str | None, device: str | None) -> bool:
    """A sign-in is from a new device unless this browser (its device cookie) has signed in to this account before.
    Rows from before device cookies existed carry no device_hash; they still vouch for a browser by its exact
    ip_address + user_agent, so upgrading doesn't alert everyone once. An account's very first sign-in isn't "new":
    there is nothing to compare with, and nobody else to warn."""
    def _seen(*conditions) -> bool:
        return session.execute(
            select(AuthEvent.id).where(AuthEvent.user_id == user.id, AuthEvent.success.is_(True), *conditions).limit(1)
        ).scalar_one_or_none() is not None

    if not _seen():
        return False
    if device is not None and _seen(AuthEvent.device_hash == device):
        return False
    return not _seen(AuthEvent.ip_address == ip_address, AuthEvent.user_agent == user_agent, AuthEvent.device_hash.is_(None))


def record_login_success(
    session: Session,
    user: User,
    ip_address: str | None,
    user_agent: str | None,
    *,
    device: str | None = None,
    session_id: str | None = None,
    brand: str | None = None,
) -> AuthEvent:
    """Log a successful sign-in. A portal sign-in (`session_id` given -- it opened that session) always gets its own
    row, flagged is_new_device if this browser has never signed in to the account (see _is_new_device); `device` is
    the browser's device_hash. An HTTP Basic check (no session) renews the matching fingerprint's row if one's still
    within SESSION_RENEW_WINDOW, so a script calling /auth/verify doesn't flood the sign-in activity.
    """
    now = datetime.now(timezone.utc)
    if session_id is None:
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

    event = AuthEvent(
        user_id=user.id,
        org_id=user.org_id,
        username=user.username,
        success=True,
        ip_address=ip_address,
        user_agent=user_agent,
        is_new_device=_is_new_device(session, user, ip_address, user_agent, device),
        device_hash=device,
        session_id=session_id,
        browser_brand=brand,
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
