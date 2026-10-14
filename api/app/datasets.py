"""Datasets: one governed definition of a body of data that many reports build on -- what Oracle BI calls a subject
area, Power BI a semantic model, Jasper a Domain. A dataset holds:

* a **source** and **filters** -- the very shapes a report's own data source and parameters have (report_data.py
  validates them the same way), so a database source may have several queries, a REST source its connection;
* **fields** -- what each column means and how it reads: a type, an English and a Khmer label, a display format,
  hidden or not. Metadata for people (and for Analyze, later); a template still gets the raw values;
* **measures** -- named calculations, picked rather than typed: sum, count, count distinct, average, minimum,
  maximum over a field (optionally only where another field has a value), or the ratio of two other measures.

A report built on a dataset saves only {"type": "dataset", "dataset": "<name>"} as its data source. Whenever the
report is looked up to be run (report_store.get_report), `resolve_into` puts the dataset's current source and filters
in its place -- so the run page, embeds, jobs and filter grants all see an ordinary source, and a change to the
dataset reaches every report on its next run. Its measures come with the data, computed over the fetched rows:

    {{ measures.net_sales }}          112,480,000 ៛      (formatted by the measure's own format)
    {{ measure_values.net_sales }}    112480000.0        (the number, for arithmetic)
"""
from __future__ import annotations

import math
import re
from typing import Any

from sqlalchemy import select

from . import db
from .report_data import MAX_VALUE_LENGTH, DataConfigError

