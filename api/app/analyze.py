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
import threading
import time
from typing import Any

from sqlalchemy import select

from . import connections, datasets, db, report_data
from .report_data import DataConfigError, DataSourceError, ParameterError

COUNT_KEY = "__rows"  # the built-in "number of rows" value, always available
BUCKETS = ("day", "month", "year")
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
    return {"source": source, "rows": rows, "columns": columns, "values": values, "buckets": buckets}


def pivot(data: dict, layout: dict, measures: list[dict]) -> dict:
    """The pivot of `data` by `layout` (check_layout's): row keys x column keys, each cell every value -- a measure
    worked out over that cell's rows (so a ratio stays a ratio, not a sum of ratios), or the row count -- plus the
    totals of each row, each column and the whole."""
    source, rows_data = _list(data, layout["source"])
    rows, columns, buckets = layout["rows"], layout["columns"], layout["buckets"]
    wanted = [m for m in measures if (m.get("source") or None) in (None, source)]
    cells: dict[tuple, dict[tuple, list[dict]]] = {}
    for r in rows_data:
        rk = tuple(_key(r, f, buckets.get(f)) for f in rows)
        ck = tuple(_key(r, f, buckets.get(f)) for f in columns)
        cells.setdefault(rk, {}).setdefault(ck, []).append(r)
    row_keys = _sorted(list(cells))
    column_keys = _sorted(list({ck for by in cells.values() for ck in by}))
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

    matrix = [[work(cells[rk].get(ck, [])) if ck in cells[rk] else None for ck in column_keys] for rk in row_keys]
    by_column: dict[tuple, list[dict]] = {}
    for rk in row_keys:
        for ck, subset in cells[rk].items():
            by_column.setdefault(ck, []).extend(subset)
    return {
        "source": source,
        "row_keys": [list(k) for k in row_keys],
        "column_keys": [list(k) for k in column_keys],
        "cells": matrix,
        "row_totals": [work([r for subset in cells[rk].values() for r in subset]) for rk in row_keys],
        "column_totals": [work(by_column.get(ck, [])) for ck in column_keys],
        "total": work(rows_data),
        "row_count": len(rows_data),
    }


def labels(row: db.Dataset, layout: dict) -> dict:
    """How to name things in a result: each field's and value's label, English and Khmer."""
    fields = {f["name"]: f for f in row.fields or [] if (f.get("source") or None) in (None, layout.get("source"))}
    measures = {m["key"]: m for m in row.measures or []}

    def field(name: str) -> dict:
        f = fields.get(name) or {}
        return {"name": name, "label": f.get("label") or name, "label_km": f.get("label_km"), "type": f.get("type") or "text"}

    def value(key: str) -> dict:
        if key == COUNT_KEY:
            return {"key": key, "label": "Rows", "label_km": "ចំនួនជួរ"}
        m = measures.get(key) or {}
        return {"key": key, "label": m.get("label") or key, "label_km": m.get("label_km")}

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
