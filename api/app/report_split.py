"""Splitting one oversized report into several files.

Why: converting a document to PDF costs a fixed ~2 s (LibreOffice starting
up) plus a per-row cost that *grows faster than the row count* -- measured on
a plain three-column invoice: 1,000 rows ~4 s / 65 pages, 5,000 rows ~28 s,
10,000 rows ~2 minutes and 1.3 GB of memory. One giant file is slow, hits
proxy timeouts, and holds a lot of RAM; the same rows as several files of a
bounded size are quick and predictable. So a report whose repeating table has
more rows than `max_rows_per_file()` is rendered as several files, each with
an equal share of the rows, and handed back as a ZIP.

Which rows: the table is the template's own repeating block -- the
`{%tr for item in items %}` (docx), `{% for item in items %}` (xlsx/html) --
so the collection that gets split is `items`, found by scanning the template,
never a guess from the data. Only when exactly one such collection is over
the limit is anything split; a report with two oversized tables is left whole
(splitting one would repeat the other in every part), with a warning logged.

What a template sees: for any report that has a repeating table, every render
-- split or not, so a template reads the same either way -- is given

    part_number, part_count       which file this is, of how many
    row_offset                    rows in the earlier parts, so numbering can
                                  continue: {{ row_offset + loop.index }}
    first_row, last_row           this part's 1-based row range
    part_row_count                rows in this part
    total_row_count               rows in the whole set
    part_totals, grand_totals     {column: sum} over this part's rows / over
                                  the whole set -- {{ part_totals.line_total }}
                                  and {{ grand_totals.line_total }}

`part_totals`/`grand_totals` cover every numeric column of the rows (JSON
numbers; a number sent as a string isn't summed) because the engine can't
know which column a template means as "the total" -- the template picks. A
key the caller already supplies (say, its own `grand_total`) is never
overridden.
"""
from __future__ import annotations

import html
import logging
import math
import os
import re
import zipfile
from pathlib import Path

_log = logging.getLogger("aksor_khmer_bi.report_split")

DEFAULT_MAX_ROWS_PER_FILE = 1000
# Past this the per-file cost stops being reasonable (5,000 rows ~28 s and
# ~1 GB in the measurements above), so a deployment can't configure past it.
ROWS_PER_FILE_CEILING = 5000
# Files are rendered one after another inside one HTTP request, so the number
# of parts bounds how long that request can run (20 parts of 1,000 rows is
# on the order of 90 s).
DEFAULT_MAX_PARTS = 20
PARTS_CEILING = 100


class TooManyPartsError(ValueError):
    """The data would need more files than one request is allowed to render."""

    def __init__(self, rows: int, parts: int, rows_per_file: int, max_parts: int):
        self.rows, self.parts, self.rows_per_file, self.max_parts = rows, parts, rows_per_file, max_parts
        super().__init__(
            f"This report has {rows:,} rows, which would need {parts} files of up to {rows_per_file:,} rows; "
            f"the most one request can produce is {max_parts} files ({max_parts * rows_per_file:,} rows). "
            "Narrow the filters and run it again."
        )


def int_setting(name: str, default: int, low: int, high: int) -> int:
    """Read at call time (not import time) so a deployment can change it with
    an environment variable and tests can override it. A missing, non-numeric
    or out-of-range value falls back / clamps instead of failing a render."""
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        _log.warning("Ignoring %s=%r (not an integer); using %d", name, raw, default)
        value = default
    return max(low, min(high, value))


def max_rows_per_file() -> int:
    """MAX_ROWS_PER_FILE -- default 1,000, never above ROWS_PER_FILE_CEILING."""
    return int_setting("MAX_ROWS_PER_FILE", DEFAULT_MAX_ROWS_PER_FILE, 1, ROWS_PER_FILE_CEILING)


def max_parts() -> int:
    """MAX_REPORT_PARTS -- default 20, never above PARTS_CEILING."""
    return int_setting("MAX_REPORT_PARTS", DEFAULT_MAX_PARTS, 1, PARTS_CEILING)


# --- which collection is the report's table ----------------------------------

# docxtpl's row/cell/paragraph/run loop tags are `{%tr for ...`, `{%tc`,
# `{%p`, `{%r`; a plain `{% for ...` works everywhere else. The loop variable
# may be a key/value pair; only the collection name matters.
_FOR_LOOP_RE = re.compile(r"\{%-?\s*(?:tr|tc|p|r)?\s*for\s+\w+(?:\s*,\s*\w+)?\s+in\s+([A-Za-z_]\w*)")
_XML_TAG_RE = re.compile(r"<[^>]+>")


