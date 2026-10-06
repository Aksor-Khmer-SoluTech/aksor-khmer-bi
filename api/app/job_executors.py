"""The four job action types (`Job.job_type`) a scheduled/manually/API-
triggered job can perform. Called from app/celery_app.py's `run_job`
task -- executors themselves never touch Celery or the scheduler, they
just do one unit of work and return a short human-readable summary
string (stored in `JobRun.result_summary`) or raise.

Config shapes, one per job_type (`Job.config`, a JSON dict):

  render_report -- {"report_id": str, "format": "docx"|"pdf"|"png"|"xlsx",
                    "context": dict, "destination_path": str}
      Renders exactly like POST /api/v1/reports/{id}/render (same
      doc_engine.render() call, same report_store lookup), then writes
      the bytes to `destination_path`. The common "just run this report
      on a schedule and drop the result somewhere" case -- see
      `file_output`'s source="render_report" for the same rendering
      logic reached through the more general action type instead.
      `destination_path` may reference "{job_id}" and "{timestamp}"
      (substituted with a filesystem-safe UTC timestamp) so repeated
      firings don't overwrite each other by default.

  rest_call -- {"url": str, "method": "GET"|"POST"|"PUT"|"PATCH"|"DELETE",
                "headers": dict | None, "body_template": dict | str | None,
                "context": dict | None,
                "auth": {"type": "basic", "username": str, "password_env": str}
                      | {"type": "bearer", "token_env": str} | None}
      `body_template`'s string values (recursively, if a dict) go through
      Jinja2 `{{ }}` substitution against `context` -- same templating
      convention used everywhere else in this project (docxtpl/xltpl
      placeholders). `auth`'s secret is an *environment variable name*,
      never a value stored in the job config itself -- same pattern as
      LdapConfig.service_bind_password_env (app/db.py).

  soap_call -- {"wsdl_url": str, "operation": str, "params": dict,
                "auth": {...} | None}
      Executed via zeep -- the modern replacement for the long-dead
      `suds`, and the "thin adapter" api/README.md already said SOAP
      would need if a real consumer showed up.

  file_output -- {"destination_path": str, "source": "static"|"render_report",
                  "content": str,  # source="static" only, written as-is (UTF-8)
                  "report_id": str, "format": str, "context": dict  # source="render_report" only
                 }
      The general "write bytes to a configured location" action --
      either a static payload (e.g. a plain semaphore/flag file for a
      downstream system to notice) or a freshly-rendered report (same
      code path as the `render_report` job_type, reached here instead
      through the general action type).

Retry semantics (see app/celery_app.py's run_job task, which reads
`RetryableJobError` vs. everything else to decide whether to retry):
transient network/5xx failures calling REST/SOAP endpoints raise
`RetryableJobError`; a bad job config (unknown report_id, malformed
URL), an HTTP 4xx, or a filesystem permission error raise
`PermanentJobError` (or let the underlying exception propagate
unwrapped) -- retrying a permission error or a malformed request isn't
going to fix it, so it isn't classified as retryable just because it's
convenient to.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from jinja2 import Template
from zeep import Client as SoapClient
from zeep.exceptions import Fault as SoapFault
from zeep.transports import Transport

from . import report_store
from .context_media import ImageResolutionError, resolve_image_refs
from .db import Job

_RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


class RetryableJobError(Exception):
    """A transient failure worth retrying (network error, 5xx, timeout)."""


class PermanentJobError(Exception):
    """A failure retrying won't fix (bad config, 4xx, permission denied)."""


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve_secret(env_var_name: str) -> str:
    value = os.environ.get(env_var_name)
    if not value:
        raise PermanentJobError(f"Environment variable {env_var_name!r} is not set")
    return value


def _render_bytes(report_id: str, fmt: str, context: dict) -> bytes:
    """Shared by `render_report` and `file_output(source="render_report")`
    -- exactly the same lookup + render call POST /reports/{id}/render
    makes (app/routers/reports.py's `_render_one`), so a scheduled render
    and an on-demand one are guaranteed to behave identically.
    """
    from doc_engine import ConversionError
    from doc_engine import render as doc_render

    try:
        # A job's config may reference the report by its code as well as its id.
        report_id = report_store.resolve_ref(report_id)
        meta = report_store.get_report(report_id)
        template_path = report_store.get_template_path(report_id)
    except report_store.ReportNotFoundError as exc:
        raise PermanentJobError(f"Report {report_id!r} not found") from exc

    allowed = {"docx": {"docx", "pdf", "png"}, "xlsx": {"xlsx"}}[meta["template_ext"]]
    if fmt not in allowed:
        raise PermanentJobError(f"Report {report_id!r} is a .{meta['template_ext']} template; format {fmt!r} unsupported")

    try:
        context = resolve_image_refs(context, meta["org_id"])
    except ImageResolutionError as exc:
        raise PermanentJobError(str(exc)) from exc

    try:
        return doc_render(context, fmt, template_path=template_path)
    except ConversionError as exc:
        raise RetryableJobError(f"Rendering failed: {exc}") from exc


