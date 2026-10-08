"""Registry for user-uploaded report templates: the template *file*
lives on the filesystem, its *metadata* lives in a database.

Each registered report is:
    data/report_templates/<report_id>/template.<docx|xlsx|html>  -- the file
    data/report_templates/<report_id>/versions/v<N>.<ext>        -- every version ever uploaded
    a row in the `reports` table (see app/db.py)                  -- the metadata
    a row per version in `report_versions`                        -- who/when/what changed

template.<ext> is the live copy the render path reads; versions/ holds
immutable snapshots of each upload so an earlier file (including the
original) can be downloaded again and compared. See ReportVersion in
app/db/report_versions.py.

STORE_DIR is deliberately outside the api/ codebase directory (repo
root's data/, a sibling of api/ and packages/) — runtime data shouldn't
live inside the application's own code tree; that's the same reasoning
behind api/ and portal/ being separate deployable things rather than one.

Metadata used to live in a `meta.json` file next to the template (one
JSON read-modify-write per update, no locking). Moved to a real database
(app/db.py) because that read-modify-write could race under concurrent
requests against the same report_id, and because a shared filesystem is
a more awkward thing to scale `api` against than a database is. The
template *file* stays exactly where it was — this migration is scoped to
metadata only, not "move everything into Postgres."
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session
from sqlalchemy.orm import Session

from . import db, report_ref, template_fields
from .audit import Actor
from .db import ApiClientReport, CodeReservation, ReportRow, ReportVersion

_log = logging.getLogger("aksor_khmer_bi.report_store")

# api/app/report_store.py -> parents[2] is the repo root (report_store.py
# -> app -> api -> repo root), same computation style as
# doc_engine.config.REPO_ROOT.
_REPO_ROOT = Path(__file__).resolve().parents[2]
STORE_DIR = _REPO_ROOT / "data" / "report_templates"

# The zip entry that must be present for each format — the same cheap
# "is this actually a docx/xlsx" sanity check used for both, generalized.
_REQUIRED_ZIP_ENTRY = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
}


class ReportNotFoundError(Exception):
    """Raised when `report_id` has no matching registered report."""


class CodeTakenError(Exception):
    """The report code is already claimed -- by another report, or (permanently) by
    another organization that used it before."""


class VersionNotFoundError(Exception):
    """Raised when a report has no retained file for the requested version
    (never existed, or was overwritten before version history was kept)."""


def _report_dir(report_id: str) -> Path:
    return STORE_DIR / report_id


def _template_path(report_id: str, template_ext: str) -> Path:
    return _report_dir(report_id) / f"template.{template_ext}"


def _versions_dir(report_id: str) -> Path:
    return _report_dir(report_id) / "versions"


def _version_path(report_id: str, version: int, template_ext: str) -> Path:
    return _versions_dir(report_id) / f"v{version}.{template_ext}"


VERSION_LABEL_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,31}$")


class VersionLabelError(ValueError):
    """The requested version label is malformed or already used by this report."""


def normalize_version_label(raw: str | None) -> str | None:
    """Trim, drop a leading "v", and validate. None/blank -> None (unlabelled)."""
    label = (raw or "").strip()
    if label[:1] in ("v", "V") and label[1:2].isdigit():
        label = label[1:]
    if not label:
        return None
    if not VERSION_LABEL_RE.match(label):
        raise VersionLabelError("Version may use letters, digits, '.', '-', '_' or '+' (up to 32 characters), e.g. 1.0.1")
    return label


def _current_label(row: ReportRow) -> str | None:
    session = object_session(row)
    if session is None:
        return None
    return session.scalar(
        select(ReportVersion.version_label).where(ReportVersion.report_id == row.report_id, ReportVersion.version == row.version)
    )


def _row_to_dict(row: ReportRow) -> dict:
    return {
        "report_id": row.report_id,
        "org_id": row.org_id,
        "folder_id": row.folder_id,
        "name": row.name,
        "description": row.description,
        "template_ext": row.template_ext,
        "version": row.version,
        "version_label": _current_label(row),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "sample_context": row.sample_context,
        "resource_bindings": row.resource_bindings,
        "is_public": row.is_public,
        "code": row.code,
        # Internal only -- ReportMeta (the public response model) has no
        # such fields, so these never leave through GET /reports; managers
        # read them via /reports/{id}/data-config (see report_data.py) and
        # /reports/{id}/protected-terms-config (see protected_terms_config.py).
        "parameters": row.parameters,
        "data_source": row.data_source,
        "protected_terms_config": row.protected_terms_config,
    }


def _clean_code(raw: str | None) -> str | None:
    """A caller's report code, normalized and checked (None = no code). Raises
    report_ref.InvalidCodeError. Enforced here, not just in the router, so a
    code that breaks the rules can't get in by any path."""
    code = report_ref.normalize(raw)
    return None if code is None else report_ref.validate(code)


