"""Registry for uploaded CSS resources -- same file-on-disk + database-row
split as image_store.py, one directory per stylesheet:

    data/stylesheet_resources/<id>/style.css  -- the bytes
    a row in the `stylesheet_resources` table (see app/db/folders.py)

The other half of "an HTML report template can point href/src at an
uploaded resource" (see app/html_template.py) -- images already had a
home in ImageResource; plain-text CSS gets this parallel, minimal store
rather than a `kind` column bolted onto ImageResource (see
StylesheetResource's docstring for why).
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from . import db
from .db import StylesheetResource

_REPO_ROOT = Path(__file__).resolve().parents[2]
STORE_DIR = _REPO_ROOT / "data" / "stylesheet_resources"

# Generous for a template stylesheet (fonts/images belong in their own
# resources, referenced from the CSS by url(), not inlined here) while
# still cheap to validate/store/serve without size limits elsewhere.
MAX_SIZE_BYTES = 512 * 1024


class StylesheetNotFoundError(Exception):
    """Raised when `stylesheet_id` has no matching registered stylesheet."""


class InvalidStylesheetError(Exception):
    """Raised when uploaded content isn't valid, reasonably-sized CSS text."""


def _stylesheet_dir(stylesheet_id: str) -> Path:
    return STORE_DIR / stylesheet_id


def _stylesheet_path(stylesheet_id: str) -> Path:
    return _stylesheet_dir(stylesheet_id) / "style.css"


def _source_path(stylesheet_id: str, source_format: str) -> Path:
    """The uploaded SCSS / Sass / Less, kept beside the compiled style.css (app/style_compile.py)."""
    return _stylesheet_dir(stylesheet_id) / f"source.{source_format}"


def _row_to_dict(row: StylesheetResource) -> dict:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "folder_id": row.folder_id,
        "name": row.name,
        "content_type": "text/css",
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "source_format": row.source_format or "css",
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def probe_stylesheet(content: bytes) -> None:
    """Cheap sanity check: decodes as UTF-8 text, non-empty, under
    MAX_SIZE_BYTES. Doesn't validate CSS grammar -- a malformed rule just
    renders as it would in any browser (ignored), same "cheap sanity
    check, not full validation" spirit as report_store.is_valid_office_file.
    """
    if len(content) == 0:
        raise InvalidStylesheetError("File is empty")
    if len(content) > MAX_SIZE_BYTES:
        raise InvalidStylesheetError(f"File exceeds the {MAX_SIZE_BYTES // 1024} KB limit for a stylesheet resource")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidStylesheetError(f"Not valid UTF-8 text: {exc}") from exc


def _compiled(content: bytes, source_format: str) -> bytes:
    """The CSS for an upload in `source_format`, checked. Raises InvalidStylesheetError (a compile error says where)."""
    from .style_compile import StyleCompileError, compile_style

    probe_stylesheet(content)
    try:
        css = compile_style(content, source_format)
    except StyleCompileError as exc:
        raise InvalidStylesheetError(str(exc)) from exc
    if not css.strip():
        raise InvalidStylesheetError("It compiles to no CSS at all -- only variables or mixins, nothing that uses them")
    probe_stylesheet(css)
    return css