def _text_of_xml(raw: bytes) -> str:
    # Word may split one `{%tr for item in items %}` across several runs;
    # dropping the tags rejoins the text, and unescape restores `<`, `"` etc.
    return html.unescape(_XML_TAG_RE.sub("", raw.decode("utf-8", errors="ignore")))


def loop_collections(template_path: str | Path, ext: str) -> set[str]:
    """Names of the collections a template loops over (`items` in
    `{%tr for item in items %}`). Best-effort: a template that can't be read
    just has none, which means "don't split" -- never a failed render."""
    try:
        path = Path(template_path)
        if ext == "html":
            return set(_FOR_LOOP_RE.findall(path.read_text(encoding="utf-8", errors="ignore")))
        parts = {"docx": lambda n: n == "word/document.xml", "xlsx": lambda n: n.startswith("xl/") and n.endswith(".xml")}.get(ext)
        if parts is None:
            return set()
        names: set[str] = set()
        with zipfile.ZipFile(path) as zf:
            for entry in zf.namelist():
                if parts(entry):
                    names.update(_FOR_LOOP_RE.findall(_text_of_xml(zf.read(entry))))
        return names
    except (OSError, zipfile.BadZipFile, KeyError):
        _log.warning("Couldn't scan %s for repeating tables; rendering it unsplit", template_path, exc_info=True)
        return set()


# --- planning the parts ------------------------------------------------------


def _sums(rows: list) -> dict[str, int | float]:
    """Sum every numeric column across `rows` (dict rows only; booleans are
    not numbers here). Integers stay integers; a float anywhere makes the
    column a float, summed with fsum so 0.1 + 0.2 doesn't drift."""
    columns: dict[str, list[int | float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                columns.setdefault(str(key), []).append(value)
    return {k: (math.fsum(v) if any(isinstance(x, float) for x in v) else sum(v)) for k, v in columns.items()}


def oversize_collections(data: dict, collections: set[str], limit: int) -> list[str]:
    """The repeating tables in `data` that have more than `limit` rows."""
    return sorted(n for n in collections if isinstance(data.get(n), list) and len(data[n]) > limit)


def _balanced_sizes(total: int, parts: int) -> list[int]:
    """`total` rows over `parts` files as evenly as possible (1,001 over two
    files is 501 + 500, not 1,000 + 1) -- so no file is a near-empty stub."""
    base, extra = divmod(total, parts)
    return [base + 1] * extra + [base] * (parts - extra)


def plan_parts(data: dict, collections: set[str], *, limit: int | None = None, parts_cap: int | None = None) -> list[dict]:
    """The contexts to render, one per output file (a list of length 1 when
    nothing needs splitting). Raises TooManyPartsError if the rows would need
    more files than `parts_cap` allows."""
    limit = limit or max_rows_per_file()
    parts_cap = parts_cap or max_parts()

    tables = {n: data[n] for n in collections if isinstance(data.get(n), list)}
    if not tables:
        return [data]  # no repeating table, nothing to split or describe

    over = oversize_collections(data, collections, limit)
    if len(over) > 1:
        _log.warning("Not splitting: %s are all over %d rows; splitting one would repeat the others in every file", over, limit)
        return [data]

    if over:
        target = over[0]
    elif len(tables) == 1:
        target = next(iter(tables))
    else:
        return [data]  # several small tables: no single "the table" to describe

    rows = tables[target]
    total = len(rows)
    parts = max(1, math.ceil(total / limit))
    if parts > parts_cap:
        raise TooManyPartsError(total, parts, limit, parts_cap)

    grand_totals = _sums(rows)
    contexts: list[dict] = []
    offset = 0
    for number, size in enumerate(_balanced_sizes(total, parts), start=1):
        chunk = rows[offset : offset + size]
        meta = {
            "part_number": number,
            "part_count": parts,
            "row_offset": offset,
            "first_row": offset + 1 if size else 0,
            "last_row": offset + size,
            "part_row_count": size,
            "total_row_count": total,
            "part_totals": _sums(chunk),
            "grand_totals": grand_totals,
        }
        # The caller's own keys win over the injected ones; the split
        # collection itself is always this part's rows.
        context = {**meta, **data}
        context[target] = chunk
        contexts.append(context)
        offset += size
    return contexts


def part_filename(base: str, number: int, count: int, ext: str) -> str:
    width = max(2, len(str(count)))
    return f"{base}-part-{number:0{width}d}-of-{count:0{width}d}.{ext}"


def zip_name(base: str) -> str:
    return f"{base}-parts.zip"

