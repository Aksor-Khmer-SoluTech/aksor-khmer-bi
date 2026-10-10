"""End-to-end pipeline: OCR (or raw text) -> word-segmented, break-ready text.

Typical use case in a document-templating flow: a placeholder value turns
out longer than the field was designed for, or arrives from an OCR'd scan
with no word spacing. Run it through `process_text`/`process_image` before
handing it to the template renderer so the layout engine has real break
points to wrap or justify against.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from .ocr import ocr_image
from .segmenter import ZWSP, insert_breaks

# Scripts written without spaces between words -- the only text a dictionary segmenter has anything to add to:
# Thai, Lao, Myanmar, Khmer (and Khmer symbols). Anything else already breaks where it should.
_NEEDS_SEGMENTING = re.compile("[\u0E00-\u0EFF\u1000-\u109F\u1780-\u17FF\u19E0-\u19FF]")


def process_text(
    text: str,
    separator: str = ZWSP,
    extra_terms_file: str | list[str] | None = None,
    exclude_terms_file: str | list[str] | None = None,
    extra_terms_dir: str | list[str] | None = None,
    exclude_terms_dir: str | list[str] | None = None,
    extra_terms: Sequence[str] | None = None,
    exclude_terms: Sequence[str] | None = None,
) -> str:
    """Segment already-digital text and insert break points.

    `extra_terms_file` optionally names one path or a list of paths to
    protected-terms files (`.txt` or `.json` -- see
    aksor_khmer_ocr_segmenter.protected_terms.loader) to merge in for this call,
    on top of the built-ins and whatever AKSOR_KHMER_OCR_PROTECTED_TERMS_FILE
    already supplies. `extra_terms_dir` is the directory form -- one path
    or a list of directories, every `*.txt` file inside merged in, on top
    of whatever AKSOR_KHMER_OCR_PROTECTED_TERMS_DIR already supplies.
    `extra_terms` is the in-memory form -- a plain list of term strings,
    for a caller that already has them (e.g. a database row) rather than
    a file on disk.

    `exclude_terms_file`/`exclude_terms_dir`/`exclude_terms` are the
    inverse: terms to drop from the merge set for this call, on top of
    whatever AKSOR_KHMER_OCR_EXCLUDED_TERMS_FILE/_DIR already supplies.

    Text with no Khmer (nor Thai, Lao or Myanmar) in it is returned unchanged: it already has its break points, and
    separators inside a date, an amount or an ID ("2026\u200b-\u200b09\u200b-\u200b02") would only break what a
    template does with it -- slicing a date, comparing a status, a value pasted out of a spreadsheet. Text that
    mixes in Khmer is segmented as a whole, as before.
    """
    if not _NEEDS_SEGMENTING.search(text):
        return text
    return insert_breaks(
        text,
        separator=separator,
        extra_terms_file=extra_terms_file,
        exclude_terms_file=exclude_terms_file,
        extra_terms_dir=extra_terms_dir,
        exclude_terms_dir=exclude_terms_dir,
        extra_terms=extra_terms,
        exclude_terms=exclude_terms,
    )


def process_image(
    image_path: str | Path,
    lang: str = "khm",
    psm: int = 6,
    separator: str = ZWSP,
    extra_terms_file: str | list[str] | None = None,
    exclude_terms_file: str | list[str] | None = None,
    extra_terms_dir: str | list[str] | None = None,
    exclude_terms_dir: str | list[str] | None = None,
    extra_terms: Sequence[str] | None = None,
    exclude_terms: Sequence[str] | None = None,
) -> str:
    """OCR an image, then segment the result and insert break points.

    See `process_text` for `extra_terms_file`/`extra_terms_dir`/`extra_terms`/
    `exclude_terms_file`/`exclude_terms_dir`/`exclude_terms`.
    """
    raw_text = ocr_image(image_path, lang=lang, psm=psm)
    return process_text(
        raw_text,
        separator=separator,
        extra_terms_file=extra_terms_file,
        exclude_terms_file=exclude_terms_file,
        extra_terms_dir=extra_terms_dir,
        exclude_terms_dir=exclude_terms_dir,
        extra_terms=extra_terms,
        exclude_terms=exclude_terms,
    )
