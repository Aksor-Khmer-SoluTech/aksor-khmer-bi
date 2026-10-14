"""Analyze: slice a dataset into a pivot -- rows, columns, measures -- as a table or a chart, then export it or keep
the view. Built on datasets (app/datasets.py): their fields, Khmer labels, formats and measures are the palette.

Who may: `analyze:use` (or a superuser). An *open* dataset is open to anyone holding it; a *restricted* one only to
its grants, and only with their filter values (datasets.effective_limits) -- the same check a report run makes. To
keep rows from someone, restrict the dataset: Analyze has no report grants to narrow it.

The data is fetched once per dataset + filter values and kept a few minutes (`_CACHE`), so re-arranging a pivot
doesn't query the database again. The values in the key have already passed the caller's own limits, so two people
whose values are the same share the data they were both allowed to fetch.
"""
from __future__ import annotations

import json
import math
import statistics
import threading
import time
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from . import connections, datasets, db, report_data
from .report_data import DataConfigError, DataSourceError, ParameterError

COUNT_KEY = "__rows"  # the built-in "number of rows" value, always available
BUCKETS = ("day", "month", "year")
# "Show value as" (Excel's Show Values As): each mode's name in English and Khmer, added to the value's label.
SHOW_AS = {
    "percent_of_total": ("% of total", "% នៃសរុប"),
    "percent_of_row": ("% of row total", "% នៃសរុបជួរដេក"),
    "percent_of_column": ("% of column total", "% នៃសរុបជួរឈរ"),
    "running_total": ("running total", "សរុបសន្សំ"),
    "difference": ("change from previous", "ភាពខុសគ្នាពីមុន"),
    "percent_difference": ("% change from previous", "% ប្រែប្រួលពីមុន"),
}
SEQUENCE_MODES = ("running_total", "difference", "percent_difference")  # these run down the rows or across the columns
RANGE_TYPES = ("number", "money")
MAX_RANGES = 200
MAX_FORECAST = 12
OUTLIER_METHODS = {"zscore": 2.0, "iqr": 1.5}  # each method's usual threshold
MAX_ROW_KEYS = 500
MAX_COLUMN_KEYS = 60
MAX_LEVELS = 3
CACHE_SECONDS = 300
CACHE_ENTRIES = 32

_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


class AnalyzeDenied(Exception):
    """The caller may not analyze this dataset."""


# --- who may analyze what -----------------------------------------------------------------------------------------


def may_analyze(context) -> bool:
    return bool(context.is_superuser or context.has_permission("analyze:use"))


def can_use(session, context, row: db.Dataset) -> bool:
    if not may_analyze(context):
        return False
    if (row.access_mode or "open") != "restricted" or datasets.bypasses(context):
        return True
    return bool(datasets._grants_for(session, context, row.id, datasets.ACCESS_LEVELS))


def usable(session, context, org_id: str) -> list[db.Dataset]:
    rows = session.scalars(select(db.Dataset).where(db.Dataset.org_id == org_id).order_by(db.Dataset.title))
    return [r for r in rows if can_use(session, context, r)]


def _limits(session, context, row: db.Dataset, names: list[str]) -> dict[str, set[str] | None]:
    try:
        own = datasets.effective_limits(session, context, row.org_id, row.name, names)
    except datasets.DatasetAccessDenied as exc:
        raise AnalyzeDenied(str(exc)) from exc
    return own if own is not None else {n: None for n in names}


def _definitions(row: db.Dataset) -> list[dict]:
    """The dataset's filters, with any choice list fed by an API fetched now (raises DataSourceError)."""
    return report_data.resolve_parameter_definitions(
        row.parameters or [], materialize=lambda source: connections.materialize(source, row.org_id)
    )


