"""Glue between doc_engine and aksor_khmer_ocr_segmenter.

Kept as its own module so the engines never import aksor_khmer_ocr_segmenter
directly — if a caller doesn't need segmentation (e.g. non-Khmer content),
this is the one place to stub out.
"""
from __future__ import annotations

from typing import Sequence

from aksor_khmer_ocr_segmenter import process_text

from .charts import is_chart_spec
from .images import is_image_spec


def segment_generic(value, extra_terms: Sequence[str] | None = None, exclude_terms: Sequence[str] | None = None):
    """Recursively apply Khmer word-segmentation to every string in an
    arbitrary JSON-like structure (dict/list/str/other).

    Used for user-supplied report templates, where there's no fixed field
    list to allowlist from — every string is a candidate, since we don't
    know ahead of time which placeholders in an uploaded docx hold
    free-text Khmer content.

    `extra_terms`/`exclude_terms` pass straight through to
    aksor_khmer_ocr_segmenter.process_text on every call this recursion
    makes -- a per-render protected-terms layer (see registry.render())
    on top of that package's own deployment-wide default, not a
    replacement for it.
    """
    if isinstance(value, str):
        return process_text(value, extra_terms=extra_terms, exclude_terms=exclude_terms)
    if isinstance(value, list):
        return [segment_generic(v, extra_terms, exclude_terms) for v in value]
    if isinstance(value, dict):
        if is_chart_spec(value) or is_image_spec(value):
            # Chart specs mix structural keys ("chart", "width_mm") with
            # display text (title, labels) in the same dict -- blindly
            # segmenting would corrupt the "chart" type discriminator,
            # and chart text is short/non-wrapping so ZWSP break points
            # serve no purpose there anyway. An already-resolved image
            # spec's "image_bytes" is binary, not prose -- segmenting it
            # would just corrupt raw bytes. Both left untouched; resolved
            # by engines/libreoffice_engine.py after this step.
            return value
        return {k: segment_generic(v, extra_terms, exclude_terms) for k, v in value.items()}
    return value
