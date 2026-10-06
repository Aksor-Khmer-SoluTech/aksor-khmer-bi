"""Resolves `{"image_id": ..., "width_mm": ...}` spec dicts inside a
render context into `{"image_bytes": ..., "width_mm": ...}` before the
context reaches doc_engine.render() -- doc_engine has no database/
filesystem access to the image store (see doc_engine.images' module
docstring), so this is the one seam where an uploaded image's
*reference* becomes its actual *bytes*. Called from both
routers/reports.py's `_render_one` and job_executors.py's
`_render_bytes` -- the two places that already build a render context --
so neither duplicates this logic.

Scoping: an image can only be referenced by a report in the *same* org
as the image. Checked here rather than by requiring caller auth, because
rendering itself stays public/unauthenticated by design (see
routers/reports.py's module docstring) -- there's no caller identity to
check an image against, only the report being rendered, so its own org
is the trust boundary this enforces. A report with no org at all (a
pre-RBAC-migration row -- see db/reports.py) can't reference any image;
there's no boundary to check it against, so it fails closed rather than
silently allowing any image through.
"""
from __future__ import annotations

from typing import Any

from . import image_store


class ImageResolutionError(ValueError):
    """Raised when a context references an image_id that doesn't exist,
    isn't a real image anymore, or belongs to a different org than the
    report being rendered.
    """


def _is_image_ref(value: object) -> bool:
    return isinstance(value, dict) and isinstance(value.get("image_id"), str)


def resolve_image_refs(context: dict[str, Any], report_org_id: str | None) -> dict[str, Any]:
    """Return a copy of `context` with every `{"image_id": ...}` spec
    replaced by `{"image_bytes": ..., "width_mm": ...}`. Values that
    aren't image specs (including plain dicts/lists/scalars) pass
    through unchanged, recursively.
    """
    return _walk(context, report_org_id)


def _walk(value: Any, report_org_id: str | None) -> Any:
    if _is_image_ref(value):
        image_id = value["image_id"]
        try:
            meta = image_store.get_image(image_id)
        except image_store.ImageNotFoundError:
            raise ImageResolutionError(f"image_id {image_id!r} not found")
        if report_org_id is None or meta["org_id"] != report_org_id:
            raise ImageResolutionError(f"image_id {image_id!r} does not belong to this report's organization")
        resolved: dict[str, Any] = {"image_bytes": image_store.get_image_bytes(image_id)}
        if "width_mm" in value:
            resolved["width_mm"] = value["width_mm"]
        return resolved
    if isinstance(value, list):
        return [_walk(v, report_org_id) for v in value]
    if isinstance(value, dict):
        return {k: _walk(v, report_org_id) for k, v in value.items()}
    return value
