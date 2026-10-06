"""How many records one batch-render request may contain.

Batch render makes one document per record, all inside a single HTTP request,
so what bounds it is *time*, and the two families of output format differ by a
factor of ~200 in what one record costs (measured on the sample invoice):

    pdf, png      ~2.0 s each -- every one is a LibreOffice conversion, and the
                  ~2 s is LibreOffice starting up, not the document
    docx, xlsx    ~0.01 s each -- filled in directly, no conversion at all

A single count for both (it used to be 200) was wrong twice: 200 PDFs is ~6.5
minutes in one request -- past what a proxy or browser will wait -- while 200
docx files is 2 seconds, needlessly small. So the limit is per family, sized to
about a minute of work, and both are settings. (The estimates below are
measurements from one machine, used only to tell the user roughly what to
expect; the limits themselves are what's enforced.)
"""
from __future__ import annotations

from .report_split import int_setting

# Formats that go through LibreOffice.
SLOW_FORMATS = ("pdf", "png")
FAST_FORMATS = ("docx", "xlsx")

DEFAULT_MAX_SLOW = 30  # ~ a minute of conversions
DEFAULT_MAX_FAST = 1000  # ~ 10 s, and a ZIP of a few tens of MB held in memory
SLOW_CEILING = 200
FAST_CEILING = 5000

# Rough seconds to render one record, for the "about how long" estimate.
SECONDS_PER_RECORD = {"pdf": 2.0, "png": 2.0, "docx": 0.02, "xlsx": 0.02}


def max_batch_size(fmt: str) -> int:
    """MAX_BATCH_PDF_PNG (default 30) for pdf/png, MAX_BATCH_DOCX_XLSX
    (default 1,000) for docx/xlsx -- read at call time, clamped to a ceiling."""
    if fmt in SLOW_FORMATS:
        return int_setting("MAX_BATCH_PDF_PNG", DEFAULT_MAX_SLOW, 1, SLOW_CEILING)
    return int_setting("MAX_BATCH_DOCX_XLSX", DEFAULT_MAX_FAST, 1, FAST_CEILING)


def limits() -> dict:
    """What GET /reports/batch-limits returns: one source of truth for the
    caps and the per-record estimate, so the portal doesn't keep its own copy."""
    formats = SLOW_FORMATS + FAST_FORMATS
    return {
        "max_records": {fmt: max_batch_size(fmt) for fmt in formats},
        "seconds_per_record": {fmt: SECONDS_PER_RECORD[fmt] for fmt in formats},
    }


def over_limit_message(count: int, fmt: str) -> str:
    cap = max_batch_size(fmt)
    seconds = SECONDS_PER_RECORD.get(fmt, 0.02)
    why = (
        f"each {fmt} takes about {seconds:g} s to render and the whole batch is one request"
        if fmt in SLOW_FORMATS
        else "the whole batch is one request held in memory"
    )
    hint = (
        f" docx and xlsx batches are far cheaper (up to {max_batch_size('docx'):,})."
        if fmt in SLOW_FORMATS
        else ""
    )
    return (
        f"Batch of {count:,} exceeds the maximum of {cap:,} {fmt} documents per request ({why}). "
        f"Split it into several requests.{hint}"
    )