def form(session, context, row: db.Dataset) -> dict:
    """What the Analyze page needs to set it up: filters narrowed to the caller's values, the lists to analyze, their
    fields (hidden ones left out), and the measures each list offers."""
    definitions = _definitions(row)
    limits = _limits(session, context, row, [d["name"] for d in definitions])
    fields = [f for f in (row.fields or []) if not f.get("hidden")]
    sources = sorted({f.get("source") or "" for f in fields}, key=lambda s: (s != "rows", s)) or [""]
    return {
        "dataset": row.name,
        "title": row.title,
        "description": row.description,
        "access_mode": row.access_mode or "open",
        "parameters": [
            {
                "name": d["name"],
                "label": d.get("label"),
                "type": d.get("type") or "text",
                "required": d.get("required", True),
                "default_value": d.get("default_value"),
                "options": report_data.allowed_options(d, limits[d["name"]]),
            }
            for d in definitions
        ],
        "sources": [s for s in sources if s],
        "fields": fields,
        "measures": [
            {"key": m["key"], "label": m["label"], "label_km": m.get("label_km"), "source": m.get("source"), "format": m.get("format")}
            for m in row.measures or []
        ],
    }


# --- the data, fetched once ---------------------------------------------------------------------------------------


def fetch(session, context, row: db.Dataset, values: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """The dataset's data for these filter values -- after the caller's limits have been checked -- and the values
    as resolved (defaults filled in). Raises AnalyzeDenied, ParameterError or DataSourceError."""
    definitions = _definitions(row)
    limits = _limits(session, context, row, [d["name"] for d in definitions])
    params = report_data.resolve_run_parameters(definitions, limits, values)
    key = (row.id, row.updated_at, json.dumps(params, sort_keys=True, ensure_ascii=False))
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1], params
    data = report_data.fetch_report_data(
        connections.materialize(row.data_source, row.org_id), params, {d["name"]: d.get("type") or "text" for d in definitions}
    )
    with _CACHE_LOCK:
        _CACHE[key] = (now, data)
        if len(_CACHE) > CACHE_ENTRIES:  # the oldest go first
            for stale in sorted(_CACHE, key=lambda k: _CACHE[k][0])[: len(_CACHE) - CACHE_ENTRIES]:
                _CACHE.pop(stale, None)
    return data, params


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


# --- the pivot -----------------------------------------------------------------------------------------------------


def _list(data: dict, source: str | None) -> tuple[str, list[dict]]:
    if source:
        value = data.get(source)
        if not isinstance(value, list):
            raise DataConfigError(f"The dataset has no list named {source!r}")
        return source, [r for r in value if isinstance(r, dict)]
    for name, value in data.items():
        if isinstance(value, list) and all(isinstance(r, dict) for r in value):
            return name, value
    raise DataConfigError("This dataset gives no list of rows to analyze")


def _key(row: dict, field: str, bucket: str | None) -> Any:
    value = row.get(field)
    if isinstance(value, str):
        value = value.replace("​", "")  # Khmer segmentation marks never split a group
    if bucket and isinstance(value, str) and len(value) >= 4:
        value = value[:10] if bucket == "day" else value[:7] if bucket == "month" else value[:4]
    return value


def _sorted(keys: list[tuple]) -> list[tuple]:
    def order(k: tuple):
        return tuple((v is None, isinstance(v, str), v if isinstance(v, (int, float)) else str(v or "")) for v in k)

    return sorted(keys, key=order)


