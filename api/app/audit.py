"""Change audit trail: the writer, the "what changed" diff helpers, and the
query the feeds share. Table shape and why it has no foreign keys:
app/db/audit.py.

Usage from a route -- build an Actor once, then record after the change
has committed:

    actor = audit.Actor.of(context, request)
    ...do the change...
    audit.record(
        actor, "user.update", "user", user.id,
        label=user.username, org_id=user.org_id,
        summary=f"Updated user {user.username}",
        changes=audit.diff(before, after, ["display_name", "is_active"]),
    )

Same never-block posture as app/render_log.py and app/security_events.py:
a failure to write the audit row is logged (loudly) and swallowed, never
turned into a failed request for the person doing legitimate work. The
trade-off is real -- a database outage that spares the change but eats
its audit row leaves a gap -- and is the same one the login and
access-denied trails already make. The *file history* of a template is
not best-effort: it's data the download feature depends on, written in
the same transaction as the change (see report_store.py).

Secrets never reach the table: every value is passed through redact()
on its way in, and a changed secret is recorded as "changed" without its
before/after (see diff()).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from . import db

_log = logging.getLogger("aksor_khmer_bi.audit")

REDACTED = "[redacted]"

# Key names whose values are credentials. Matched against the *key*, not the
# value, so it can't be fooled by what a secret happens to look like.
# `body_template` is here not because it is a secret but because it's free
# text a manager wrote for a POST body, and free text is where an API key
# ends up pasted.
_SENSITIVE_KEY_RE = re.compile(
    r"password|passwd|passphrase|secret|token|authorization|api[_-]?key|credential|cookie|private[_-]?key|totp|bind_pw|body_template",
    re.IGNORECASE,
)


def _is_sensitive(path: str) -> bool:
    """Is the value at dotted `path` (or bare key) one to hide? Every value
    under a `headers` mapping is (their *names* stay visible -- that an
    `Authorization` header exists is the useful part, and a header called
    `X-Portal-Auth` is a credential no name regex could know). A key ending
    in `_env` or `_secret` is the *name* of an environment variable or a
    Secret (see DataSourceAuth.password_env/.password_secret) that holds the
    actual value, which is exactly what an investigator wants to see, so
    it's exempt from the name match.
    """
    parts = path.split(".")
    if "headers" in parts[:-1]:
        return True
    key = parts[-1].lower()
    if key.endswith("_env") or key.endswith("_secret"):
        return False
    return bool(_SENSITIVE_KEY_RE.search(key))

_MAX_TEXT = 1000  # chars kept of any one string value
_MAX_LIST = 100  # items kept of any one added/removed list


@dataclass(frozen=True)
class Actor:
    """Who did it -- resolved once per request and handed to whatever
    writes the rows, so the store functions don't need an AuthContext or a
    Request just to say "by whom, from where"."""

    username: str
    user_id: str | None = None
    org_id: str | None = None
    ip_address: str | None = None

    @classmethod
    def of(cls, context: Any, request: Any = None) -> "Actor":
        # Imported here, not at module top: auth_events pulls in rbac,
        # which pulls in db -- fine at call time, needless at import time.
        from .auth_events import client_ip

        return cls(
            username=context.username,
            user_id=context.user.id if context.user else None,
            org_id=context.org_id,
            ip_address=client_ip(request) if request is not None else None,
        )


# Work the platform does on its own (a scheduler tick, a startup sync).
SYSTEM = Actor(username="system")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# --- Redaction and diffing --------------------------------------------------


def redact(value: Any, key: str = "") -> Any:
    """`value` with anything credential-shaped replaced by REDACTED.

    See _is_sensitive for what counts.
    """
    if _is_sensitive(key):
        return REDACTED if value not in (None, "", [], {}) else value
    if isinstance(value, dict):
        if key.lower() == "headers":
            return {k: REDACTED for k in value}
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, key) for v in value]
    return value


def _clip(value: Any) -> Any:
    """Bound one scalar's stored size and make it JSON-safe."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + f"… (+{len(text) - _MAX_TEXT} chars)"


