"""Personal profile-photo storage for Settings > Profile -- deliberately
separate from app/image_store.py's ImageResource registry: that one is
an org-scoped, folder-organized *shared* resource (report template
images, permissioned via report:view/folder:manage), while an avatar is
1:1 with exactly one user, always self-service, and needs no folder,
name, or independent lifecycle of its own -- just a file keyed by
user_id, and a `User.avatar_content_type` column to say whether it
exists (see app/db/rbac.py).

Every upload is re-encoded (never stored as the caller's original
bytes): downscaled to fit within _MAX_DIMENSION and re-saved as PNG or
JPEG. That's not just size control -- it also strips embedded metadata
(EXIF, XMP) and rules out anything that isn't decodable as a raster
image (an SVG with an embedded <script>, for instance) the same way
image_store.probe_image's decode-or-reject check does for shared images.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError

_REPO_ROOT = Path(__file__).resolve().parents[2]
AVATAR_DIR = _REPO_ROOT / "data" / "avatars"

_MAX_DIMENSION = 512
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB -- generous for a phone photo, bounded against abuse
_EXT_BY_CONTENT_TYPE = {"image/png": "png", "image/jpeg": "jpg"}


class InvalidImageError(Exception):
    """Raised when uploaded content doesn't decode as a real image, or
    exceeds _MAX_UPLOAD_BYTES."""


class AvatarNotFoundError(Exception):
    """Raised when `user_id` has no avatar file on disk (the caller
    should have already checked User.avatar_content_type is not None --
    this means that column and the filesystem have drifted)."""


def _avatar_path(user_id: str, content_type: str) -> Path:
    return AVATAR_DIR / f"{user_id}.{_EXT_BY_CONTENT_TYPE[content_type]}"


def save_avatar(user_id: str, content: bytes) -> str:
    """Validate, downscale, and store `content` as this user's avatar.
    Returns the stored content_type ("image/png" or "image/jpeg") to
    save onto User.avatar_content_type. Replaces any previous avatar for
    this user, including one stored under a different extension.
    """
    if len(content) > _MAX_UPLOAD_BYTES:
        raise InvalidImageError(f"Image must be at most {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    try:
        with Image.open(io.BytesIO(content)) as probe:
            probe.verify()
        # verify() leaves the file object unusable for further reads
        # (same Pillow quirk image_store.probe_image works around) --
        # re-open to actually process the pixels.
        with Image.open(io.BytesIO(content)) as img:
            img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
            img.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION))
            has_alpha = img.mode == "RGBA"
            buf = io.BytesIO()
            if has_alpha:
                img.save(buf, format="PNG", optimize=True)
                content_type = "image/png"
            else:
                img.save(buf, format="JPEG", quality=88)
                content_type = "image/jpeg"
            encoded = buf.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImageError(str(exc)) from exc

    delete_avatar(user_id)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    _avatar_path(user_id, content_type).write_bytes(encoded)
    return content_type


def get_avatar_bytes(user_id: str, content_type: str) -> bytes:
    path = _avatar_path(user_id, content_type)
    if not path.exists():
        raise AvatarNotFoundError(user_id)
    return path.read_bytes()


def delete_avatar(user_id: str) -> None:
    """Idempotent -- removes whichever extension (if any) exists,
    silently no-ops if there's nothing to remove."""
    for ext in _EXT_BY_CONTENT_TYPE.values():
        path = AVATAR_DIR / f"{user_id}.{ext}"
        if path.exists():
            path.unlink()