def _claim_code(session: Session, code: str, org_id: str | None, report_id: str) -> None:
    """Make `code` available to this report or raise CodeTakenError: it isn't held
    by another report, and it hasn't ever been used by another organization
    (report_code_reservations -- what stops a freed code being picked up by another
    tenant and silently receiving the first one's traffic). The caller commits."""
    held = session.execute(select(ReportRow.report_id).where(ReportRow.code == code, ReportRow.report_id != report_id)).first()
    if held is not None:
        raise CodeTakenError(code)
    owner = org_id or ""
    reservation = session.get(CodeReservation, code)
    if reservation is None:
        session.add(CodeReservation(code=code, org_id=owner, created_at=datetime.now(timezone.utc).isoformat()))
    elif reservation.org_id != owner:
        raise CodeTakenError(code)


def resolve_ref(ref: str) -> str:
    """The report id for `ref`, which may be an id or a report code. Raises
    ReportNotFoundError for neither. (The HTTP routes never need this -- the
    middleware in report_ref.py has already swapped a code for its id -- but
    callers that take a reference from config, like scheduled jobs, do.)"""
    with db.SessionLocal() as session:
        if session.get(ReportRow, ref) is not None:
            return ref
        code = report_ref.normalize(ref)
        if code is not None:
            found = session.execute(select(ReportRow.report_id).where(ReportRow.code == code)).scalar_one_or_none()
            if found is not None:
                return found
    raise ReportNotFoundError(ref)


def is_valid_office_file(content: bytes, template_ext: str) -> bool:
    """Cheap sanity check: docx/xlsx are both zips with a specific entry
    required by their format. Doesn't validate Jinja2 placeholder syntax
    — malformed placeholders surface as a render-time error instead, same
    as the built-in notice template would.
    """
    required = _REQUIRED_ZIP_ENTRY.get(template_ext)
    if required is None:
        return False
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            return required in zf.namelist()
    except zipfile.BadZipFile:
        return False


def _detect_fields_or_none(path: Path, template_ext: str) -> list[str] | None:
    """A malformed template must stay uploadable and downloadable -- it just
    gets no field summary in the changelog."""
    try:
        return template_fields.detect_fields(path, template_ext)
    except Exception:
        _log.warning("Couldn't detect placeholder fields in %s", path, exc_info=True)
        return None