def _is_scalar_list(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and all(not isinstance(v, (dict, list, tuple)) for v in value)


def _flatten(value: Any, prefix: str) -> dict[str, Any]:
    """{"a": {"b": 1}} -> {"a.b": 1}, so a nested config change reads as the
    one leaf that moved rather than "the whole object is different"."""
    if isinstance(value, dict) and value:
        out: dict[str, Any] = {}
        for k, v in value.items():
            out.update(_flatten(v, f"{prefix}.{k}"))
        return out
    return {prefix: value}


def opaque_change(field: str) -> dict[str, Any]:
    """A change worth noting whose value isn't worth storing (a bulky
    sample payload): "this changed", nothing more."""
    return {"field": field, "opaque": True}


def _change(field: str, before: Any, after: Any) -> dict[str, Any]:
    key = field.rsplit(".", 1)[-1]
    if _is_sensitive(field):
        # Say it changed; never say from/to what.
        return {"field": field, "before": REDACTED if before else None, "after": REDACTED if after else None, "redacted": True}
    if isinstance(before, (list, tuple)) or isinstance(after, (list, tuple)):
        b, a = list(before or []), list(after or [])
        if _is_scalar_list(b) and _is_scalar_list(a):
            added = [x for x in a if x not in b]
            removed = [x for x in b if x not in a]
            return {
                "field": field,
                "added": [_clip(x) for x in added[:_MAX_LIST]],
                "removed": [_clip(x) for x in removed[:_MAX_LIST]],
                "added_count": len(added),
                "removed_count": len(removed),
            }
    return {"field": field, "before": _clip(redact(before, key)), "after": _clip(redact(after, key))}


def diff(before: dict[str, Any], after: dict[str, Any], fields: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    """The fields (of `fields`) whose value differs between two dicts, as
    [{"field", "before", "after"}, ...]. Dict-valued fields are compared
    leaf by leaf ("data_source.url"); lists of plain values (terms,
    permission codes) come back as added/removed rather than two whole
    lists. Compared on the *raw* values, redacted only afterwards -- so a
    changed password is reported as changed even though both sides print
    as [redacted].
    """
    changes: list[dict[str, Any]] = []
    for field in fields:
        b, a = before.get(field), after.get(field)
        if b == a:
            continue
        if isinstance(b, dict) or isinstance(a, dict):
            flat_b = _flatten(b, field) if isinstance(b, dict) else {field: b}
            flat_a = _flatten(a, field) if isinstance(a, dict) else {field: a}
            for path in sorted(set(flat_b) | set(flat_a)):
                if flat_b.get(path) != flat_a.get(path):
                    changes.append(_change(path, flat_b.get(path), flat_a.get(path)))
            continue
        changes.append(_change(field, b, a))
    return changes


def named_list_change(field: str, before: list | None, after: list | None, key: str = "name") -> dict[str, Any] | None:
    """A change entry for a list of dicts identified by `key` (a report's
    filter parameters), summarised as which were added, removed or edited
    -- or None if nothing differs."""
    b = {str(item.get(key)): item for item in (before or []) if isinstance(item, dict)}
    a = {str(item.get(key)): item for item in (after or []) if isinstance(item, dict)}
    added = [n for n in a if n not in b]
    removed = [n for n in b if n not in a]
    modified = [n for n in a if n in b and a[n] != b[n]]
    if not (added or removed or modified):
        return None
    return {
        "field": field,
        "added": added[:_MAX_LIST],
        "removed": removed[:_MAX_LIST],
        "modified": modified[:_MAX_LIST],
        "added_count": len(added),
        "removed_count": len(removed),
    }


# --- Writing ------------------------------------------------------------------


def record(
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: str,
    *,
    summary: str,
    label: str | None = None,
    org_id: str | None = None,
    changes: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append one audit row. Never raises (see the module docstring)."""
    try:
        with db.SessionLocal() as session:
            session.add(
                db.AuditEvent(
                    created_at=_now(),
                    actor_user_id=actor.user_id,
                    actor_username=actor.username,
                    ip_address=actor.ip_address,
                    org_id=org_id if org_id is not None else actor.org_id,
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_label=_clip(label) if label is not None else None,
                    summary=_clip(summary),
                    changes=changes or None,
                    details=redact(details) if details else None,
                )
            )
            session.commit()
    except Exception:
        _log.exception("Failed to record audit event action=%r entity=%s/%s", action, entity_type, entity_id)


# --- Reading ------------------------------------------------------------------


def event_to_dict(row: db.AuditEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at,
        "actor_username": row.actor_username,
        "actor_user_id": row.actor_user_id,
        "ip_address": row.ip_address,
        "org_id": row.org_id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "entity_label": row.entity_label,
        "summary": row.summary,
        "changes": row.changes,
        "details": row.details,
    }


def _filtered(
    *,
    org_id: str | None,
    entity_type: str | None,
    entity_id: str | None,
    action: str | None,
    actor: str | None,
    q: str | None,
    since: str | None,
    until: str | None,
) -> Select:
    query = select(db.AuditEvent)
    if org_id is not None:
        query = query.where(db.AuditEvent.org_id == org_id)
    if entity_type:
        query = query.where(db.AuditEvent.entity_type == entity_type)
    if entity_id:
        query = query.where(db.AuditEvent.entity_id == entity_id)
    if action:
        # "report" matches every report.*; a full "report.file_replace" is exact.
        query = query.where(or_(db.AuditEvent.action == action, db.AuditEvent.action.like(f"{_like_escape(action)}.%", escape="\\")))
    if actor:
        query = query.where(db.AuditEvent.actor_username.ilike(f"%{_like_escape(actor)}%", escape="\\"))
    if q:
        pattern = f"%{_like_escape(q)}%"
        query = query.where(
            or_(
                db.AuditEvent.summary.ilike(pattern, escape="\\"),
                db.AuditEvent.entity_label.ilike(pattern, escape="\\"),
                db.AuditEvent.entity_id.ilike(pattern, escape="\\"),
            )
        )
    if since:
        query = query.where(db.AuditEvent.created_at >= since)
    if until:
        query = query.where(db.AuditEvent.created_at <= until)
    return query


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_events(
    session: Session,
    *,
    org_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    q: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """(page of events newest first, total matching). `org_id=None` means
    every org -- callers scope non-superusers before they get here."""
    query = _filtered(
        org_id=org_id, entity_type=entity_type, entity_id=entity_id, action=action, actor=actor, q=q, since=since, until=until
    )
    total = session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = (
        session.execute(query.order_by(db.AuditEvent.created_at.desc(), db.AuditEvent.id.desc()).limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return [event_to_dict(r) for r in rows], total
