"""Font files on disk (data/font_resources), described by db.FontResource.

Same file-on-disk + DB-row split as images and JDBC drivers: the file is named by the row's id, never by the uploaded
filename. The folder is also where the rendering paths look for extra fonts (DOC_ENGINE_FONT_DIRS, set in
app/__init__.py): LibreOffice reads it per conversion, WeasyPrint and the chart renderer per render -- so an upload
takes effect on the next render, with no restart, in the API and in the workers (which mount the same folder).
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from . import font_info

# api/app/font_store.py -> parents[2] is the repo root, same as report_store / jdbc_drivers.
_REPO_ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = _REPO_ROOT / "data" / "font_resources"

MAX_BYTES = int(os.environ.get("FONT_MAX_MB", "20")) * 1024 * 1024


def path_for(font_id: str, ext: str) -> Path:
    return FONT_DIR / f"{font_id}.{ext}"


def read_upload(source: BinaryIO) -> bytes:
    """The whole upload, refused past MAX_BYTES (a font is a few hundred KB; CJK ones reach several MB)."""
    data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise font_info.FontError(f"That file is larger than {MAX_BYTES // (1024 * 1024)} MB -- fonts are rarely over a few")
    if not data:
        raise font_info.FontError("That file is empty")
    return data


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(font_id: str, ext: str, data: bytes) -> None:
    """Write the bytes atomically as <id>.<ext> (readable by the worker containers)."""
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=FONT_DIR, prefix=".upload.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path_for(font_id, ext))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def remove_file(font_id: str, ext: str) -> None:
    try:
        path_for(font_id, ext).unlink()
    except FileNotFoundError:
        pass
