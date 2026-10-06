"""Discriminator for an already-resolved image reference in a render
context -- see docs/building-a-report.md's "Images" section for the full
picture. Unlike charts.py, this module never touches image *bytes*
itself: doc_engine has no database/filesystem access to an uploaded
image store, so resolving an `image_id` to actual bytes happens one
layer up, in api/app/context_media.py, before the context ever reaches
doc_engine.render(). By the time a value gets here it's already
`{"image_bytes": b"...", "width_mm": 40}` -- this module only recognizes
that shape and (in engines/libreoffice_engine.py) turns it into an
InlineImage, the same way charts.is_chart_spec's dict gets turned into
one.
"""
from __future__ import annotations

DEFAULT_WIDTH_MM = 40


def is_image_spec(value: object) -> bool:
    """True for an already-resolved image reference: a dict carrying raw
    `image_bytes`. (The caller-facing spec shape before resolution is
    `{"image_id": "...", "width_mm": ...}` -- that form is only ever seen
    by api/app/context_media.py, never by doc_engine itself.)
    """
    return isinstance(value, dict) and isinstance(value.get("image_bytes"), (bytes, bytearray))