def _write_file(destination_path: str, content: bytes) -> str:
    path = Path(destination_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    except PermissionError as exc:
        raise PermanentJobError(f"Permission denied writing to {destination_path!r}") from exc
    except OSError as exc:
        # Disk full, a network share that's momentarily unreachable, etc.
        # -- worth retrying, unlike a permission error.
        raise RetryableJobError(f"Failed writing to {destination_path!r}: {exc}") from exc
    return f"wrote {len(content)} bytes to {destination_path}"


def execute_render_report(config: dict, job_id: str) -> str:
    report_id = config["report_id"]
    fmt = config["format"]
    context = config.get("context", {})
    destination_path = config["destination_path"].format(job_id=job_id, timestamp=_now_stamp())
    content = _render_bytes(report_id, fmt, context)
    return _write_file(destination_path, content)


def execute_file_output(config: dict, job_id: str) -> str:
    source = config.get("source", "static")
    destination_path = config["destination_path"].format(job_id=job_id, timestamp=_now_stamp())

    if source == "static":
        content = config.get("content", "").encode("utf-8")
    elif source == "render_report":
        content = _render_bytes(config["report_id"], config["format"], config.get("context", {}))
    else:
        raise PermanentJobError(f"Unknown file_output source: {source!r}")

    return _write_file(destination_path, content)


def _render_template_value(value, context: dict):
    if isinstance(value, str):
        return Template(value).render(**context)
    if isinstance(value, dict):
        return {k: _render_template_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_template_value(v, context) for v in value]
    return value


def _build_auth(auth_config: dict | None) -> httpx.Auth | None:
    if not auth_config:
        return None
    if auth_config["type"] == "basic":
        return httpx.BasicAuth(auth_config["username"], _resolve_secret(auth_config["password_env"]))
    if auth_config["type"] == "bearer":
        # httpx has no built-in bearer-auth helper; a header is simplest.
        return None  # handled via header injection in execute_rest_call instead
    raise PermanentJobError(f"Unknown auth type: {auth_config['type']!r}")


def execute_rest_call(config: dict, job_id: str) -> str:  # noqa: ARG001 -- job_id kept for a consistent executor signature
    context = config.get("context", {})
    headers = dict(config.get("headers") or {})
    auth_config = config.get("auth")
    if auth_config and auth_config["type"] == "bearer":
        headers["Authorization"] = f"Bearer {_resolve_secret(auth_config['token_env'])}"

    body = config.get("body_template")
    json_body = _render_template_value(body, context) if body is not None else None

    try:
        resp = httpx.request(
            config.get("method", "POST"),
            config["url"],
            headers=headers,
            json=json_body if isinstance(json_body, (dict, list)) else None,
            content=json_body if isinstance(json_body, str) else None,
            auth=_build_auth(auth_config),
            timeout=30.0,
        )
    except httpx.RequestError as exc:
        raise RetryableJobError(f"Request to {config['url']!r} failed: {exc}") from exc

    if resp.status_code in _RETRYABLE_HTTP_STATUS:
        raise RetryableJobError(f"{config['url']} returned {resp.status_code}")
    if resp.status_code >= 400:
        raise PermanentJobError(f"{config['url']} returned {resp.status_code}: {resp.text[:500]}")

    return f"{config.get('method', 'POST')} {config['url']} -> {resp.status_code}"


def execute_soap_call(config: dict, job_id: str) -> str:  # noqa: ARG001
    auth_config = config.get("auth")
    transport = Transport(timeout=30)
    if auth_config and auth_config["type"] == "basic":
        transport.session.auth = (auth_config["username"], _resolve_secret(auth_config["password_env"]))

    try:
        client = SoapClient(config["wsdl_url"], transport=transport)
        operation = getattr(client.service, config["operation"])
        result = operation(**config.get("params", {}))
    except SoapFault as exc:
        raise PermanentJobError(f"SOAP fault calling {config['operation']!r}: {exc}") from exc
    except httpx.RequestError as exc:  # pragma: no cover -- zeep uses requests, not httpx, in practice
        raise RetryableJobError(str(exc)) from exc
    except Exception as exc:  # zeep wraps transport errors in various requests.* exception types
        message = str(exc)
        if "Connection" in type(exc).__name__ or "Timeout" in type(exc).__name__:
            raise RetryableJobError(f"SOAP transport error calling {config['wsdl_url']!r}: {message}") from exc
        raise PermanentJobError(f"SOAP call to {config['wsdl_url']!r} failed: {message}") from exc

    return f"SOAP {config['operation']} -> {result!r}"[:500]


_EXECUTORS = {
    "render_report": execute_render_report,
    "rest_call": execute_rest_call,
    "soap_call": execute_soap_call,
    "file_output": execute_file_output,
}


def execute(job: Job) -> str:
    executor = _EXECUTORS.get(job.job_type)
    if executor is None:
        raise PermanentJobError(f"Unknown job_type: {job.job_type!r}")
    return executor(job.config, job.id)
