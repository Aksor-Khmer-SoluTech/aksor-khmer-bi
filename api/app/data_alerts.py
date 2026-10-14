"""Data alerts: a job (job_type "data_alert") that works out one dataset measure on its schedule and emails when it
crosses a threshold -- "tell me when net sales for Phnom Penh drop below 50,000,000 ៛".

It runs later, unattended, with nobody's grants in force -- so, like a report job, it may only do what its creator
could do when saving it: analyze that dataset with those filter values (checked here, on every save of the config).
The executor then trusts the stored values.

By default it emails when the condition *starts* to hold, not on every check while it stays true (`repeat`
"on_change"): the previous run's summary says whether it was already triggered. "every_time" emails on every check
that finds it true. Every check is a job run, so the job's run history shows each value it saw.

The "outlier" condition compares instead of thresholding: the measure is worked out for each value of a field
(`group_by` -- each branch, each product) and it alerts when any of them stands out from the rest, by z-score or
interquartile range (analyze.outlier_limits) -- "tell me when a branch's sales are unusual", with no fixed number to
pick. Its `threshold` is then the method's sensitivity (2 standard deviations, 1.5 IQR).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from . import analyze, connections, datasets, db, mailer, report_data
from .report_data import DataConfigError, ParameterError

CONDITIONS = {"above": "rises above", "below": "drops below", "outlier": "stands out from the rest"}
REPEATS = ("on_change", "every_time")
TRIGGERED = "Triggered:"


def validate(context, org_id: str, config: dict) -> dict:
    """The config to store, cleaned. Raises DataConfigError (400) or ParameterError (the run page's 400/403)."""
    with db.SessionLocal() as session:
        row = datasets.row_by_name(session, org_id, config.get("dataset") or "")
        if row is None or not analyze.can_use(session, context, row):
            raise DataConfigError("Choose a dataset you may analyze")
        definitions = analyze._definitions(row)
        limits = analyze._limits(session, context, row, [d["name"] for d in definitions])
    values = config.get("values") or {}
    if not isinstance(values, dict):
        raise DataConfigError("values must map each filter's name to a value")
    report_data.resolve_run_parameters(definitions, limits, values)  # the creator's own access, now
    measure = config.get("measure")
    measures = {m["key"]: m for m in row.measures or []}
    if measure != analyze.COUNT_KEY and measure not in measures:
        raise DataConfigError("Choose the measure to watch")
    condition = config.get("condition")
    if condition not in CONDITIONS:
        raise DataConfigError("Alert when it rises above or drops below the threshold, or when one stands out")
    extra: dict = {}
    if condition == "outlier":
        spec = analyze.check_outliers({"method": config.get("method"), "threshold": config.get("threshold")})
        group_by = config.get("group_by")
        if not group_by:
            raise DataConfigError("Choose the field to compare across -- each branch, each product…")
        analyze.check_layout({"rows": [group_by], "values": [measure], "outliers": spec}, row.fields or [], row.measures or [])
        threshold, extra = spec["threshold"], {"group_by": group_by, "method": spec["method"]}
    else:
        threshold = config.get("threshold")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            raise DataConfigError("The threshold must be a number")
    repeat = config.get("repeat") or "on_change"
    if repeat not in REPEATS:
        raise DataConfigError("Email when it starts to hold, or on every check")
    email = config.get("email") or {}
    name = email.get("connection")
    if not name or connections.smtp_config_by_name(name, org_id) is None:
        raise DataConfigError("Choose a mail server (Manage → Connections → New Mail Server)")
    to = mailer.validate_addresses(email.get("to"), "To")
    if not to:
        raise DataConfigError("Who gets the alert? Add at least one address")
    title = (config.get("title") or "").strip() or f"{row.title}: {_measure_label(row, measure)}"
    return {
        "dataset": row.name, "values": values, "measure": measure, "condition": condition, "threshold": float(threshold),
        "repeat": repeat, "title": title[:200], **extra,
        "email": {"connection": name, "to": to, "cc": mailer.validate_addresses(email.get("cc"), "CC")},
    }


def _measure_label(row: db.Dataset, key: str) -> str:
    if key == analyze.COUNT_KEY:
        return "Rows"
    return next((m.get("label") or key for m in row.measures or [] if m["key"] == key), key)


def _fetch(config: dict, org_id: str) -> tuple[dict, db.Dataset]:
    """The dataset's data now, for the stored filter values."""
    with db.SessionLocal() as session:
        row = datasets.row_by_name(session, org_id, config["dataset"])
        if row is None:
            raise report_data.DataSourceError(f"The dataset {config['dataset']!r} this alert watches no longer exists")
        session.expunge(row)
    definitions = analyze._definitions(row)
    params = report_data.resolve_run_parameters(definitions, {d["name"]: None for d in definitions}, config.get("values") or {})
    data = report_data.fetch_report_data(
        connections.materialize(row.data_source, row.org_id), params, {d["name"]: d.get("type") or "text" for d in definitions}
    )
    return data, row


def evaluate(config: dict, org_id: str) -> tuple[float | None, str, db.Dataset]:
    """The measure's value now, over all the data for the stored filter values: (number, its text, the dataset)."""
    data, row = _fetch(config, org_id)
    if config["measure"] == analyze.COUNT_KEY:
        _, rows = analyze._list(data, None)
        return float(len(rows)), f"{len(rows):,}", row
    texts, numbers = datasets.compute_measures(row.measures or [], data)
    return numbers.get(config["measure"]), texts.get(config["measure"], ""), row


def evaluate_outliers(config: dict, org_id: str) -> tuple[list[dict], int, db.Dataset]:
    """The groups that stand out now: ([{name, text, side}], how many were compared, the dataset)."""
    data, row = _fetch(config, org_id)
    layout = analyze.check_layout(
        {"rows": [config["group_by"]], "values": [config["measure"]], "outliers": {"method": config["method"], "threshold": config["threshold"]}},
        row.fields or [], row.measures or [],
    )
    result = analyze.pivot(data, layout, row.measures or [])
    found = [
        {"name": "(blank)" if key[0] is None else str(key[0]), "text": line[0][0]["t"], "side": line[0][0]["o"]}
        for key, line in zip(result["row_keys"], result["cells"]) if line[0] and line[0][0].get("o")
    ]
    return found, sum(1 for line in result["cells"] if line[0] and line[0][0]["v"] is not None), row


def _was_triggered(job_id: str, run_id: str | None) -> bool:
    with db.SessionLocal() as session:
        query = select(db.JobRun.result_summary).where(db.JobRun.job_id == job_id, db.JobRun.status == "succeeded")
        if run_id:
            query = query.where(db.JobRun.id != run_id)
        last = session.scalar(query.order_by(db.JobRun.finished_at.desc()).limit(1))
    return bool(last and last.startswith(TRIGGERED))


def _field_label(row: db.Dataset, name: str) -> str:
    return next((f.get("label") or name for f in row.fields or [] if f["name"] == name), name)


def run(config: dict, job_id: str, run_id: str | None = None) -> str:
    """One check. Returns the run's summary -- which says the value, whether it crossed, and who was emailed."""
    with db.SessionLocal() as session:
        job = session.get(db.Job, job_id)
        org_id = job.org_id if job else None
    if config["condition"] == "outlier":
        found, compared, row = evaluate_outliers(config, org_id)
        label, by = _measure_label(row, config["measure"]), _field_label(row, config["group_by"])
        how = f"z-score beyond {config['threshold']:g}" if config["method"] == "zscore" else f"{config['threshold']:g} × IQR beyond the quartiles"
        if not found:
            return f"Not triggered: no {by} stands out on {label} ({compared} compared, {how})"
        listed = ", ".join(f"{f['name']} {f['text']} ({f['side']})" for f in found)
        seen = f"{len(found)} {by} {'stands' if len(found) == 1 else 'stand'} out on {label}: {listed}"
        lines = [f"{label} by {by} -- these stand out from the other {compared - len(found)} ({how}):"]
        lines += [f"  • {f['name']}: {f['text']} ({'unusually high' if f['side'] == 'high' else 'unusually low'})" for f in found]
        again = seen
    else:
        value, text, row = evaluate(config, org_id)
        label = _measure_label(row, config["measure"])
        threshold = config["threshold"]
        threshold_text = report_data_format(row, config["measure"], threshold)
        crossed = value is not None and (value > threshold if config["condition"] == "above" else value < threshold)
        if not crossed:
            return f"Not triggered: {label} is {text or '—'} (alerts when it {CONDITIONS[config['condition']]} {threshold_text})"
        seen = f"{label} is {text}, {config['condition']} {threshold_text}"
        again = f"{label} is {text}, still {config['condition']} {threshold_text}"
        lines = [f"{label} is {text} -- it {CONDITIONS[config['condition']]} {threshold_text}."]
    if config.get("repeat", "on_change") == "on_change" and _was_triggered(job_id, run_id):
        return f"{TRIGGERED} {again} -- already emailed, not again"
    email = config["email"]
    server = connections.smtp_config_by_name(email["connection"], org_id)
    if server is None:
        raise report_data.DataSourceError(f"The mail server {email['connection']!r} this alert uses no longer exists")
    filters = ", ".join(f"{k}: {v}" for k, v in (config.get("values") or {}).items())
    body = (
        f"{config['title']}\n\n"
        + "\n".join(lines) + "\n"
        + (f"Filters: {filters}\n" if filters else "")
        + f"Dataset: {row.title}\n\n"
        "Sent by Aksor Khmer. Change or stop this alert under Manage → Jobs."
    )
    with mailer.Session(connections.resolve_smtp(server, org_id, where="Data alert")) as session_mail:
        note = session_mail.send(mailer.Message(to=email["to"], cc=email.get("cc") or [], subject=f"Alert: {config['title']}", body=body))
    sent = len(email["to"]) + len(email.get("cc") or [])
    return f"{TRIGGERED} {seen} -- emailed {sent} {'person' if sent == 1 else 'people'}" + (f" ({note})" if note else "")


def report_data_format(row: db.Dataset, key: str, number: float) -> str:
    """The threshold in the measure's own format, so "below 50,000,000 ៛" reads like the value it's compared with."""
    measure = next((m for m in row.measures or [] if m["key"] == key), None)
    return datasets.format_number(number, measure.get("format") if measure else None)


__all__ = ["validate", "run", "evaluate", "ParameterError", "DataConfigError", "Any"]
