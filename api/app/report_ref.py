"""Report codes: address a report by a human-chosen code as well as its random
id (specs/report_codes_design.md).

Two halves. The *rules* (what a code may look like) are used at write time by
report_store. The *resolution* (code -> id) is an ASGI middleware, so that
every `/api/v1/reports/{ref}/...` route -- all sixteen, plus their permission
dependencies, audit rows and logs -- keeps seeing a plain report id and none of
them needs to know codes exist.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from . import db

# 3-64 chars: lowercase letters/digits, single hyphens between them. Stricter
# than it needs to be on purpose -- codes end up in URLs, shell snippets and
# HTML attributes, and [a-z0-9-] is safe in all of them unescaped.
CODE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CODE_MIN, CODE_MAX = 3, 64

# What report_store.create_report mints: uuid4().hex[:12]. A code can never look
# like this, which is what makes "id first, then code" unambiguous.
ID_RE = re.compile(r"^[0-9a-f]{12}$")

# Fixed path segments registered before `/{report_id}` in routers/reports.py --
# a code equal to one would be unreachable by code (the static route wins) and,
# worse, look valid. Keep in sync with that router.
RESERVED = frozenset({"parse-template", "accessible", "batch-limits", "analytics"})

PREFIX = "/api/v1/reports/"


class InvalidCodeError(ValueError):
    """A proposed report code breaks the rules above (message says which)."""


def normalize(raw: str | None) -> str | None:
    """Trim and lowercase; blank means "no code" (None). Doesn't validate."""
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    return cleaned or None


def validate(code: str) -> str:
    """`code` (already normalized) if acceptable, else InvalidCodeError."""
    if not CODE_MIN <= len(code) <= CODE_MAX:
        raise InvalidCodeError(f"A code must be {CODE_MIN}–{CODE_MAX} characters")
    if not CODE_RE.match(code):
        raise InvalidCodeError(
            "A code may only use lowercase letters, digits and single hyphens between them (e.g. revenue-comparison)"
        )
    if ID_RE.match(code):
        raise InvalidCodeError("That looks like a report id — choose a code that isn't 12 hex characters")
    if code in RESERVED:
        raise InvalidCodeError(f'"{code}" is reserved')
    return code


def _lookup(code: str) -> str | None:
    with db.SessionLocal() as session:
        return session.execute(select(db.ReportRow.report_id).where(db.ReportRow.code == code)).scalar_one_or_none()


def _could_be_a_code(segment: str) -> str | None:
    """The lowercased segment if it's worth a database lookup, else None --
    which is every id, every static segment, and anything that could not be a code."""
    if not segment or ID_RE.match(segment) or segment in RESERVED:
        return None
    lowered = segment.lower()
    return lowered if CODE_MIN <= len(lowered) <= CODE_MAX and CODE_RE.match(lowered) else None


class ReportRefMiddleware:
    """Rewrites `/api/v1/reports/<code>[/...]` to `/api/v1/reports/<id>[/...]`
    before routing, when `<code>` is a valid code that exists.

    Only the substitution comes from the database -- never from the request --
    so nothing in the path can be smuggled through. A segment that isn't a known
    code is left exactly as it was and gets the same 404 an unknown id does.
    Pure ASGI (not BaseHTTPMiddleware): it changes the routing scope and nothing
    else, and adds no per-request task or buffering.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(PREFIX):
            rest = scope["path"][len(PREFIX):]
            segment, slash, tail = rest.partition("/")
            code = _could_be_a_code(segment)
            if code is not None:
                # A sync query on the event loop would stall every request behind it.
                report_id = await run_in_threadpool(_lookup, code)
                if report_id is not None:
                    scope = dict(scope)
                    scope["path"] = f"{PREFIX}{report_id}{slash}{tail}"
                    raw = scope.get("raw_path")
                    if raw:
                        raw_prefix = PREFIX.encode()
                        raw_segment, raw_slash, raw_tail = raw[len(raw_prefix):].partition(b"/")
                        scope["raw_path"] = raw_prefix + report_id.encode() + raw_slash + raw_tail
        await self.app(scope, receive, send)
