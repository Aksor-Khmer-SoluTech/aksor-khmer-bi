"""Where a Render-report job's files go, and splitting a job into one file per value of a filter ("bursting", as
Oracle BI Publisher calls it). Called by job_executors.execute_render_report for every real run.

A job's config may add, next to report_id / format / parameters / context:

    "destination_path": "/data/output/sales-{value}-{timestamp}.pdf"   # save to a folder (optional now)
    "email": {"connection": "company-mail",                            # a Mail Server connection's name
              "to": ["finance@example.com"], "cc": [...],              # get every file
              "subject": "Daily sales · {{ p_branch_label }} · {{ date }}",
              "body": "..."}
    "burst": {"by": "p_branch",                                        # a filter with a list of choices
              "values": [{"value": "BR01", "to": [...], "cc": [...]}, ...],
              "skip_empty": true}                                      # no mail for a value with no data

Each value -- or the one unsplit run -- becomes one row of the run's history (db.JobDelivery): sent, saved,
failed (with the reason) or skipped. One value failing doesn't stop the others. The file is kept under
data/job_outputs for JOB_OUTPUT_DAYS (30) days, so a failed email is re-sent with the very report that failed
(`resend`), not a fresh one with different data.

Retrying: a run where nothing could be delivered, and every failure might pass on its own (the database or the mail
server down), is retried as a whole -- the job's own retry settings. Once anything went out, the run finishes as
it is, so a retry never mails the same file twice; what failed is re-sent from its history.

Who may split by what is settled when the job is saved (routers/jobs.py): only values of a filter its creator
could run themselves.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import TemplateSyntaxError, meta as jinja_meta
from jinja2.sandbox import SandboxedEnvironment

from . import connections, db, mailer, report_data, report_store
from .job_executors import PermanentJobError, RetryableJobError, _write_file, render_with_data
from .report_data import DataConfigError

_log = logging.getLogger("aksor_khmer_bi.job_delivery")

_REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = _REPO_ROOT / "data" / "job_outputs"
MAX_BURST_VALUES = 200
SUBJECT_MAX = 300
BODY_MAX = 10_000
_ENV = SandboxedEnvironment(autoescape=False, keep_trailing_newline=True)


def keep_days() -> int:
    raw = os.environ.get("JOB_OUTPUT_DAYS", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    # Keeps Khmer and other letters: a file name people recognise, minus what a file system or mail client chokes on.
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "-", text.strip()).strip("-.")
    return cleaned[:80] or "report"


# --- checking a job's delivery settings (when it is saved) --------------------------------------------------------


def template_names(definitions: list[dict]) -> set[str]:
    names = {"report", "date", "job", "value", "value_label"}
    for d in definitions:
        names.update({d["name"], f"{d['name']}_label"})
    return names


def _check_template(text: object, where: str, limit: int, allowed: set[str]) -> str:
    if not isinstance(text, str):
        raise DataConfigError(f"{where} must be text")
    if len(text) > limit:
        raise DataConfigError(f"{where} is too long (at most {limit:,} characters)")
    try:
        used = jinja_meta.find_undeclared_variables(_ENV.parse(text))
    except TemplateSyntaxError as exc:
        raise DataConfigError(f"{where}: {exc.message}") from exc
    unknown = sorted(used - allowed)
    if unknown:
        raise DataConfigError(f"{where} uses {', '.join('{{ ' + u + ' }}' for u in unknown)}, which isn't a filter of the report"
                              f" -- you can use {', '.join(sorted('{{ ' + a + ' }}' for a in allowed))}")
    return text


def validate(config: dict, definitions: list[dict], limits: dict, org_id: str) -> dict:
    """The delivery part of a Render-report job's config, normalized: `email`, `burst`, and that a file goes
    somewhere. `definitions` are the report's filters (choice lists already resolved), `limits` what the person
    saving the job may pick. Raises DataConfigError (a 400 for the form); a burst value outside the saver's access
    is a ParameterError(403), as on the run page."""
    out: dict = {}
    allowed = template_names(definitions)

    email = config.get("email")
    if email is not None:
        if not isinstance(email, dict):
            raise DataConfigError("email must be an object")
        name = email.get("connection")
        if not name or connections.smtp_config_by_name(name, org_id) is None:
            raise DataConfigError("Choose a mail server (Manage → Connections → New Mail Server)")
        out["email"] = {
            "connection": name,
            "to": mailer.validate_addresses(email.get("to"), "To"),
            "cc": mailer.validate_addresses(email.get("cc"), "CC"),
            "subject": _check_template(email.get("subject") or "{{ report }}", "The subject", SUBJECT_MAX, allowed),
            "body": _check_template(email.get("body") or "", "The message", BODY_MAX, allowed),
        }

    burst = config.get("burst")
    if burst is not None:
        if not isinstance(burst, dict):
            raise DataConfigError("burst must be an object")
        by = burst.get("by")
        definition = next((d for d in definitions if d["name"] == by), None)
        if definition is None:
            raise DataConfigError("Split by: choose one of the report's filters")
        if definition.get("options") is None:
            raise DataConfigError(f"Split by: {definition.get('label') or by} has no list of choices to split into")
        if by in (config.get("parameters") or {}):
            raise DataConfigError(f"{definition.get('label') or by} is what the job splits by, so it can't also be a fixed filter value")
        choices = {o["value"]: o for o in definition["options"]}
        values = burst.get("values")
        if not isinstance(values, list) or not values:
            raise DataConfigError("Split by: pick at least one value")
        if len(values) > MAX_BURST_VALUES:
            raise DataConfigError(f"Split by: at most {MAX_BURST_VALUES} values in one job")
        limit = limits.get(by)
        cleaned_values: list[dict] = []
        for item in values:
            value = item.get("value") if isinstance(item, dict) else None
            if value not in choices:
                raise DataConfigError(f"Split by: {value!r} isn't one of {definition.get('label') or by}'s choices")
            if limit is not None and value not in limit:
                raise report_data.ParameterError(403, f"You don't have access to that {definition.get('label') or by}")
            if any(v["value"] == value for v in cleaned_values):
                continue
            label = choices[value].get("label") or value
            cleaned_values.append({
                "value": value,
                "to": mailer.validate_addresses(item.get("to"), f"To for {label}"),
                "cc": mailer.validate_addresses(item.get("cc"), f"CC for {label}"),
            })
        out["burst"] = {"by": by, "values": cleaned_values, "skip_empty": burst.get("skip_empty", True) is not False}

    has_folder = bool((config.get("destination_path") or "").strip())
    if "email" not in out and not has_folder:
        raise DataConfigError("Say where the report goes: save it to a folder, email it, or both")
    if "email" in out:
        everyone = out["email"]["to"] + out["email"]["cc"]
        per_value = any(v["to"] or v["cc"] for v in out.get("burst", {}).get("values", []))
        if not everyone and not per_value and not has_folder:
            raise DataConfigError("Add at least one email address")
    return out


# --- running it ---------------------------------------------------------------------------------------------------


@dataclass
class _Item:
    value: str | None
    label: str | None
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)


def _has_no_data(data: dict) -> bool:
    lists = [v for v in data.values() if isinstance(v, list)]
    return bool(lists) and all(len(v) == 0 for v in lists)


def _clean_old_outputs() -> None:
    cutoff = time.time() - keep_days() * 86400
    if not OUTPUT_DIR.is_dir():
        return
    for run_dir in OUTPUT_DIR.iterdir():
        try:
            if run_dir.is_dir() and run_dir.stat().st_mtime < cutoff:
                shutil.rmtree(run_dir, ignore_errors=True)
        except OSError:
            pass


def _record(**fields) -> db.JobDelivery:
    with db.SessionLocal() as session:
        row = db.JobDelivery(created_at=_now(), **fields)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def _update(delivery_id: str, **fields) -> None:
    with db.SessionLocal() as session:
        row = session.get(db.JobDelivery, delivery_id)
        if row is None:  # its job was deleted meanwhile, history and all
            return
        for key, value in fields.items():
            setattr(row, key, value)
        session.commit()


def run(config: dict, job_id: str, run_id: str) -> str:
    """Render the report (once, or once per burst value), keep each file, save and/or email it, and record each one.
    Returns the run's summary ("3 sent, 1 failed"); raises RetryableJobError when nothing went out but trying again
    may help, PermanentJobError when nothing went out and it won't."""
    _clean_old_outputs()
    with db.SessionLocal() as session:
        # A retried run starts over: forget what the failed attempt recorded (nothing of it went out).
        session.query(db.JobDelivery).filter(db.JobDelivery.run_id == run_id).delete()
        job = session.get(db.Job, job_id)
        job_name = job.name if job else ""
        org_id = job.org_id if job else None
        session.commit()

    try:
        report_id = report_store.resolve_ref(config["report_id"])
        meta = report_store.get_report(report_id)
    except report_store.ReportNotFoundError as exc:
        raise PermanentJobError(f"Report {config['report_id']!r} not found") from exc
    try:
        definitions = report_data.resolve_parameter_definitions(
            meta.get("parameters") or [], materialize=lambda source: connections.materialize(source, meta["org_id"])
        )
    except report_data.DataSourceError as exc:
        raise RetryableJobError(f"Couldn't load the report's filter choices: {exc}") from exc
    labels = {d["name"]: {o["value"]: o.get("label") or o["value"] for o in d.get("options") or []} for d in definitions}

    burst = config.get("burst")
    if burst:
        items = [_Item(v["value"], labels.get(burst["by"], {}).get(v["value"], v["value"]), v.get("to") or [], v.get("cc") or []) for v in burst["values"]]
    else:
        items = [_Item(None, None)]

    email = config.get("email")
    server = None
    if email:
        saved = connections.smtp_config_by_name(email["connection"], org_id)
        if saved is None:
            raise PermanentJobError(f"The mail server {email['connection']!r} no longer exists -- choose another in the job")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    today = datetime.now(report_data._report_timezone()).strftime("%d/%m/%Y")
    run_dir = OUTPUT_DIR / run_id
    counts = {"sent": 0, "saved": 0, "failed": 0, "skipped": 0}
    retryable_failures = 0
    went_out = False  # a file emailed or saved to the folder: from then on a whole-run retry would duplicate it
    session_mail: mailer.Session | None = None

    try:
        for item in items:
            parameters = dict(config.get("parameters") or {})
            if burst:
                parameters[burst["by"]] = item.value
            base = {"run_id": run_id, "job_id": job_id, "burst_value": item.value, "burst_label": item.label}

            try:
                content, data = render_with_data(report_id, config["format"], config.get("context") or {}, parameters)
            except (RetryableJobError, PermanentJobError) as exc:
                _record(**base, status="failed", reason=str(exc)[:1000])
                counts["failed"] += 1
                retryable_failures += isinstance(exc, RetryableJobError)
                continue

            if burst and burst.get("skip_empty", True) and _has_no_data(data):
                _record(**base, status="skipped", reason="No data for this value, so nothing was sent")
                counts["skipped"] += 1
                continue

            name_parts = [meta["name"]] + ([item.label or item.value] if burst else []) + [datetime.now(report_data._report_timezone()).strftime("%Y-%m-%d")]
            file_name = _slug("-".join(p for p in name_parts if p)) + "." + config["format"]
            run_dir.mkdir(parents=True, exist_ok=True)
            kept = run_dir / file_name
            if kept.exists():
                kept = run_dir / f"{kept.stem}-{(item.value or 'x')[:20]}{kept.suffix}"
            kept.write_bytes(content)

            saved_to = None
            if (config.get("destination_path") or "").strip():
                try:
                    saved_to = config["destination_path"].format(job_id=job_id, timestamp=stamp, value=_slug(item.value or ""))
                    _write_file(saved_to, content)
                    went_out = True
                except (RetryableJobError, PermanentJobError, KeyError, ValueError) as exc:
                    _record(**base, status="failed", reason=f"Saving the file failed: {exc}"[:1000], file_name=file_name,
                            file_path=str(kept), size_bytes=len(content))
                    counts["failed"] += 1
                    retryable_failures += isinstance(exc, RetryableJobError)
                    continue

            to = (email or {}).get("to", []) + [a for a in item.to if a not in (email or {}).get("to", [])]
            cc = [a for a in (email or {}).get("cc", []) + item.cc if a not in to]
            if not email or not (to or cc):
                status = "saved" if saved_to else "skipped"
                _record(**base, status=status, reason=None if saved_to else "Nobody to send it to", file_name=file_name,
                        file_path=str(kept), size_bytes=len(content), saved_to=saved_to)
                counts[status] += 1
                continue

            variables = {
                **{d["name"]: "" for d in definitions},
                **{f"{d['name']}_label": "" for d in definitions},
                **{k: str(v) for k, v in data.items() if k in {d["name"] for d in definitions}},
                **{f"{k}_label": labels.get(k, {}).get(str(v), str(v)) for k, v in parameters.items()},
                "report": meta["name"], "date": today, "job": job_name,
                "value": item.value or "", "value_label": item.label or "",
            }
            try:
                subject = _ENV.from_string(email["subject"]).render(**variables)
                body = _ENV.from_string(email["body"]).render(**variables)
            except Exception as exc:  # a template that slipped past validation (a filter renamed since)
                _record(**base, status="failed", reason=f"The subject or message couldn't be filled in: {exc}"[:1000],
                        file_name=file_name, file_path=str(kept), size_bytes=len(content), saved_to=saved_to)
                counts["failed"] += 1
                continue

            delivery = _record(**base, status="failed", reason="Not sent yet", file_name=file_name, file_path=str(kept),
                               size_bytes=len(content), saved_to=saved_to, email_to=to, email_cc=cc, subject=subject, body=body)
            try:
                if session_mail is None:
                    session_mail = mailer.Session(connections.resolve_smtp(saved, org_id, where="Job email"))
                note = session_mail.send(mailer.Message(to=to, cc=cc, subject=subject, body=body,
                                                        attachment=mailer.Attachment(file_name, content)))
                _update(delivery.id, status="sent", reason=note, sent_at=_now(), attempts=1)
                counts["sent"] += 1
                went_out = True
            except (mailer.MailError, report_data.DataSourceError) as exc:
                _update(delivery.id, status="failed", reason=str(exc)[:1000], attempts=1)
                counts["failed"] += 1
                retryable_failures += getattr(exc, "retryable", False)
    finally:
        if session_mail is not None:
            session_mail.__exit__(None, None, None)

    summary = ", ".join(f"{n} {k}" for k, n in counts.items() if n) or "nothing to do"
    if not went_out and counts["failed"]:
        if retryable_failures == counts["failed"]:
            raise RetryableJobError(summary)
        raise PermanentJobError(summary)
    return summary