NAME_RE = re.compile(r"^[a-z0-9]+([-_][a-z0-9]+)*$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
FIELD_TYPES = ("text", "number", "money", "date", "datetime", "boolean")
MEASURE_KINDS = ("sum", "count", "count_distinct", "avg", "min", "max", "ratio")
MAX_FIELDS = 200
MAX_MEASURES = 50
LABEL_MAX = 100
FORMAT_MAX = 40


def _org(org_id: str | None) -> str:
    from .rbac import ROOT_ORG_ID

    return org_id or ROOT_ORG_ID


# --- checking a dataset ---------------------------------------------------------------------------------------------


def validate_name(name: Any) -> str:
    cleaned = (name or "").strip() if isinstance(name, str) else ""
    if not (2 <= len(cleaned) <= 64) or not NAME_RE.match(cleaned):
        raise DataConfigError("The name is 2-64 lowercase letters and digits, with single hyphens or underscores between them (e.g. branch-sales)")
    return cleaned


def _label(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > LABEL_MAX or "\n" in value:
        raise DataConfigError(f"{where} must be one line of at most {LABEL_MAX} characters")
    return value.strip() or None


def _format(value: Any, where: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > FORMAT_MAX:
        raise DataConfigError(f"{where}: a display format is at most {FORMAT_MAX} characters, e.g. #,##0.00 ៛ or 0.0%")
    return value


def validate_fields(raw: Any) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_FIELDS:
        raise DataConfigError(f"Fields must be a list of at most {MAX_FIELDS}")
    cleaned: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise DataConfigError("Each field must be an object")
        source = (item.get("source") or "").strip()
        name = (item.get("name") or "").strip()
        if not name or len(name) > 128:
            raise DataConfigError("Each field needs the column name it describes")
        if (source, name) in seen:
            raise DataConfigError(f"The field {name!r} is described twice")
        seen.add((source, name))
        kind = item.get("type") or "text"
        if kind not in FIELD_TYPES:
            raise DataConfigError(f"{name}: a field is one of {', '.join(FIELD_TYPES)}")
        cleaned.append({
            "source": source or None,
            "name": name,
            "type": kind,
            "label": _label(item.get("label"), f"{name}'s label"),
            "label_km": _label(item.get("label_km"), f"{name}'s Khmer label"),
            "format": _format(item.get("format"), name),
            "hidden": item.get("hidden") is True,
        })
    return cleaned


def validate_measures(raw: Any) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_MEASURES:
        raise DataConfigError(f"Measures must be a list of at most {MAX_MEASURES}")
    cleaned: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise DataConfigError("Each measure must be an object")
        key = (item.get("key") or "").strip()
        if not KEY_RE.match(key):
            raise DataConfigError(f"{key!r}: a measure's key is lowercase letters, digits and underscores, starting with a letter (e.g. net_sales)")
        if any(m["key"] == key for m in cleaned):
            raise DataConfigError(f"Two measures are called {key!r}")
        kind = item.get("kind")
        if kind not in MEASURE_KINDS:
            raise DataConfigError(f"{key}: a measure is one of {', '.join(MEASURE_KINDS)}")
        measure = {
            "key": key,
            "label": _label(item.get("label"), f"{key}'s label") or key,
            "label_km": _label(item.get("label_km"), f"{key}'s Khmer label"),
            "kind": kind,
            "source": (item.get("source") or "").strip() or None,
            "field": None,
            "where": None,
            "numerator": None,
            "denominator": None,
            "format": _format(item.get("format"), key),
        }
        if kind == "ratio":
            for part in ("numerator", "denominator"):
                ref = item.get(part)
                if not isinstance(ref, str) or not ref:
                    raise DataConfigError(f"{key}: a ratio needs a {part} -- another measure")
                measure[part] = ref
        else:
            field = (item.get("field") or "").strip()
            if kind != "count" and not field:
                raise DataConfigError(f"{key}: choose the field to {kind.replace('_', ' ')}")
            measure["field"] = field or None
        where = item.get("where")
        if where:
            if not isinstance(where, dict) or not (where.get("field") or "").strip() or "value" not in where:
                raise DataConfigError(f"{key}: “only where” needs a field and a value")
            measure["where"] = {"field": where["field"].strip(), "value": str(where["value"])}
        cleaned.append(measure)
    keys = {m["key"] for m in cleaned}
    for m in cleaned:
        if m["kind"] == "ratio":
            for part in ("numerator", "denominator"):
                ref = m[part]
                if ref == m["key"] or ref not in keys:
                    raise DataConfigError(f"{m['key']}: its {part} {ref!r} isn't another measure of this dataset")
                if next(x for x in cleaned if x["key"] == ref)["kind"] == "ratio":
                    raise DataConfigError(f"{m['key']}: a ratio is of two plain measures, not of another ratio")
    return cleaned


# --- computing measures ---------------------------------------------------------------------------------------------


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("​", "")
        text = re.sub(r"[^\d.\-eE+]", "", text)
        try:
            number = float(text)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _rows(data: dict, source: str | None) -> list[dict]:
    """The list a measure counts over: the named result, or the first list in the data."""
    if source:
        value = data.get(source)
        return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []
    for value in data.values():
        if isinstance(value, list) and all(isinstance(r, dict) for r in value):
            return value
    return []


def _plain(measure: dict, data: dict) -> float | None:
    rows = _rows(data, measure["source"])
    where = measure["where"]
    if where:
        rows = [r for r in rows if str(r.get(where["field"], "")).replace("​", "") == where["value"]]
    kind = measure["kind"]
    if kind == "count":
        return float(len(rows)) if not measure["field"] else float(sum(1 for r in rows if r.get(measure["field"]) not in (None, "")))
    values = [r.get(measure["field"]) for r in rows]
    if kind == "count_distinct":
        return float(len({str(v).replace("​", "") for v in values if v not in (None, "")}))
    numbers = [n for n in (_number(v) for v in values) if n is not None]
    if not numbers:
        return 0.0 if kind == "sum" else None
    if kind == "sum":
        return sum(numbers)
    if kind == "avg":
        return sum(numbers) / len(numbers)
    return min(numbers) if kind == "min" else max(numbers)


def format_number(value: float | None, pattern: str | None) -> str:
    """A number as a person reads it, by a small Excel-like pattern: `#,##0`, `#,##0.00`, `0.0%`, with any text
    around it kept (`#,##0 ៛`, `$#,##0.00`). No pattern: thousands separators, and two decimals unless whole."""
    if value is None:
        return "—"
    if not pattern:
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    core = re.search(r"[#0][#0,]*(?:\.0+)?%?", pattern)
    if not core:
        return pattern + (f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}")
    spec = core.group(0)
    decimals = len(spec.split(".")[1].rstrip("%")) if "." in spec else 0
    number = value * 100 if spec.endswith("%") else value
    text = f"{number:,.{decimals}f}" if "," in spec else f"{number:.{decimals}f}"
    return pattern[: core.start()] + text + ("%" if spec.endswith("%") else "") + pattern[core.end():]


def compute_measures(measures: list[dict], data: dict) -> tuple[dict[str, str], dict[str, float | None]]:
    """({key: formatted text}, {key: number}) for every measure over `data` (the fetched, merged result)."""
    values: dict[str, float | None] = {}
    for m in measures:
        if m["kind"] != "ratio":
            values[m["key"]] = _plain(m, data)
    for m in measures:
        if m["kind"] == "ratio":
            top, bottom = values.get(m["numerator"]), values.get(m["denominator"])
            values[m["key"]] = None if top is None or not bottom else top / bottom
    texts = {m["key"]: format_number(values[m["key"]], m["format"]) for m in measures}
    return texts, values


def detect_fields(data: dict, known: list[dict] | None = None) -> list[dict]:
    """Every column of the data, with a guessed type -- merged with what's already described (`known` wins), so
    running the source again adds new columns without undoing anyone's labels."""
    described = {(f.get("source"), f["name"]): f for f in known or []}
    found: list[dict] = []

    def guess(values: list[Any]) -> str:
        present = [v for v in values if v not in (None, "")]
        if not present:
            return "text"
        if all(isinstance(v, bool) for v in present):
            return "boolean"
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
            return "number"
        if all(isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", v) for v in present):
            return "datetime"
        if all(isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", v) for v in present):
            return "date"
        return "text"

    for key, value in data.items():
        if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
            columns: list[str] = []
            for row in value[:200]:
                columns += [c for c in row if c not in columns]
            for c in columns:
                found.append({"source": key, "name": c, "type": guess([r.get(c) for r in value[:200]])})
        elif isinstance(value, dict):
            for c, v in value.items():
                found.append({"source": key, "name": c, "type": guess([v])})
        elif value is not None and not isinstance(value, list):
            found.append({"source": None, "name": key, "type": guess([value])})

    out: list[dict] = []
    for f in found:
        old = described.pop((f["source"], f["name"]), None)
        out.append(old or {**f, "label": None, "label_km": None, "format": None, "hidden": False})
    out += described.values()  # described but not in this run's data (an empty list, say): kept
    return out


# --- looking datasets up -------------------------------------------------------------------------------------------


def to_dict(row: db.Dataset) -> dict:
    return {
        "id": row.id, "org_id": row.org_id, "name": row.name, "title": row.title, "description": row.description,
        "parameters": row.parameters or [], "data_source": row.data_source, "fields": row.fields or [],
        "measures": row.measures or [], "access_mode": row.access_mode or "open",
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def row_by_name(session, org_id: str | None, name: str) -> db.Dataset | None:
    return session.scalar(select(db.Dataset).where(db.Dataset.org_id == _org(org_id), db.Dataset.name == name))


def get_by_name(name: str, org_id: str | None) -> dict | None:
    with db.SessionLocal() as session:
        row = session.scalar(select(db.Dataset).where(db.Dataset.org_id == _org(org_id), db.Dataset.name == name))
        return to_dict(row) if row is not None else None


def names_for_org(org_id: str | None) -> set[str]:
    with db.SessionLocal() as session:
        return set(session.scalars(select(db.Dataset.name).where(db.Dataset.org_id == _org(org_id))))


def resolve_into(meta: dict) -> dict:
    """A report's meta, with a dataset source replaced by the dataset's current source and filters (and its
    measures carried along for fetch time). A dataset that's gone leaves the reference, which fails at fetch with a
    message saying so. Anything else is returned unchanged."""
    source = meta.get("data_source")
    if not isinstance(source, dict) or source.get("type") != "dataset":
        return meta
    dataset = get_by_name(source.get("dataset") or "", meta.get("org_id"))
    if dataset is None:
        return meta
    return {
        **meta,
        "parameters": dataset["parameters"],
        "data_source": {**dataset["data_source"], "dataset": dataset["name"], "measures": dataset["measures"]},
        "dataset": dataset["name"],
    }


def reports_using(session, org_id: str | None, name: str) -> list[dict]:
    """The reports whose data source is this dataset."""
    from .rbac import ROOT_ORG_ID

    org = _org(org_id)
    query = select(db.ReportRow.report_id, db.ReportRow.name, db.ReportRow.code, db.ReportRow.data_source).order_by(db.ReportRow.name)
    query = query.where(db.ReportRow.org_id == org) if org != ROOT_ORG_ID else query.where(
        (db.ReportRow.org_id == org) | (db.ReportRow.org_id.is_(None))
    )
    return [
        {"report_id": r.report_id, "name": r.name, "code": r.code}
        for r in session.execute(query)
        if isinstance(r.data_source, dict) and r.data_source.get("type") == "dataset" and r.data_source.get("dataset") == name
    ]


def connections_in_use(session, org_id: str | None) -> dict[str, list[str]]:
    """{connection name: [dataset titles]} -- a connection a dataset reads through can't be deleted from under it."""
    usage: dict[str, list[str]] = {}
    for row in session.scalars(select(db.Dataset).where(db.Dataset.org_id == _org(org_id))):
        names = {(row.data_source or {}).get("connection")}
        names |= {(q or {}).get("connection") for q in (row.data_source or {}).get("queries") or []}
        names |= {((p or {}).get("options_source") or {}).get("connection") for p in row.parameters or []}
        for name in names - {None}:
            usage.setdefault(name, []).append(row.title)
    return usage


# --- access (row-level) ---------------------------------------------------------------------------------------------
#
# A dataset is "open" (the default: the reports built on it decide who runs them, exactly as in Phase 2a) or
# "restricted": then only the users and roles holding an active, unexpired grant may use it, each only with the filter
# values their grants allow -- on *top* of what the report's own grants allow (both have to say yes, so a report author
# can't widen what the data's owner allowed). Within the dataset the grants are additive, like every grant here: one
# that leaves a filter out leaves it unrestricted for that person. Superusers and dataset:manage holders aren't limited.

ACCESS_MODES = ("open", "restricted")
ACCESS_LEVELS = ("run", "build")


class DatasetAccessDenied(Exception):
    """The caller has no grant on a restricted dataset."""


def bypasses(context) -> bool:
    return bool(context.is_superuser or context.has_permission("dataset:manage"))


def _grants_for(session, context, dataset_id: str, levels: tuple[str, ...]) -> list[db.DatasetAccessGrant]:
    from .rbac import _active_role_ids, _not_expired_clause

    if context.user is None:
        return []
    role_ids = _active_role_ids(session, context.user.id)
    G = db.DatasetAccessGrant
    subject = (G.subject_type == "user") & (G.subject_id == context.user.id)
    if role_ids:
        subject = subject | ((G.subject_type == "role") & (G.subject_id.in_(role_ids)))
    return list(session.scalars(
        select(G).where(G.dataset_id == dataset_id, G.is_active.is_(True), _not_expired_clause(G), G.level.in_(levels), subject)
    ))


def effective_limits(session, context, org_id: str | None, name: str, parameter_names: list[str]) -> dict[str, set[str] | None] | None:
    """What the dataset itself allows `context` per filter: None when it adds no limits (open, or the caller isn't
    limited); otherwise {filter: allowed values, or None for unrestricted}. Raises DatasetAccessDenied when the
    dataset is restricted and the caller holds no grant on it."""
    row = row_by_name(session, org_id, name)
    if row is None or (row.access_mode or "open") != "restricted" or bypasses(context):
        return None
    grants = _grants_for(session, context, row.id, ACCESS_LEVELS)
    if not grants:
        raise DatasetAccessDenied(f"You don't have access to the dataset {row.title!r} this report is built on")
    limits: dict[str, set[str] | None] = {n: set() for n in parameter_names}
    for grant in grants:
        own = grant.parameter_limits or {}
        for n in parameter_names:
            if limits[n] is None:
                continue
            limits[n] = None if own.get(n) is None else limits[n] | set(own[n])
    return limits


def intersect_limits(report: dict[str, set[str] | None], dataset: dict[str, set[str] | None] | None) -> dict[str, set[str] | None]:
    """Both have to allow a value: None (unrestricted) on one side leaves the other side's limit."""
    if dataset is None:
        return report
    out: dict[str, set[str] | None] = {}
    for n, allowed in report.items():
        other = dataset.get(n)
        out[n] = other if allowed is None else (allowed if other is None else allowed & other)
    return out


def can_build(session, context, row: db.Dataset) -> bool:
    """May choose this dataset as a report's data source (an open one: anyone who may manage the report)."""
    if (row.access_mode or "open") != "restricted" or bypasses(context):
        return True
    return bool(_grants_for(session, context, row.id, ("build",)))


def validate_limits(parameters: list[dict], limits: Any) -> dict[str, list[str]]:
    """A grant's filter limits against the dataset's filters: only filters with a list of choices, only values from a
    fixed list (a filter whose choices come from an API can't be checked here, only at run time), never empty."""
    if not limits:
        return {}
    if not isinstance(limits, dict):
        raise DataConfigError("Limits must map a filter's name to its allowed values")
    defined = {p["name"]: p for p in parameters}
    cleaned: dict[str, list[str]] = {}
    for name, values in limits.items():
        definition = defined.get(name)
        if definition is None:
            raise DataConfigError(f"{name!r} isn't a filter of this dataset")
        options = definition.get("options")
        if options is None and definition.get("options_source") is None:
            raise DataConfigError(f"{name!r} has no list of choices, so it can't be limited")
        if not isinstance(values, list) or not values:
            raise DataConfigError(f"The limit for {name!r} is empty, which would allow nothing -- leave it out to keep it unrestricted")
        if not all(isinstance(v, str) and v.strip() and len(v) <= MAX_VALUE_LENGTH for v in values):
            raise DataConfigError(f"An invalid value was given for {name!r}")
        if options is not None:
            unknown = sorted(set(values) - {o["value"] for o in options})
            if unknown:
                raise DataConfigError(f"Not a choice of {name!r}: {', '.join(unknown)}")
        cleaned[name] = sorted(set(values))
    return cleaned