def check_layout(layout: dict, fields: list[dict], measures: list[dict]) -> dict:
    """The pivot layout cleaned: {source, rows, columns, values, buckets}. Refuses a field or measure the dataset
    doesn't offer to the caller (hidden fields included)."""
    visible = {(f.get("source") or None, f["name"]): f for f in fields if not f.get("hidden")}
    # No list named: the first one the dataset describes ("rows" first) -- settled here, so the measures offered and
    # the list pivoted are the same one.
    described = sorted({src for (src, _) in visible if src}, key=lambda s: (s != "rows", s))
    source = layout.get("source") or (described[0] if described else None)
    if layout.get("source") and layout["source"] not in described:
        raise DataConfigError(f"The dataset has no list named {layout['source']!r}")
    names = {name for (src, name) in visible if src == source or source is None or src is None}

    def dims(key: str) -> list[str]:
        out = layout.get(key) or []
        if not isinstance(out, list) or len(out) > MAX_LEVELS:
            raise DataConfigError(f"Use at most {MAX_LEVELS} fields in {key}")
        for name in out:
            if name not in names:
                raise DataConfigError(f"{name!r} isn't a field you can analyze here")
        return list(out)

    rows, columns = dims("rows"), dims("columns")
    if set(rows) & set(columns):
        raise DataConfigError("A field can be in rows or in columns, not both")
    offered = {m["key"] for m in measures if (m.get("source") or None) in (None, source)}
    values = layout.get("values") or [COUNT_KEY]
    if not isinstance(values, list) or len(values) > 6:
        raise DataConfigError("Show at most 6 values at once")
    for key in values:
        if key != COUNT_KEY and key not in offered:
            raise DataConfigError(f"{key!r} isn't a measure of this list")
    buckets = {k: v for k, v in (layout.get("buckets") or {}).items() if k in rows + columns}
    for v in buckets.values():
        if v not in BUCKETS:
            raise DataConfigError("Group dates by day, month or year")
    types = {name: f.get("type") for (src, name), f in visible.items() if name in names}
    return {
        "source": source, "rows": rows, "columns": columns, "values": values, "buckets": buckets,
        "ranges": _check_ranges(layout.get("ranges"), rows + columns, types),
        "show_as": _check_show_as(layout.get("show_as"), values, rows, columns),
        "trend": _check_trend(layout.get("trend"), values, rows),
        "outliers": check_outliers(layout.get("outliers")),
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_ranges(raw: Any, placed: list[str], types: dict[str, str | None]) -> dict[str, float | None]:
    """{number field: range width, or None to choose one}. Only fields in rows or columns count."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float | None] = {}
    for name, width in raw.items():
        if name not in placed:
            continue
        if types.get(name) not in RANGE_TYPES:
            raise DataConfigError(f"{name!r} isn't a number -- only number and money fields group into ranges")
        if width is not None and not (_is_number(width) and width > 0):
            raise DataConfigError("A range's width must be a number above 0 -- or leave it empty to have one chosen")
        out[name] = float(width) if width is not None else None
    return out


def _check_show_as(raw: Any, values: list[str], rows: list[str], columns: list[str]) -> dict[str, dict]:
    """{value key: {mode, along}}. A running total or a change from the previous one needs a field to run along."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for key, spec in raw.items():
        if spec is None:
            continue
        if key not in values:
            raise DataConfigError(f"{key!r} isn't one of the values shown")
        spec = spec if isinstance(spec, dict) else {"mode": spec}
        mode, along = spec.get("mode"), spec.get("along") or "rows"
        if mode not in SHOW_AS:
            raise DataConfigError("Show a value as a percentage of a total, a running total, or the change from the previous one")
        if along not in ("rows", "columns"):
            raise DataConfigError("A running total or a change runs down the rows or across the columns")
        if mode in SEQUENCE_MODES and not (rows if along == "rows" else columns):
            raise DataConfigError(f"A {SHOW_AS[mode][0]} runs along a field -- put one in {along} first")
        out[key] = {"mode": mode, "along": along}
    return out


def _check_trend(raw: Any, values: list[str], rows: list[str]) -> dict | None:
    """{value, line, moving_average, forecast}, or None. A trend runs down exactly one row field."""
    if raw is None or raw is False:
        return None
    if not isinstance(raw, dict):
        raise DataConfigError("trend must be an object")
    if len(rows) != 1:
        raise DataConfigError("A trend runs down one field in rows -- use exactly one (a date by month, say)")
    value = raw.get("value") or values[0]
    if value not in values:
        raise DataConfigError(f"{value!r} isn't one of the values shown")
    line = bool(raw.get("line", True))
    average = raw.get("moving_average")
    if average is not None and (not isinstance(average, int) or isinstance(average, bool) or not 2 <= average <= 12):
        raise DataConfigError("A moving average is over 2 to 12 periods")
    forecast = raw.get("forecast") or 0
    if not isinstance(forecast, int) or isinstance(forecast, bool) or not 0 <= forecast <= MAX_FORECAST:
        raise DataConfigError(f"Forecast 0 to {MAX_FORECAST} periods ahead")
    if forecast and not line:
        raise DataConfigError("A forecast extends the trend line -- turn the line on")
    if not line and not average:
        return None
    return {"value": value, "line": line, "moving_average": average, "forecast": forecast}


def check_outliers(raw: Any) -> dict | None:
    """{method, threshold}, or None: z-score (how many standard deviations from the mean, 2 by default) or IQR (how
    many interquartile ranges beyond the quartiles, 1.5 by default -- Tukey's fences, as a box plot draws them)."""
    if raw is None or raw is False:
        return None
    if not isinstance(raw, dict):
        raise DataConfigError("outliers must be an object")
    method = raw.get("method") or "zscore"
    if method not in OUTLIER_METHODS:
        raise DataConfigError("Find outliers by z-score or by interquartile range (IQR)")
    threshold = raw.get("threshold")
    if threshold is None:
        threshold = OUTLIER_METHODS[method]
    if not _is_number(threshold) or not 0 < threshold <= 10:
        raise DataConfigError("An outlier threshold is a number above 0, up to 10")
    return {"method": method, "threshold": float(threshold)}


def pivot(data: dict, layout: dict, measures: list[dict]) -> dict:
    """The pivot of `data` by `layout` (check_layout's): row keys x column keys, each cell every value -- a measure
    worked out over that cell's rows (so a ratio stays a ratio, not a sum of ratios), or the row count -- plus the
    totals of each row, each column and the whole. Then, as the layout asks: values shown as a percentage, running
    total or change; outliers marked; a trend down the rows."""
    source, rows_data = _list(data, layout["source"])
    rows, columns, buckets = layout["rows"], layout["columns"], layout["buckets"]
    ranges = {f: _range_plan(rows_data, f, w) for f, w in (layout.get("ranges") or {}).items()}
    wanted = [m for m in measures if (m.get("source") or None) in (None, source)]

    def key_of(r: dict, field: str) -> Any:
        if field in ranges:  # the range's number (0, 1, 2…) while grouping and sorting; its label at the end
            n = datasets._number(r.get(field))
            return None if n is None else math.floor((n - ranges[field]["start"]) / ranges[field]["width"] + 1e-9)
        return _key(r, field, buckets.get(field))

    cells: dict[tuple, dict[tuple, list[dict]]] = {}
    for r in rows_data:
        rk = tuple(key_of(r, f) for f in rows)
        ck = tuple(key_of(r, f) for f in columns)
        cells.setdefault(rk, {}).setdefault(ck, []).append(r)
    row_keys = _sorted(list(cells))
    column_keys = _sorted(list({ck for by in cells.values() for ck in by}))
    # A range field alone on its side lists every range from the lowest to the highest, the empty ones too: a
    # histogram that leaves out a gap misleads.
    if len(rows) == 1 and rows[0] in ranges:
        row_keys = _filled(row_keys)
    if len(columns) == 1 and columns[0] in ranges:
        column_keys = _filled(column_keys)
    if len(row_keys) > MAX_ROW_KEYS or len(column_keys) > MAX_COLUMN_KEYS:
        raise DataConfigError(
            f"That makes {len(row_keys):,} rows by {len(column_keys):,} columns -- more than {MAX_ROW_KEYS} by "
            f"{MAX_COLUMN_KEYS}. Group a date by month or year, move a field, or narrow the filters"
        )

    def work(subset: list[dict]) -> list[dict]:
        texts, numbers = datasets.compute_measures(wanted, {source: subset}) if wanted else ({}, {})
        out = []
        for key in layout["values"]:
            if key == COUNT_KEY:
                out.append({"v": len(subset), "t": f"{len(subset):,}"})
            else:
                out.append({"v": numbers.get(key), "t": texts.get(key, "")})
        return out

    matrix = [[work(cells[rk][ck]) if ck in cells.get(rk, {}) else None for ck in column_keys] for rk in row_keys]
    by_column: dict[tuple, list[dict]] = {}
    for rk in row_keys:
        for ck, subset in cells.get(rk, {}).items():
            by_column.setdefault(ck, []).extend(subset)
    result = {
        "source": source,
        "row_keys": [list(k) for k in row_keys],
        "column_keys": [list(k) for k in column_keys],
        "cells": matrix,
        "row_totals": [work([r for subset in cells.get(rk, {}).values() for r in subset]) for rk in row_keys],
        "column_totals": [work(by_column.get(ck, [])) for ck in column_keys],
        "total": work(rows_data),
        "row_count": len(rows_data),
    }
    formats = value_formats(layout, measures)
    result["formats"] = formats  # how each value reads -- a chart's axis shows a percentage as one
    _show_values_as(result, layout, formats)
    if layout.get("outliers"):
        result["outliers"] = _mark_outliers(result, layout, formats)
    if layout.get("trend"):
        result["trend"] = _trend(result, layout, formats, ranges)
    if ranges:
        result["ranges"] = {f: {"width": p["width"], "width_t": _plain_number(p["width"])} for f, p in ranges.items()}

        def named(keys: list[list], fields: list[str]) -> list[list]:
            return [[_range_label(ranges[f], v) if f in ranges and v is not None else v for f, v in zip(fields, k)] for k in keys]

        result["row_keys"], result["column_keys"] = named(result["row_keys"], rows), named(result["column_keys"], columns)
    return result


def value_formats(layout: dict, measures: list[dict]) -> dict[str, str | None]:
    """Each value's display format as shown: a percentage when shown as one, else the measure's own."""
    own = {m["key"]: m.get("format") for m in measures}
    show = layout.get("show_as") or {}
    return {
        key: "0.0%" if show.get(key, {}).get("mode", "").startswith("percent") else ("#,##0" if key == COUNT_KEY else own.get(key))
        for key in layout["values"]
    }


# --- number ranges ---------------------------------------------------------------------------------------------------


def _plain_number(x: float) -> str:
    return f"{round(x, 9):,.6f}".rstrip("0").rstrip(".")


def _nice_width(raw: float) -> float:
    """The first of 1, 2, 2.5, 5 or 10 x a power of ten at or above `raw` -- so ranges read 0-5,000, not 0-4,731."""
    magnitude = 10 ** math.floor(math.log10(raw))
    return next(step * magnitude for step in (1, 2, 2.5, 5, 10) if step * magnitude >= raw * (1 - 1e-9))


def _range_plan(rows_data: list[dict], field: str, width: float | None) -> dict:
    """How a number field groups into ranges: {start, width}, each range from its lower edge up to (not including)
    the next. The start is a whole number of widths, so the edges read round. No width given: about ten ranges."""
    numbers = [n for n in (datasets._number(r.get(field)) for r in rows_data) if n is not None]
    if not numbers:
        return {"start": 0.0, "width": width or 1.0}
    low, high = min(numbers), max(numbers)
    if width is None:
        width = _nice_width((high - low) / 10 if high > low else abs(high) or 1)
    start = math.floor(low / width + 1e-9) * width
    count = math.floor((high - start) / width + 1e-9) + 1
    if count > MAX_RANGES:
        raise DataConfigError(f"Ranges {_plain_number(width)} wide make {count:,} of them -- more than {MAX_RANGES}. Make them wider")
    return {"start": start, "width": width}


def _range_label(plan: dict, index: int) -> str:
    low = plan["start"] + index * plan["width"]
    return f"{_plain_number(low)}–{_plain_number(low + plan['width'])}"


def _filled(keys: list[tuple]) -> list[tuple]:
    present = [k[0] for k in keys if k[0] is not None]
    if not present:
        return keys
    return [(i,) for i in range(min(present), max(present) + 1)] + [k for k in keys if k[0] is None]


# --- show value as ---------------------------------------------------------------------------------------------------


def _show_values_as(result: dict, layout: dict, formats: dict[str, str | None]) -> None:
    """Replace each value shown as something else -- in place, cells and totals alike."""
    show = layout.get("show_as") or {}
    if not show:
        return
    # The whole pivot as one grid: each row's cells, then its total; under them the column totals, then the total.
    grid = [list(result["cells"][r]) + [result["row_totals"][r]] for r in range(len(result["row_keys"]))]
    grid.append(list(result["column_totals"]) + [result["total"]])
    for i, key in enumerate(layout["values"]):
        if key not in show:
            continue
        before = [[entries[i]["v"] if entries else None for entries in line] for line in grid]
        after = _shown(before, show[key], result["row_keys"], result["column_keys"])
        for r, line in enumerate(grid):
            for c, entries in enumerate(line):
                if entries:
                    entries[i] = {"v": after[r][c], "t": datasets.format_number(after[r][c], formats[key])}


def _shown(grid: list[list], spec: dict, row_keys: list, column_keys: list) -> list[list]:
    """`grid` (rows of numbers, the totals last on each side) as `spec` shows it."""
    last_row, last_column = len(grid) - 1, len(grid[0]) - 1
    mode = spec["mode"]

    def share(part: float | None, whole: float | None) -> float | None:
        return None if part is None or not whole else part / whole

    if mode == "percent_of_total":
        return [[share(v, grid[last_row][last_column]) for v in line] for line in grid]
    if mode == "percent_of_row":
        return [[share(v, line[last_column]) for v in line] for line in grid]
    if mode == "percent_of_column":
        return [[share(grid[r][c], grid[last_row][c]) for c in range(last_column + 1)] for r in range(last_row + 1)]
    # A running total or a change runs down each column (along the rows) or across each row (along the columns),
    # starting again whenever an outer field's value changes -- branch, then month: each branch's months. The totals
    # across that direction have nothing to run along, so they're left empty.
    out: list[list] = [[None] * (last_column + 1) for _ in range(last_row + 1)]
    if spec["along"] == "rows":
        for c in range(last_column + 1):
            for run in _runs(row_keys):
                for r, v in zip(run, _sequence([grid[r][c] for r in run], mode)):
                    out[r][c] = v
    else:
        for r in range(last_row + 1):
            for run in _runs(column_keys):
                for c, v in zip(run, _sequence([grid[r][c] for c in run], mode)):
                    out[r][c] = v
    return out


def _runs(keys: list) -> list[list[int]]:
    """Positions of `keys` grouped by everything but their last level (sorted keys keep each group together)."""
    groups: list[list[int]] = []
    for i, key in enumerate(keys):
        if groups and tuple(keys[groups[-1][0]][:-1]) == tuple(key[:-1]):
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def _sequence(values: list[float | None], mode: str) -> list[float | None]:
    out: list[float | None] = []
    running, previous = 0.0, None
    for v in values:
        if mode == "running_total":
            running += v or 0
            out.append(running if v is not None else None)
        elif mode == "difference":
            out.append(None if v is None or previous is None else v - previous)
        else:
            out.append(None if v is None or not previous else (v - previous) / abs(previous))
        previous = v
    return out


# --- outliers --------------------------------------------------------------------------------------------------------


def outlier_limits(numbers: list[float], method: str, threshold: float) -> tuple[float, float] | None:
    """(low, high): a value below or above is an outlier. None when there are too few values to say -- 3 for a
    z-score, 4 for quartiles -- or they're all the same."""
    if method == "zscore":
        if len(numbers) < 3:
            return None
        # Of these values themselves (population), as a z-score is: how far each is from their mean.
        mean, spread = statistics.fmean(numbers), statistics.pstdev(numbers)
        return None if spread == 0 else (mean - threshold * spread, mean + threshold * spread)
    if len(numbers) < 4:
        return None
    ordered = sorted(numbers)
    q1, q3 = datasets._percentile(ordered, 25), datasets._percentile(ordered, 75)
    return None if q3 == q1 else (q1 - threshold * (q3 - q1), q3 + threshold * (q3 - q1))


def _mark_outliers(result: dict, layout: dict, formats: dict[str, str | None]) -> dict:
    """Mark each cell (not the totals) whose value stands out from the other cells of the same value: "o": "high" or
    "low". Returns the limits used, per value."""
    spec = layout["outliers"]
    found = []
    for i, key in enumerate(layout["values"]):
        entries = [cell[i] for line in result["cells"] for cell in line if cell and cell[i]["v"] is not None]
        limits = outlier_limits([e["v"] for e in entries], spec["method"], spec["threshold"])
        count = 0
        for e in entries if limits else []:
            if e["v"] < limits[0] or e["v"] > limits[1]:
                e["o"] = "low" if e["v"] < limits[0] else "high"
                count += 1
        found.append({
            "key": key, "count": count,
            "low": limits[0] if limits else None, "high": limits[1] if limits else None,
            "low_t": datasets.format_number(limits[0], formats[key]) if limits else None,
            "high_t": datasets.format_number(limits[1], formats[key]) if limits else None,
        })
    return {**spec, "values": found}


# --- trend -----------------------------------------------------------------------------------------------------------


def _period(value: Any) -> tuple[str, int] | None:
    """A date key as (unit, a count of that unit), so months 2026-11 and 2027-01 are two apart, not one."""
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 4 and value.isdigit():
            return "year", int(value)
        if len(value) == 7 and value[4] == "-":
            year, month = int(value[:4]), int(value[5:])
            return ("month", year * 12 + month - 1) if 1 <= month <= 12 else None
        if len(value) >= 10 and value[4] == "-" and value[7] == "-":
            return "day", date.fromisoformat(value[:10]).toordinal()
    except ValueError:
        return None
    return None


def _period_name(unit: str, n: int) -> str:
    if unit == "year":
        return str(n)
    if unit == "month":
        return f"{n // 12:04d}-{n % 12 + 1:02d}"
    return (date.fromordinal(n)).isoformat()


def _fit(points: list[tuple[float, float]]) -> tuple[float, float, float | None] | None:
    """Least squares: (slope, intercept, R²). None with fewer than two distinct places along the axis."""
    if len({x for x, _ in points}) < 2:
        return None
    mx, my = statistics.fmean(x for x, _ in points), statistics.fmean(y for _, y in points)
    sxx = sum((x - mx) ** 2 for x, _ in points)
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx
    intercept = my - slope * mx
    total = sum((y - my) ** 2 for _, y in points)
    residual = sum((y - intercept - slope * x) ** 2 for x, y in points)
    return slope, intercept, (1 - residual / total) if total else None


def _trend(result: dict, layout: dict, formats: dict[str, str | None], ranges: dict[str, dict]) -> dict:
    """Down the rows, for each series (column) of one value: a straight-line trend (slope per period, R²), a
    trailing moving average, and the line carried on for the periods asked. Periods are real ones when the rows are
    dates -- a missing month leaves a gap, not a shorter step -- ranges step one range, anything else one row."""
    spec = layout["trend"]
    field, i, fmt = layout["rows"][0], layout["values"].index(spec["value"]), formats[spec["value"]]
    keys = [k[0] for k in result["row_keys"]]
    periods = [_period(k) for k in keys if k is not None]
    unit: str | None = None
    if field in ranges:
        axis, unit = keys, "range"
    elif periods and all(periods) and len({p[0] for p in periods}) == 1:
        unit = periods[0][0]
        axis = [_period(k)[1] if k is not None else None for k in keys]
    else:
        axis = [n if k is not None else None for n, k in enumerate(keys)]
    known = [x for x in axis if x is not None]
    ahead = [max(known) + j for j in range(1, spec["forecast"] + 1)] if known and spec["line"] else []
    if unit == "range":
        ahead_names = [_range_label(ranges[field], x) for x in ahead]
    elif unit:
        ahead_names = [_period_name(unit, x) for x in ahead]
    else:
        ahead_names = [f"+{j}" for j in range(1, len(ahead) + 1)]
    series = []
    for c in range(len(result["column_keys"])):
        ys = [(line[c][i]["v"] if line[c] else None) for line in result["cells"]]
        entry: dict[str, Any] = {}
        fit = _fit([(x, y) for x, y in zip(axis, ys) if x is not None and y is not None]) if spec["line"] else None
        if fit:
            slope, intercept, r2 = fit
            entry.update({
                "slope": slope, "slope_t": datasets.format_number(slope, fmt), "intercept": intercept, "r2": r2,
                "fitted": [None if x is None else intercept + slope * x for x in axis],
                "forecast": [{"v": intercept + slope * x, "t": datasets.format_number(intercept + slope * x, fmt)} for x in ahead],
            })
        n = spec["moving_average"]
        if n:
            entry["moving_average"] = [
                sum(ys[r - n + 1: r + 1]) / n if r >= n - 1 and all(y is not None for y in ys[r - n + 1: r + 1]) else None
                for r in range(len(ys))
            ]
        series.append(entry)
    return {**spec, "per": unit, "forecast_keys": ahead_names, "series": series}


def labels(row: db.Dataset, layout: dict) -> dict:
    """How to name things in a result: each field's and value's label, English and Khmer."""
    fields = {f["name"]: f for f in row.fields or [] if (f.get("source") or None) in (None, layout.get("source"))}
    measures = {m["key"]: m for m in row.measures or []}

    def field(name: str) -> dict:
        f = fields.get(name) or {}
        return {"name": name, "label": f.get("label") or name, "label_km": f.get("label_km"), "type": f.get("type") or "text"}

    def value(key: str) -> dict:
        if key == COUNT_KEY:
            out = {"key": key, "label": "Rows", "label_km": "ចំនួនជួរ"}
        else:
            m = measures.get(key) or {}
            out = {"key": key, "label": m.get("label") or key, "label_km": m.get("label_km")}
        mode = (layout.get("show_as") or {}).get(key, {}).get("mode")
        if mode:  # "Net sales (% of total)" -- the column says what it holds now
            en, km = SHOW_AS[mode]
            out = {**out, "label": f"{out['label']} ({en})", "label_km": f"{out['label_km']} ({km})" if out["label_km"] else None, "show_as": mode}
        return out

    return {
        "rows": [field(n) for n in layout["rows"]],
        "columns": [field(n) for n in layout["columns"]],
        "values": [value(k) for k in layout["values"]],
    }


def run(session, context, row: db.Dataset, values: dict[str, str], layout: dict) -> dict:
    """Everything one pivot request answers with."""
    started = time.monotonic()
    clean = check_layout(layout, row.fields or [], row.measures or [])
    data, params = fetch(session, context, row, values)
    result = pivot(data, clean, row.measures or [])
    return {
        **result,
        "layout": clean,
        "labels": labels(row, clean),
        "values_used": params,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


__all__ = ["AnalyzeDenied", "ParameterError", "DataSourceError", "DataConfigError"]
