"""Registry for uploaded image resources -- same file-on-disk +
database-row split as report_store.py, one directory per image:

    data/image_resources/<image_id>/<file>   -- the bytes
    a row in the `image_resources` table (see app/db/folders.py)  -- the metadata

STORE_DIR sits next to report_store.STORE_DIR under the repo-root data/
directory, for the same reason: runtime data doesn't belong inside the
application's own code tree.
"""
from __future__ import annotations

import hashlib
import io
import shutil
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from . import db
from .db import ImageResource

_REPO_ROOT = Path(__file__).resolve().parents[2]
STORE_DIR = _REPO_ROOT / "data" / "image_resources"


class ImageNotFoundError(Exception):
    """Raised when `image_id` has no matching registered image."""


class InvalidImageError(Exception):
    """Raised when uploaded content doesn't decode as a real image."""


def _image_dir(image_id: str) -> Path:
    return STORE_DIR / image_id


def _image_path(image_id: str, file_ext: str) -> Path:
    return _image_dir(image_id) / f"image.{file_ext}"


def _row_to_dict(row: ImageResource) -> dict:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "folder_id": row.folder_id,
        "name": row.name,
        "content_type": row.content_type,
        "file_ext": row.file_ext,
        "width_px": row.width_px,
        "height_px": row.height_px,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def probe_image(content: bytes) -> tuple[int, int, str]:
    """Verify `content` actually decodes as an image and return
    (width_px, height_px, content_type). Raises InvalidImageError
    otherwise -- same "cheap sanity check, not full validation" spirit as
    report_store.is_valid_office_file.
    """
    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
        # verify() leaves the file object unusable for further reads, so
        # re-open for the width/height/format Pillow discards after verify.
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
            content_type = Image.MIME.get(img.format or "", "application/octet-stream")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImageError(str(exc)) from exc
    return width, height, content_type


def create_image(
    name: str,
    content: bytes,
    org_id: str,
    folder_id: str | None,
    created_by: str | None,
) -> dict:
    width_px, height_px, content_type = probe_image(content)
    file_ext = (content_type.split("/")[-1] or "bin").lower()
    image_id = db._gen_id()
    image_dir = _image_dir(image_id)
    image_dir.mkdir(parents=True, exist_ok=False)
    _image_path(image_id, file_ext).write_bytes(content)

    now = datetime.now(timezone.utc).isoformat()
    row = ImageResource(
        id=image_id,
        org_id=org_id,
        folder_id=folder_id,
        name=name,
        content_type=content_type,
        file_ext=file_ext,
        width_px=width_px,
        height_px=height_px,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    with db.SessionLocal() as session:
        session.add(row)
        session.commit()
        return _row_to_dict(row)


def replace_image_content(image_id: str, content: bytes) -> dict:
    """New bytes for an existing image, keeping its id -- so every template that points at it gets the new picture
    (a project import's "overwrite"). Raises ImageNotFoundError / InvalidImageError."""
    width_px, height_px, content_type = probe_image(content)
    file_ext = (content_type.split("/")[-1] or "bin").lower()
    with db.SessionLocal() as session:
        row = session.get(ImageResource, image_id)
        if row is None:
            raise ImageNotFoundError(image_id)
        old = _image_path(image_id, row.file_ext)
        _image_dir(image_id).mkdir(parents=True, exist_ok=True)
        _image_path(image_id, file_ext).write_bytes(content)
        if old != _image_path(image_id, file_ext) and old.exists():
            old.unlink()
        row.content_type, row.file_ext, row.width_px, row.height_px = content_type, file_ext, width_px, height_px
        row.size_bytes, row.sha256 = len(content), hashlib.sha256(content).hexdigest()
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _row_to_dict(row)


_KEEP = object()


def update_image_meta(resource_id: str, *, name: str | None = None, folder_id: object = _KEEP) -> dict:
    """Rename and/or move (folder_id None = the organization's top level); the file and its id stay the same."""
    with db.SessionLocal() as session:
        row = session.get(ImageResource, resource_id)
        if row is None:
            raise ImageNotFoundError(resource_id)
        if name is not None:
            row.name = name
        if folder_id is not _KEEP:
            row.folder_id = folder_id
        row.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _row_to_dict(row)


def fingerprint(image_id: str) -> str | None:
    """The image's sha256, worked out and kept the first time for a row from before fingerprints. None if its file
    is gone."""
    with db.SessionLocal() as session:
        row = session.get(ImageResource, image_id)
        if row is None:
            raise ImageNotFoundError(image_id)
        if row.sha256:
            return row.sha256
        path = _image_path(image_id, row.file_ext)
        if not path.exists():
            return None
        row.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        session.commit()
        return row.sha256


def with_content(org_id: str, sha256: str) -> list[dict]:
    """The organization's images holding exactly this content (older rows fingerprinted on the way)."""
    with db.SessionLocal() as session:
        unprinted = session.execute(select(ImageResource.id).where(ImageResource.org_id == org_id, ImageResource.sha256.is_(None))).scalars().all()
    for image_id in unprinted:
        fingerprint(image_id)
    with db.SessionLocal() as session:
        rows = session.execute(select(ImageResource).where(ImageResource.org_id == org_id, ImageResource.sha256 == sha256).order_by(ImageResource.name)).scalars().all()
        return [_row_to_dict(r) for r in rows]


def get_image(image_id: str) -> dict:
    with db.SessionLocal() as session:
        row = session.get(ImageResource, image_id)
        if row is None:
            raise ImageNotFoundError(image_id)
        return _row_to_dict(row)


def get_image_bytes(image_id: str) -> bytes:
    meta = get_image(image_id)  # raises ImageNotFoundError if the row doesn't exist
    path = _image_path(image_id, meta["file_ext"])
    if not path.exists():
        raise ImageNotFoundError(image_id)
    return path.read_bytes()


def list_images(org_id: str | None = None, folder_id: str | None = None) -> list[dict]:
    with db.SessionLocal() as session:
        query = select(ImageResource).order_by(ImageResource.name)
        if org_id is not None:
            query = query.where(ImageResource.org_id == org_id)
        if folder_id is not None:
            query = query.where(ImageResource.folder_id == folder_id)
        rows = session.execute(query).scalars().all()
        return [_row_to_dict(row) for row in rows]


def delete_image(image_id: str) -> None:
    with db.SessionLocal() as session:
        row = session.get(ImageResource, image_id)
        if row is None:
            raise ImageNotFoundError(image_id)
        session.delete(row)
        session.commit()

    image_dir = _image_dir(image_id)
    if image_dir.exists():
        shutil.rmtree(image_dir)