def _snapshot(
    session: Session,
    report_id: str,
    version: int,
    template_ext: str,
    content: bytes,
    *,
    created_at: str,
    actor: Actor | None = None,
    note: str | None = None,
    version_label: str | None = None,
    original_filename: str | None = None,
    backfilled: bool = False,
) -> None:
    """Keep an immutable copy of one version's file and record who put it
    there. The caller commits, so the row lands in the same transaction as
    the change to the live template."""
    path = _version_path(report_id, version, template_ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    session.add(
        ReportVersion(
            report_id=report_id,
            version=version,
            version_label=version_label,
            template_ext=template_ext,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            original_filename=original_filename,
            fields=_detect_fields_or_none(path, template_ext),
            note=note,
            created_by=actor.username if actor else None,
            created_by_user_id=actor.user_id if actor else None,
            created_at=created_at,
            backfilled=backfilled,
        )
    )


def _ensure_current_snapshot(session: Session, row: ReportRow) -> None:
    """Backfill a report registered before version history existed: its
    live file becomes its current version's snapshot, uploader unknown.
    A no-op for every report that already has one. Earlier versions of such
    a report were overwritten in place and can't be recovered -- v1 gets
    its true upload time (`created_at`), later ones only the last-modified
    time, since that's all that was kept.
    """
    already = session.execute(
        select(ReportVersion.id).where(ReportVersion.report_id == row.report_id, ReportVersion.version == row.version)
    ).first()
    if already is not None:
        return
    live = _template_path(row.report_id, row.template_ext)
    if not live.exists():
        return
    _snapshot(
        session,
        row.report_id,
        row.version,
        row.template_ext,
        live.read_bytes(),
        created_at=row.created_at if row.version == 1 else row.updated_at,
        backfilled=True,
    )


def create_report(
    name: str,
    content: bytes,
    template_ext: str,
    description: str | None = None,
    org_id: str | None = None,
    resource_bindings: dict | None = None,
    *,
    code: str | None = None,
    folder_id: str | None = None,
    actor: Actor | None = None,
    note: str | None = None,
    original_filename: str | None = None,
) -> dict:
    code = _clean_code(code)  # before any file is written
    report_id = uuid.uuid4().hex[:12]
    report_dir = _report_dir(report_id)
    report_dir.mkdir(parents=True, exist_ok=False)
    _template_path(report_id, template_ext).write_bytes(content)
    now = datetime.now(timezone.utc).isoformat()
    row = ReportRow(
        report_id=report_id,
        org_id=org_id,
        folder_id=folder_id,
        name=name,
        description=description,
        template_ext=template_ext,
        version=1,
        created_at=now,
        updated_at=now,
        sample_context=None,
        resource_bindings=resource_bindings,
        code=code,
    )
    try:
        with db.SessionLocal() as session:
            if code is not None:
                _claim_code(session, code, org_id, report_id)
            session.add(row)
            _snapshot(
                session, report_id, 1, template_ext, content,
                created_at=now, actor=actor, note=note, original_filename=original_filename,
            )
            try:
                session.commit()
            except IntegrityError as exc:  # two requests claiming the same code at once
                session.rollback()
                raise CodeTakenError(code) from exc
            return _row_to_dict(row)
    except CodeTakenError:
        shutil.rmtree(report_dir, ignore_errors=True)  # the template file was written before the claim
        raise


UNSET = object()  # sentinel: "this field wasn't part of the request at all"


def update_report_meta(
    report_id: str,
    name: str | None = None,
    description: str | None = None,
    sample_context: dict | None = None,
    folder_id: str | None = UNSET,
    is_public: bool | None = None,
    code: str | None = UNSET,
) -> dict:
    """Partial update: only overwrites fields that were actually passed.

    `code` has the same third state as `folder_id`: `UNSET` leaves
    it alone, None (or "") removes it. Raises report_ref.InvalidCodeError /
    CodeTakenError.

    `folder_id` alone distinguishes "omitted" (`UNSET`, the default --
    leave it as-is) from "explicitly null" (clear it back to root) --
    see ReportUpdate's docstring in models/reports.py for why this one
    field needs that third state and the others don't. `is_public` has
    no such third state (a boolean has no meaningful "clear" beyond
    true/false), so it follows the same `None`-means-unchanged rule as
    `name`/`description`.
    """
    with db.SessionLocal() as session:
        row = session.get(ReportRow, report_id)
        if row is None:
            raise ReportNotFoundError(report_id)
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if sample_context is not None:
            row.sample_context = sample_context
        if folder_id is not UNSET:
            row.folder_id = folder_id
        if is_public is not None:
            row.is_public = is_public
        if code is not UNSET:
            new_code = _clean_code(code)
            if new_code is not None:
                _claim_code(session, new_code, row.org_id, report_id)
            row.code = new_code
        row.updated_at = datetime.now(timezone.utc).isoformat()
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise CodeTakenError(code) from exc
        return _row_to_dict(row)


def update_data_config(report_id: str, parameters: list[dict], data_source: dict | None) -> dict:
    """Replace a report's filter-parameter definitions and data source
    wholesale (the caller has already run report_data.validate_data_config).
    Stored as null when empty so "nothing configured" has one shape.
    """
    with db.SessionLocal() as session:
        row = session.get(ReportRow, report_id)
        if row is None:
            raise ReportNotFoundError(report_id)
        row.parameters = parameters or None
        row.data_source = data_source
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _row_to_dict(row)


def update_protected_terms_config(report_id: str, config: dict) -> dict:
    """Replace a report's own protected-terms layer wholesale (the
    caller has already run
    protected_terms_config.validate_protected_terms_config). Stored as
    null when there's nothing selected/configured, same "one shape for
    nothing configured" convention update_data_config uses."""
    with db.SessionLocal() as session:
        row = session.get(ReportRow, report_id)
        if row is None:
            raise ReportNotFoundError(report_id)
        has_content = bool(config.get("set_ids") or config.get("terms") or config.get("exclude_terms"))
        row.protected_terms_config = config if has_content else None
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _row_to_dict(row)


def replace_report_file(
    report_id: str,
    content: bytes,
    template_ext: str,
    *,
    actor: Actor | None = None,
    note: str | None = None,
    original_filename: str | None = None,
    version_label: str | None = None,
) -> dict:
    """Replace the template file itself (a new version of the same
    report) — same validation the caller must run before this
    (`is_valid_office_file`) as for a fresh upload. The file being
    replaced is kept (see _ensure_current_snapshot for a report that
    predates version history) so it can still be downloaded afterwards.
    """
    with db.SessionLocal() as session:
        row = session.get(ReportRow, report_id)
        if row is None:
            raise ReportNotFoundError(report_id)

        # Before anything is overwritten: a report from before version
        # history keeps the file it's about to lose.
        _ensure_current_snapshot(session, row)

        version_label = normalize_version_label(version_label)
        if version_label is not None and session.scalar(
            select(ReportVersion.id).where(ReportVersion.report_id == report_id, ReportVersion.version_label == version_label)
        ):
            raise VersionLabelError(f"This template already has a version {version_label}")

        old_ext = row.template_ext
        now = datetime.now(timezone.utc).isoformat()
        row.template_ext = template_ext
        row.version += 1
        row.updated_at = now
        _snapshot(
            session, report_id, row.version, template_ext, content,
            created_at=now, actor=actor, note=note, original_filename=original_filename,
            version_label=version_label,
        )
        try:
            session.flush()  # the unique label constraint fires here, before the live file is touched
        except IntegrityError as exc:
            session.rollback()
            raise VersionLabelError(f"This template already has a version {version_label}") from exc

        if old_ext != template_ext:
            old_path = _template_path(report_id, old_ext)
            if old_path.exists():
                old_path.unlink()
        _template_path(report_id, template_ext).write_bytes(content)
        session.commit()
        return _row_to_dict(row)


def _version_to_dict(row: ReportVersion, previous: ReportVersion | None, live_exists: bool) -> dict:
    """One version as the API shows it, with what changed against the
    version before it (`previous`, the next-lower retained one)."""
    fields = row.fields
    prev_fields = previous.fields if previous is not None else None
    if fields is not None and prev_fields is not None:
        fields_added = [f for f in fields if f not in prev_fields]
        fields_removed = [f for f in prev_fields if f not in fields]
    else:
        fields_added = fields_removed = None  # unknown: first retained version, or detection failed
    return {
        "version": row.version,
        "version_label": row.version_label,
        "template_ext": row.template_ext,
        "size_bytes": row.size_bytes,
        "size_delta": row.size_bytes - previous.size_bytes if previous is not None else None,
        "sha256": row.sha256,
        "original_filename": row.original_filename,
        "note": row.note,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "backfilled": row.backfilled,
        "fields": fields,
        "fields_added": fields_added,
        "fields_removed": fields_removed,
        "identical_to_previous": previous is not None and previous.sha256 == row.sha256,
        "available": live_exists,
    }


def update_version(report_id: str, version: int, changes: dict) -> tuple[dict, dict]:
    """Edit a retained version's label and/or note (the only mutable parts --
    the file itself never changes). `changes` holds only the keys to touch.
    Returns (before, after) for the audit diff."""
    with db.SessionLocal() as session:
        if session.get(ReportRow, report_id) is None:
            raise ReportNotFoundError(report_id)
        row = session.scalar(select(ReportVersion).where(ReportVersion.report_id == report_id, ReportVersion.version == version))
        if row is None:
            raise VersionNotFoundError(f"{report_id} v{version}")
        before = {"version_label": row.version_label, "note": row.note}
        if "version_label" in changes:
            label = normalize_version_label(changes["version_label"])
            if label is not None and session.scalar(
                select(ReportVersion.id).where(
                    ReportVersion.report_id == report_id, ReportVersion.version_label == label, ReportVersion.version != version
                )
            ):
                raise VersionLabelError(f"This template already has a version {label}")
            row.version_label = label
        if "note" in changes:
            row.note = (changes["note"] or "").strip() or None
        try:
            session.commit()
        except IntegrityError as exc:  # lost a race for the label
            session.rollback()
            raise VersionLabelError(f"This template already has a version {changes.get('version_label')}") from exc
        return before, {"version_label": row.version_label, "note": row.note}


def list_versions(report_id: str) -> list[dict]:
    """Every retained version of `report_id`'s file, newest first. Only
    versions with a row are listed -- a report that was replaced before
    version history existed simply starts at a later number (the gap is
    real: those files were overwritten and are gone)."""
    with db.SessionLocal() as session:
        report = session.get(ReportRow, report_id)
        if report is None:
            raise ReportNotFoundError(report_id)
        _ensure_current_snapshot(session, report)
        session.commit()
        rows = session.execute(
            select(ReportVersion).where(ReportVersion.report_id == report_id).order_by(ReportVersion.version)
        ).scalars().all()

        out: list[dict] = []
        previous: ReportVersion | None = None
        for row in rows:
            if row.version == report.version:
                exists = _template_path(report_id, report.template_ext).exists()
            else:
                exists = _version_path(report_id, row.version, row.template_ext).exists()
            out.append(_version_to_dict(row, previous, exists))
            previous = row
        out.reverse()
        return out


def get_version_file(report_id: str, version: int | None = None) -> tuple[Path, dict]:
    """(path to the file, its version info) for `version`, or the current
    version when None. The current version is served from the live
    template.<ext> the renderer itself uses; older ones from versions/."""
    with db.SessionLocal() as session:
        report = session.get(ReportRow, report_id)
        if report is None:
            raise ReportNotFoundError(report_id)
        _ensure_current_snapshot(session, report)
        session.commit()
        wanted = report.version if version is None else version
        info = session.execute(
            select(ReportVersion).where(ReportVersion.report_id == report_id, ReportVersion.version == wanted)
        ).scalar_one_or_none()
        if info is None:
            raise VersionNotFoundError(f"{report_id} v{wanted}")
        if wanted == report.version:
            path = _template_path(report_id, report.template_ext)
        else:
            path = _version_path(report_id, wanted, info.template_ext)
        if not path.exists():
            raise VersionNotFoundError(f"{report_id} v{wanted}")
        return path, _version_to_dict(info, None, True)


def get_report(report_id: str) -> dict:
    with db.SessionLocal() as session:
        row = session.get(ReportRow, report_id)
        if row is None:
            raise ReportNotFoundError(report_id)
        return _row_to_dict(row)


def get_template_path(report_id: str) -> Path:
    meta = get_report(report_id)  # raises ReportNotFoundError if the row doesn't exist
    path = _template_path(meta["report_id"], meta["template_ext"])
    if not path.exists():
        raise ReportNotFoundError(report_id)
    return path


def list_reports(org_id: str | None = None) -> list[dict]:
    """`org_id=None` lists every report regardless of owner -- used for a
    superuser view; route handlers scope this to the caller's own org
    (see routers/reports.py) unless the caller is a break-glass superuser.
    """
    with db.SessionLocal() as session:
        query = select(ReportRow).order_by(ReportRow.report_id)
        if org_id is not None:
            query = query.where(ReportRow.org_id == org_id)
        rows = session.execute(query).scalars().all()
        return [_row_to_dict(row) for row in rows]


def delete_report(report_id: str) -> None:
    with db.SessionLocal() as session:
        row = session.get(ReportRow, report_id)
        if row is None:
            raise ReportNotFoundError(report_id)
        session.execute(delete(ReportVersion).where(ReportVersion.report_id == report_id))
        session.execute(delete(db.ReportShortcut).where(db.ReportShortcut.report_id == report_id))
        # Not left to the FK's ON DELETE CASCADE: SQLite ignores foreign keys unless asked to.
        session.execute(delete(ApiClientReport).where(ApiClientReport.report_id == report_id))
        session.delete(row)
        session.commit()

    report_dir = _report_dir(report_id)
    if report_dir.exists():
        shutil.rmtree(report_dir)