def create_stylesheet(
    name: str,
    content: bytes,
    org_id: str,
    folder_id: str | None,
    created_by: str | None,
    source_format: str = "css",
) -> dict:
    """`content` as uploaded: CSS, or SCSS / Sass / Less (`source_format`) compiled to the CSS templates use -- the
    source is kept beside it. The fingerprint is the upload's own."""
    css = _compiled(content, source_format)
    stylesheet_id = db._gen_id()
    stylesheet_dir = _stylesheet_dir(stylesheet_id)
    stylesheet_dir.mkdir(parents=True, exist_ok=False)
    _stylesheet_path(stylesheet_id).write_bytes(css)
    if source_format != "css":
        _source_path(stylesheet_id, source_format).write_bytes(content)

    now = datetime.now(timezone.utc).isoformat()
    row = StylesheetResource(
        id=stylesheet_id,
        org_id=org_id,
        folder_id=folder_id,
        name=name,
        size_bytes=len(css),
        sha256=hashlib.sha256(content).hexdigest(),
        source_format=None if source_format == "css" else source_format,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    with db.SessionLocal() as session:
        session.add(row)
        session.commit()
        return _row_to_dict(row)


def replace_stylesheet_content(stylesheet_id: str, content: bytes, source_format: str | None = None) -> dict:
    """New content for an existing stylesheet, keeping its id (an edit, or a project import's "overwrite").
    `source_format` None keeps the stylesheet's own format."""
    with db.SessionLocal() as session:
        row = session.get(StylesheetResource, stylesheet_id)
        if row is None:
            raise StylesheetNotFoundError(stylesheet_id)
        fmt = source_format or row.source_format or "css"
        css = _compiled(content, fmt)
        _stylesheet_dir(stylesheet_id).mkdir(parents=True, exist_ok=True)
        for old in _stylesheet_dir(stylesheet_id).glob("source.*"):
            old.unlink()
        _stylesheet_path(stylesheet_id).write_bytes(css)
        if fmt != "css":
            _source_path(stylesheet_id, fmt).write_bytes(content)
        row.source_format = None if fmt == "css" else fmt
        row.size_bytes, row.sha256 = len(css), hashlib.sha256(content).hexdigest()
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _row_to_dict(row)


def fingerprint(stylesheet_id: str) -> str | None:
    with db.SessionLocal() as session:
        row = session.get(StylesheetResource, stylesheet_id)
        if row is None:
            raise StylesheetNotFoundError(stylesheet_id)
        if row.sha256:
            return row.sha256
        path = _stylesheet_path(stylesheet_id)
        if not path.exists():
            return None
        row.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        session.commit()
        return row.sha256


def with_content(org_id: str, sha256: str) -> list[dict]:
    with db.SessionLocal() as session:
        unprinted = session.execute(
            select(StylesheetResource.id).where(StylesheetResource.org_id == org_id, StylesheetResource.sha256.is_(None))
        ).scalars().all()
    for stylesheet_id in unprinted:
        fingerprint(stylesheet_id)
    with db.SessionLocal() as session:
        rows = session.execute(
            select(StylesheetResource).where(StylesheetResource.org_id == org_id, StylesheetResource.sha256 == sha256).order_by(StylesheetResource.name)
        ).scalars().all()
        return [_row_to_dict(r) for r in rows]


def get_stylesheet(stylesheet_id: str) -> dict:
    with db.SessionLocal() as session:
        row = session.get(StylesheetResource, stylesheet_id)
        if row is None:
            raise StylesheetNotFoundError(stylesheet_id)
        return _row_to_dict(row)


def get_stylesheet_bytes(stylesheet_id: str) -> bytes:
    meta = get_stylesheet(stylesheet_id)  # raises StylesheetNotFoundError if the row doesn't exist
    path = _stylesheet_path(stylesheet_id)
    if not path.exists():
        raise StylesheetNotFoundError(stylesheet_id)
    return path.read_bytes()


def get_stylesheet_source(stylesheet_id: str) -> tuple[bytes, str]:
    """(what was uploaded, its format): the SCSS / Sass / Less source, or the CSS itself for a plain stylesheet."""
    meta = get_stylesheet(stylesheet_id)
    fmt = meta["source_format"]
    path = _source_path(stylesheet_id, fmt) if fmt != "css" else _stylesheet_path(stylesheet_id)
    if not path.exists():
        raise StylesheetNotFoundError(stylesheet_id)
    return path.read_bytes(), fmt


def list_stylesheets(org_id: str | None = None, folder_id: str | None = None) -> list[dict]:
    with db.SessionLocal() as session:
        query = select(StylesheetResource).order_by(StylesheetResource.name)
        if org_id is not None:
            query = query.where(StylesheetResource.org_id == org_id)
        if folder_id is not None:
            query = query.where(StylesheetResource.folder_id == folder_id)
        rows = session.execute(query).scalars().all()
        return [_row_to_dict(row) for row in rows]


def delete_stylesheet(stylesheet_id: str) -> None:
    with db.SessionLocal() as session:
        row = session.get(StylesheetResource, stylesheet_id)
        if row is None:
            raise StylesheetNotFoundError(stylesheet_id)
        session.delete(row)
        session.commit()

    stylesheet_dir = _stylesheet_dir(stylesheet_id)
    if stylesheet_dir.exists():
        shutil.rmtree(stylesheet_dir)