def resend(run_id: str) -> str:
    """Send again every email of a run that failed, with the very file and message that failed. Returns a summary."""
    with db.SessionLocal() as session:
        rows = session.query(db.JobDelivery).filter(db.JobDelivery.run_id == run_id, db.JobDelivery.status == "failed").all()
        job = session.get(db.Job, rows[0].job_id) if rows else None
        pending = [(r.id, r.file_name, r.file_path, list(r.email_to or []), list(r.email_cc or []), r.subject or "", r.body or "", r.attempts) for r in rows]
    if not pending or job is None:
        return "nothing to re-send"
    email = (job.config or {}).get("email")
    saved = connections.smtp_config_by_name(email["connection"], job.org_id) if email else None
    if saved is None:
        return "the job has no mail server any more"
    sent = failed = 0
    with mailer.Session(connections.resolve_smtp(saved, job.org_id, where="Job email")) as session_mail:
        for delivery_id, file_name, file_path, to, cc, subject, body, attempts in pending:
            if not to and not cc:
                continue  # a failure before mailing (the data source, say): only a new run can fix that
            if not file_path or not Path(file_path).is_file():
                _update(delivery_id, reason="The file is gone (older than the days files are kept); run the job again")
                failed += 1
                continue
            try:
                note = session_mail.send(mailer.Message(to=to, cc=cc, subject=subject, body=body,
                                                        attachment=mailer.Attachment(file_name, Path(file_path).read_bytes())))
                _update(delivery_id, status="sent", reason=note, sent_at=_now(), attempts=attempts + 1)
                sent += 1
            except mailer.MailError as exc:
                _update(delivery_id, reason=str(exc)[:1000], attempts=attempts + 1)
                failed += 1
    return f"re-sent {sent}" + (f", {failed} still failing" if failed else "")
