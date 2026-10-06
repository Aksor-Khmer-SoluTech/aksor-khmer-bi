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


def _row_to_dict(row: StylesheetResource) -> dict:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "folder_id": row.folder_id,
        "name": row.name,
        "content_type": "text/css",
        "size_bytes": row.size_bytes,
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


def create_stylesheet(
    name: str,
    content: bytes,
    org_id: str,
    folder_id: str | None,
    created_by: str | None,
) -> dict:
    probe_stylesheet(content)
    stylesheet_id = db._gen_id()
    stylesheet_dir = _stylesheet_dir(stylesheet_id)
    stylesheet_dir.mkdir(parents=True, exist_ok=False)
    _stylesheet_path(stylesheet_id).write_bytes(content)

    now = datetime.now(timezone.utc).isoformat()
    row = StylesheetResource(
        id=stylesheet_id,
        org_id=org_id,
        folder_id=folder_id,
        name=name,
        size_bytes=len(content),
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    with db.SessionLocal() as session:
        session.add(row)
        session.commit()
        return _row_to_dict(row)


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
