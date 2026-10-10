"""Filter parameters + the server-side data source behind an end-user
report run (routers/reports.py's `run-form` and `run`).

Why this exists: a report's *data* has to come from somewhere the caller
of a run doesn't control, otherwise "this user may only see branch BR01"
is just a dropdown the user could bypass by typing their own numbers. So
a report can carry

  - `parameters`: the filter parameters the run form asks for (each
    optionally an enumerated `options` list -- the kind a grant can
    narrow, see rbac.effective_parameter_limits -- either static or,
    via `options_source`, fetched from a REST API at run-form/run time;
    see `resolve_parameter_definitions`, which turns the latter into
    the former before anything else in this module has to care), and
  - `data_source`: a REST call the *server* makes with the validated
    parameter values, whose JSON response becomes the render context.

The order of operations in a run is the whole security model: resolve any
options_source parameters -> resolve the caller's limits -> reject any
parameter value they may not use (403) -> only then call the data source
with the surviving values. Nothing here trusts the browser to have
filtered anything.

Data source config shape (`Report.data_source`):

  {"type": "rest",                       # the only kind today; a JDBC one would slot in beside it
   "connection": "erp" | None,           # a named connection (app/connections.py): its base URL,
                                         # headers and authentication are used, and `url` is just the path
   "url": "https://erp.example/api/sales?branch={{ p_branch }}"   # (or "/api/sales?branch=..." with a connection)
   "method": "GET" | "POST",
   "headers": {"X-Api-Version": "2"} | None,
   "body_template": {"branch": "{{ p_branch }}"} | "raw {{ text }}" | None,   # POST only
   "auth": {"type": "bearer", "token_env": "ERP_TOKEN"} | {"type": "bearer", "token_secret": "erp-token"}
         | {"type": "basic", "username": "svc", "password_env": "ERP_PASSWORD"}
         | {"type": "basic", "username": "svc", "password_secret": "erp-password"} | None}

A credential is never a value here: either the *name* of an environment
variable on the API server (same convention scheduled jobs' rest_call,
app/job_executors.py, uses), or the *name* of a Secret -- a credential
created, rotated and revoked in the portal (Admin > Secrets; app/secrets.py),
encrypted at rest and resolved only for the one call that needs it.
Exactly one of the two names the credential; which one is a deployment's
choice, made per data source or connection. With a `connection`, the fetch functions below
still receive one plain, complete source dict -- the router turns the
reference into it first (connections.materialize), so nothing in here has to
know connections exist. Differences that matter for a config an
end user's run triggers: the scheme/host must be literal text (a
parameter can't steer where the server connects), substituted URL values
are percent-encoded, redirects aren't followed, and the response is
size-capped.
"""
from __future__ import annotations

import calendar
import copy
import json
import logging
import os
import re
from datetime import date, datetime, time, timezone
from typing import Any, Callable
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, UndefinedError, meta

from . import jsonpath

_log = logging.getLogger("aksor_khmer_bi.report_data")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")
# Literal http(s) scheme + a host with no template braces in it.
_URL_PREFIX_RE = re.compile(r"^https?://[^/{}\s?#]+", re.IGNORECASE)

# A free-text parameter's declared input shape (models.ReportParameter.type)
# -- meaningless once options/options_source is set, since that's always a
# <select> regardless. Shapes match what the matching HTML input type
# actually submits (native date/time/datetime-local pickers), so a value
# a real browser control produced always passes.
PARAMETER_TYPES = {"text", "number", "date", "datetime", "time"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")

# A default of exactly this text, on a date/datetime/time parameter, means "the
# moment the report is run" -- see resolve_default.
NOW_EXPRESSION = "now()"
_NOW_TYPES = {"date", "datetime", "time"}
# ...and these mean the first / last day of the month the report is run in. A
# time has no day, so they only apply to date and datetime (a datetime reads
# 00:00 on the first day and 23:59 on the last).
FIRST_DAY_EXPRESSION = "firstDayOfMonth()"
LAST_DAY_EXPRESSION = "lastDayOfMonth()"
_MONTH_EXPRESSIONS = {FIRST_DAY_EXPRESSION, LAST_DAY_EXPRESSION}
_MONTH_TYPES = {"date", "datetime"}
# What a connection is called in a report's config: same shape as a report code.
CONNECTION_NAME_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
MAX_CONNECTION_NAME_LENGTH = 64

MAX_PARAMETERS = 20
MAX_OPTIONS = 1000
MAX_VALUE_LENGTH = 200
MAX_URL_LENGTH = 2000
MAX_HEADERS = 20
MAX_HEADER_VALUE_LENGTH = 1000
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
TIMEOUT_SECONDS = 15.0

# Headers httpx (or the connection) owns; letting a config set them only
# invites request-smuggling-shaped surprises.
_FORBIDDEN_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}


class DataConfigError(ValueError):
    """The manager-supplied parameters/data source are invalid (-> 400)."""


class ParameterError(ValueError):
    """A run request's parameter values are unacceptable; carries the HTTP
    status to answer with (400 malformed, 403 not permitted)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class DataSourceError(RuntimeError):
    """The data source couldn't be reached or answered badly (-> 502).
    The message is safe to show the end user -- it never carries the
    upstream body, URL, or credentials (those go to the server log)."""


def _env() -> Environment:
    return Environment(undefined=StrictUndefined, autoescape=False)


def _label(definition: dict) -> str:
    return definition.get("label") or definition["name"]


# --- validating what a manager saves -----------------------------------


def validate_data_config(
    parameters: list[dict],
    data_source: dict | None,
    connection_names: set[str] | None = None,
    secret_names: set[str] | None = None,
    connection_kinds: dict[str, str] | None = None,
) -> tuple[list[dict], dict | None]:
    """Strict validation + normalization of a PUT /data-config body.
    Returns cleaned copies; raises DataConfigError with a message a
    manager can act on. `connection_names`/`secret_names` are what exists in
    the report's organization: a source naming any other is refused. None
    skips that check (callers with no database to ask)."""
    cleaned_parameters = _validate_parameters(parameters, connection_names, secret_names, connection_kinds)
    if data_source is None:
        return cleaned_parameters, None
    return cleaned_parameters, _validate_data_source(
        data_source, {p["name"] for p in cleaned_parameters}, connection_names, secret_names, connection_kinds
    )


def _validate_default(name: str, type_: str, raw: Any) -> str | None:
    """A free-text parameter's default: a literal of the parameter's type, or
    `now()` on a date/datetime/time one, or `firstDayOfMonth()` /
    `lastDayOfMonth()` on a date/datetime one. Blank means no default."""
    if raw is None:
        return None
    default = str(raw).strip()
    if not default:
        return None
    if len(default) > MAX_VALUE_LENGTH:
        raise DataConfigError(f"The default value for {name!r} is too long (max {MAX_VALUE_LENGTH} characters)")
    if re.sub(r"\s+", "", default).lower() == NOW_EXPRESSION:
        if type_ not in _NOW_TYPES:
            raise DataConfigError(f"{name!r} is {type_} input, so it can't default to now() -- that only works for date, datetime and time")
        return NOW_EXPRESSION
    compact = re.sub(r"\s+", "", default).lower()
    for expression in _MONTH_EXPRESSIONS:
        if compact in (expression.lower(), expression.lower().removesuffix("()")):
            if type_ not in _MONTH_TYPES:
                raise DataConfigError(f"{name!r} is {type_} input, so it can't default to {expression} -- that only works for date and datetime")
            return expression
    if not _value_is_real(default, type_):
        example = {"number": "12.5", "date": "2026-09-30", "datetime": "2026-09-30T08:00", "time": "08:00"}[type_]
        raise DataConfigError(f"The default value for {name!r} isn't a valid {type_} -- write it like {example}" + (", or use now()" if type_ in _NOW_TYPES else "") + (", firstDayOfMonth() or lastDayOfMonth()" if type_ in _MONTH_TYPES else ""))
    return default


def _value_is_real(value: str, type_: str) -> bool:
    """Shape *and* sense (no 2026-02-30) -- for a default a manager types by
    hand. A run's value only has to match the shape a browser control submits."""
    if not _value_matches_type(value, type_):
        return False
    try:
        if type_ == "date":
            date.fromisoformat(value)
        elif type_ == "time":
            time.fromisoformat(value)
        elif type_ == "datetime":
            datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_parameters(
    parameters: list[dict],
    connection_names: set[str] | None = None,
    secret_names: set[str] | None = None,
    connection_kinds: dict[str, str] | None = None,
) -> list[dict]:
    if len(parameters) > MAX_PARAMETERS:
        raise DataConfigError(f"A report can have at most {MAX_PARAMETERS} filter parameters")
    cleaned: list[dict] = []
    seen: set[str] = set()
    for raw in parameters:
        name = (raw.get("name") or "").strip()
        if not _IDENTIFIER_RE.match(name):
            raise DataConfigError(
                f"Parameter name {name!r} is invalid -- use letters, digits and underscores, not starting with a digit (e.g. p_branch)"
            )
        if name in seen:
            raise DataConfigError(f"Parameter {name!r} is defined more than once")
        seen.add(name)

        label = (raw.get("label") or "").strip() or None
        if label is not None and len(label) > MAX_VALUE_LENGTH:
            raise DataConfigError(f"The label for {name!r} is too long (max {MAX_VALUE_LENGTH} characters)")

        type_ = (raw.get("type") or "text").strip()
        if type_ not in PARAMETER_TYPES:
            raise DataConfigError(f"{name!r} has an invalid type {type_!r} -- use one of: {', '.join(sorted(PARAMETER_TYPES))}")

        required_raw = raw.get("required")
        required = True if required_raw is None else bool(required_raw)

        entry: dict[str, Any] = {
            "name": name,
            "label": label,
            "type": type_,
            "required": required,
            "default_value": None,
            "options": None,
            "options_source": None,
        }
        options = raw.get("options")
        options_source = raw.get("options_source")
        default_value = _validate_default(name, type_, raw.get("default_value"))
        if default_value is not None and (options is not None or options_source is not None):
            raise DataConfigError(
                f"{name!r} can't have a default value while it's a choice list -- a default is for free-text, date and time "
                "parameters (choices come from the list itself)"
            )
        entry["default_value"] = default_value
        if options is not None and options_source is not None:
            raise DataConfigError(f"{name!r} can't have both a static option list and an options source -- choose one")
        if not required and (options is not None or options_source is not None):
            raise DataConfigError(
                f"{name!r} can't be optional while it's a choice list -- a grant can restrict which options someone may "
                "pick, and letting them skip it entirely would bypass that; only free-text parameters can be optional"
            )
        if options is not None:
            if not options:
                raise DataConfigError(f"{name!r} has an empty option list -- add at least one option, or remove the list to make it free text")
            if len(options) > MAX_OPTIONS:
                raise DataConfigError(f"{name!r} has too many options (max {MAX_OPTIONS})")
            values: set[str] = set()
            entry["options"] = []
            for option in options:
                value = (option.get("value") or "").strip()
                if not value:
                    raise DataConfigError(f"{name!r} has an option with an empty value")
                if len(value) > MAX_VALUE_LENGTH:
                    raise DataConfigError(f"An option value for {name!r} is too long (max {MAX_VALUE_LENGTH} characters)")
                if value in values:
                    raise DataConfigError(f"{name!r} lists the option {value!r} more than once")
                values.add(value)
                option_label = (option.get("label") or "").strip() or None
                entry["options"].append({"value": value, "label": option_label})
        elif options_source is not None:
            entry["options_source"] = _validate_options_source(options_source, name, connection_names, secret_names, connection_kinds)
        cleaned.append(entry)
    return cleaned


def _template_variables(source: str, where: str) -> set[str]:
    try:
        return meta.find_undeclared_variables(_env().parse(source))
    except TemplateSyntaxError as exc:
        raise DataConfigError(f"Template syntax error in the data source {where}: {exc.message}") from exc


def source_parameter_names(data_source: dict | None) -> list[str]:
    """The filters a data source refers to, in order of first use: a database query's `:name` placeholders, a REST
    source's `{{ name }}` in its URL or body. What the New report wizard turns into filter parameters, so nobody
    has to declare them by hand first. Raises DataConfigError for a query or template that doesn't parse."""
    if not data_source:
        return []
    kind = data_source.get("type") or "rest"
    if kind == "jdbc":
        from . import jdbc

        return jdbc.validate_query(data_source.get("query"))
    if kind != "rest":
        return []
    names: list[str] = []
    texts = [data_source.get("url") or ""] + list(_walk_strings(data_source.get("body_template")))
    for text in texts:
        for name in sorted(_template_variables(text, "URL" if text is texts[0] else "body")):
            if name not in names:
                names.append(name)
    return names


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v)


def _validate_url(raw_url: str, where: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        raise DataConfigError(f"The {where} needs a URL")
    if len(url) > MAX_URL_LENGTH:
        raise DataConfigError(f"The {where} URL is too long (max {MAX_URL_LENGTH} characters)")
    if not _URL_PREFIX_RE.match(url):
        raise DataConfigError(
            f"The {where} URL must start with a literal http:// or https:// scheme and host -- "
            "parameters can only appear after the host, so a value can't steer where the server connects"
        )
    return url


def _validate_connection_ref(raw: Any, connection_names: set[str] | None, where: str) -> str | None:
    """The connection a source names, once it's known to exist -- or None for a
    source that spells out its own URL."""
    name = (raw or "").strip() if isinstance(raw, str) else None
    if not name:
        return None
    if len(name) > MAX_CONNECTION_NAME_LENGTH or not CONNECTION_NAME_RE.match(name):
        raise DataConfigError(f"{name!r} isn't a valid connection name")
    if connection_names is not None and name not in connection_names:
        raise DataConfigError(
            f"The {where} uses the connection {name!r}, which doesn't exist in this organization -- "
            "create it under Admin > Connections, or pick another"
        )
    return name


def _validate_secret_ref(raw: Any, secret_names: set[str] | None, where: str) -> str | None:
    """The Secret a credential names -- or None when it isn't set (an
    environment variable name is used instead). Same slug shape as a
    connection name; `secret_names` is the *active* secrets that exist in the
    org, so a revoked or unknown one is refused at save time the same way an
    unknown connection is."""
    name = (raw or "").strip() if isinstance(raw, str) else None
    if not name:
        return None
    if len(name) > MAX_CONNECTION_NAME_LENGTH or not CONNECTION_NAME_RE.match(name):
        raise DataConfigError(f"{name!r} isn't a valid credential name")
    if secret_names is not None and name not in secret_names:
        raise DataConfigError(
            f"The {where} uses the credential {name!r}, which doesn't exist (or has been revoked) in this "
            "organization -- create it under Admin > Secrets, or pick another"
        )
    return name


def _validate_request_url(raw_url: Any, connection: str | None, where: str) -> str:
    """The URL of a source: complete (http(s) scheme + host written out) when it
    has no connection; otherwise just what follows the connection's base URL --
    a path (or a bare query), so it can never say where to connect."""
    if connection is None:
        return _validate_url(raw_url, where)
    url = (raw_url or "").strip()
    if len(url) > MAX_URL_LENGTH:
        raise DataConfigError(f"The {where} URL is too long (max {MAX_URL_LENGTH} characters)")
    if url and url[0] not in "/?":
        raise DataConfigError(
            f"The {where} URL is added after the connection's base URL, so it must start with / (or ?) -- "
            "e.g. /api/v1/branches. Leave the connection empty to write a full URL instead"
        )
    return url


def _validate_headers_and_auth(
    raw: dict, where: str, secret_names: set[str] | None = None
) -> tuple[dict[str, str] | None, dict | None]:
    """The header-name/size and auth-shape rules `data_source` and
    `options_source` both need -- factored out so the two paths can't
    quietly drift apart. `where` only flavors error messages.

    A credential is exactly one of two things, never both: the *name* of an
    environment variable on the API server, or the *name* of a Secret
    (app/secrets.py) -- a credential managed in the portal. Either way, only
    the name is ever part of this dict; the value is resolved elsewhere,
    right before the one call that needs it."""
    headers = raw.get("headers") or None
    if headers is not None:
        if len(headers) > MAX_HEADERS:
            raise DataConfigError(f"At most {MAX_HEADERS} custom headers are supported")
        for name, value in headers.items():
            if not _HEADER_NAME_RE.match(name):
                raise DataConfigError(f"Header name {name!r} is invalid")
            if name.lower() in _FORBIDDEN_HEADERS:
                raise DataConfigError(f"The {name!r} header is set automatically and can't be overridden")
            if len(value) > MAX_HEADER_VALUE_LENGTH:
                raise DataConfigError(f"The value of header {name!r} is too long")

    auth = raw.get("auth") or None
    if auth is not None:
        if auth["type"] == "bearer":
            token_env = (auth.get("token_env") or "").strip()
            token_secret = _validate_secret_ref(auth.get("token_secret"), secret_names, where)
            if token_env and token_secret:
                raise DataConfigError("Choose either an environment variable or a saved credential for the token, not both")
            if token_env and not _IDENTIFIER_RE.match(token_env):
                raise DataConfigError(f"Bearer auth on the {where} needs the name of the environment variable holding the token")
            if not token_env and not token_secret:
                raise DataConfigError(f"Bearer auth on the {where} needs a token -- an environment variable name, or a saved credential")
            auth = {"type": "bearer", **({"token_env": token_env} if token_env else {"token_secret": token_secret})}
            if headers and any(h.lower() == "authorization" for h in headers):
                raise DataConfigError("Remove the Authorization header -- the configured auth sets it")
        else:
            username = (auth.get("username") or "").strip()
            password_env = (auth.get("password_env") or "").strip()
            password_secret = _validate_secret_ref(auth.get("password_secret"), secret_names, where)
            if not username:
                raise DataConfigError(f"Basic auth on the {where} needs a username")
            if password_env and password_secret:
                raise DataConfigError("Choose either an environment variable or a saved credential for the password, not both")
            if password_env and not _IDENTIFIER_RE.match(password_env):
                raise DataConfigError(f"{password_env!r} isn't a valid environment variable name")
            if not password_env and not password_secret:
                raise DataConfigError(f"Basic auth on the {where} needs a password -- an environment variable name, or a saved credential")
            auth = {
                "type": "basic",
                "username": username,
                **({"password_env": password_env} if password_env else {"password_secret": password_secret}),
            }

    return headers, auth


MAX_STATIC_BYTES = 1024 * 1024


def _validate_static_source(raw: dict) -> dict:
    data = raw.get("static_data")
    if not isinstance(data, dict):
        raise DataConfigError("Sample data must be a JSON object, e.g. {\"rows\": [{\"name\": \"A\"}]}")
    try:
        size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise DataConfigError("The sample data isn't valid JSON") from exc
    if size > MAX_STATIC_BYTES:
        raise DataConfigError(f"The sample data is too large (max {MAX_STATIC_BYTES // 1024} KB)")
    return {"type": "static", "static_data": data}


def _validate_jdbc_source(
    raw: dict, parameter_names: set[str], connection_names: set[str] | None, connection_kinds: dict[str, str] | None
) -> dict:
    from . import jdbc

    connection = _validate_connection_ref(raw.get("connection"), connection_names, "data source")
    if connection is None:
        raise DataConfigError("A database source needs a connection -- choose one, or create it under Admin > Connections")
    if connection_kinds is not None and connection_kinds.get(connection) not in (None, "jdbc"):
        raise DataConfigError(f"The connection {connection!r} isn't a database connection")
    query = raw.get("query")
    used = jdbc.validate_query(query)
    unknown = sorted(set(used) - parameter_names)
    if unknown:
        raise DataConfigError(
            "The query uses "
            + ", ".join(":" + name for name in unknown)
            + " but no filter parameter with that name is defined"
        )
    root_key = (raw.get("root_key") or "").strip() or None
    if root_key is not None and not jdbc.ROOT_KEY_RE.match(root_key):
        raise DataConfigError("The result name must be letters, digits and underscores, starting with a letter (e.g. rows)")
    return {
        "type": "jdbc",
        "connection": connection,
        "query": query.strip(),
        "root_key": root_key,
        # Off unless asked for: switching it on changes what an existing CAST / TO_DATE receives.
        "typed_binding": raw.get("typed_binding") is True,
    }


def _validate_data_source(
    raw: dict,
    parameter_names: set[str],
    connection_names: set[str] | None = None,
    secret_names: set[str] | None = None,
    connection_kinds: dict[str, str] | None = None,
) -> dict:
    kind = raw.get("type") or "rest"
    if kind == "static":
        return _validate_static_source(raw)
    if kind == "jdbc":
        return _validate_jdbc_source(raw, parameter_names, connection_names, connection_kinds)
    if kind != "rest":
        raise DataConfigError(f"Data source type {kind!r} isn't supported")
    connection = _validate_connection_ref(raw.get("connection"), connection_names, "data source")
    if connection is not None and connection_kinds is not None and connection_kinds.get(connection) not in (None, "rest"):
        raise DataConfigError(f"The connection {connection!r} is a database connection -- use it with a database source")
    url = _validate_request_url(raw.get("url"), connection, "data source")

    method = raw.get("method") or "GET"
    if method not in ("GET", "POST"):
        raise DataConfigError("The data source method must be GET or POST")

    body_template = raw.get("body_template")
    if body_template is not None and method != "POST":
        raise DataConfigError("A request body is only sent with POST -- switch the method or clear the body")
    if isinstance(body_template, str) and not body_template.strip():
        body_template = None

    headers, auth = _validate_headers_and_auth(raw, "data source", secret_names)
    if connection is not None and auth is not None:
        raise DataConfigError("Authentication comes from the connection -- clear it here, or use a different connection")

    # Every {{ variable }} the url/body use must be a defined parameter --
    # catches a typo now instead of as a failed run later.
    used = _template_variables(url, "URL")
    if body_template is not None:
        for text in _walk_strings(body_template):
            used |= _template_variables(text, "body")
    unknown = sorted(used - parameter_names)
    if unknown:
        raise DataConfigError(
            "The data source uses "
            + ", ".join("{{ " + name + " }}" for name in unknown)
            + " but no filter parameter with that name is defined"
        )

    return {
        "type": kind,
        "connection": connection,
        "url": url,
        "method": method,
        "headers": headers,
        "body_template": body_template,
        "auth": auth,
    }


def validate_options_source(
    raw: dict,
    parameter_name: str,
    connection_names: set[str] | None = None,
    secret_names: set[str] | None = None,
    connection_kinds: dict[str, str] | None = None,
) -> dict:
    """Strict validation + normalization of one options source -- what a
    parameter's own save does, exposed so the portal's "Test" button can vet
    an unsaved draft the same way before calling it."""
    return _validate_options_source(raw, parameter_name, connection_names, secret_names, connection_kinds)


def _validate_options_source(
    raw: dict,
    parameter_name: str,
    connection_names: set[str] | None = None,
    secret_names: set[str] | None = None,
    connection_kinds: dict[str, str] | None = None,
) -> dict:
    """Shape-only, like _validate_data_source -- no live HTTP call at save
    time. No {{ }} substitution to check either: options_source doesn't
    see the caller's other parameter values (see OptionsSource's
    docstring), so there's nothing to resolve here yet."""
    connection = _validate_connection_ref(raw.get("connection"), connection_names, "options source")
    if connection is not None and connection_kinds is not None and connection_kinds.get(connection) not in (None, "rest"):
        raise DataConfigError(f"The connection {connection!r} is a database connection -- a choice list is fetched from a REST API")
    url = _validate_request_url(raw.get("url"), connection, "options source")

    method = raw.get("method") or "GET"
    if method not in ("GET", "POST"):
        raise DataConfigError("The options source method must be GET or POST")

    body = raw.get("body")
    if body is not None and method != "POST":
        raise DataConfigError("A request body is only sent with POST -- switch the method or clear the body")

    headers, auth = _validate_headers_and_auth(raw, "options source", secret_names)
    if connection is not None and auth is not None:
        raise DataConfigError("Authentication comes from the connection -- clear it here, or use a different connection")

    items_path = (raw.get("items_path") or "").strip() or None
    value_field = (raw.get("value_field") or "").strip()
    if not value_field:
        raise DataConfigError(f"{parameter_name!r}'s options source needs a value -- which field of each item to use as the option's value (e.g. code)")
    label_field = (raw.get("label_field") or "").strip() or None
    for text, what in ((items_path, "items path"), (value_field, "value"), (label_field, "label")):
        if text is not None and len(text) > MAX_VALUE_LENGTH:
            raise DataConfigError(f"{parameter_name!r}'s options source {what} is too long")
    try:
        if items_path is not None:
            jsonpath.parse(items_path)
        jsonpath.parse_expression(value_field, where="value")
        if label_field is not None:
            jsonpath.parse_expression(label_field, where="label")
    except jsonpath.JsonPathError as exc:
        raise DataConfigError(f"{parameter_name!r}'s options source: {exc}") from exc

    return {
        "connection": connection,
        "url": url,
        "method": method,
        "headers": headers,
        "body": body,
        "auth": auth,
        "items_path": items_path,
        "value_field": value_field,
        "label_field": label_field,
    }


# --- resolving a run request -------------------------------------------


def allowed_options(definition: dict, limit: set[str] | None) -> list[dict] | None:
    """A parameter's options narrowed to what `limit` permits (None means
    unrestricted). Free-text parameters (no option list) return None."""
    options = definition.get("options")
    if options is None:
        return None
    if limit is None:
        return list(options)
    return [option for option in options if option["value"] in limit]


def _value_matches_type(value: str, type_: str) -> bool:
    """Shape-check a free-text value against its declared input type --
    matches what a browser's own native date/time/datetime-local/number
    input actually submits, so a value that control produced always
    passes; only a value someone typed straight into the request body
    (bypassing the picker) can fail this."""
    if type_ == "number":
        try:
            float(value)
        except ValueError:
            return False
        return True
    if type_ == "date":
        return bool(_DATE_RE.match(value))
    if type_ == "time":
        return bool(_TIME_RE.match(value))
    if type_ == "datetime":
        return bool(_DATETIME_RE.match(value))
    return True  # "text" -- anything within MAX_VALUE_LENGTH is fine


def _report_timezone():
    """The zone `now()` defaults are read in (REPORT_TIMEZONE, an IANA name such
    as Asia/Phnom_Penh; UTC when unset). The portal fills its run form from the
    viewer's own clock, so this only matters to a run that leaves a parameter
    out -- an API caller, an embed."""
    name = os.environ.get("REPORT_TIMEZONE", "").strip()
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        _log.warning("REPORT_TIMEZONE=%r isn't a known time zone; using UTC for now() defaults", name)
        return timezone.utc


def resolve_default(definition: dict, now: datetime | None = None) -> str | None:
    """A parameter's default as the value a run would use: its literal, or --
    for `now()` on a date/datetime/time parameter -- the current date, time or
    both, in the shape the matching browser control submits. `firstDayOfMonth()`
    and `lastDayOfMonth()` give that day of the current month. None = no default."""
    default = definition.get("default_value")
    if default is None or default == "":
        return None
    if default not in (NOW_EXPRESSION, *_MONTH_EXPRESSIONS):
        return default
    moment = now or datetime.now(_report_timezone())
    type_ = definition.get("type", "text")
    if default in _MONTH_EXPRESSIONS:
        if type_ not in _MONTH_TYPES:
            return None
        if default == FIRST_DAY_EXPRESSION:
            day, clock = 1, "00:00"
        else:
            day, clock = calendar.monthrange(moment.year, moment.month)[1], "23:59"
        stamp = f"{moment.year:04d}-{moment.month:02d}-{day:02d}"
        return stamp if type_ == "date" else f"{stamp}T{clock}"
    if type_ == "date":
        return moment.strftime("%Y-%m-%d")
    if type_ == "time":
        return moment.strftime("%H:%M")
    if type_ == "datetime":
        return moment.strftime("%Y-%m-%dT%H:%M")
    return None


def resolve_run_parameters(
    definitions: list[dict], limits: dict[str, set[str] | None], supplied: dict[str, str]
) -> dict[str, str]:
    """Validate the values a user submitted against the report's parameter
    definitions and the limits their grants impose. Returns the resolved
    {name: value}; raises ParameterError otherwise.

    A value outside a *restricted* parameter's allowed set is a 403 whether
    or not it's a real option -- answering "not a valid choice" only for
    values that don't exist would let a user enumerate the option list
    they're not supposed to see.

    A parameter with a default that the request leaves out (no key at all)
    takes the default. One sent as an empty string stays empty: that is the
    caller saying "none", not forgetting -- the run form sends every filter,
    so a person who clears a pre-filled optional field gets exactly that.
    """
    defined = {d["name"]: d for d in definitions}
    unknown = sorted(set(supplied) - set(defined))
    if unknown:
        raise ParameterError(400, "Unknown parameter(s): " + ", ".join(unknown))

    resolved: dict[str, str] = {}
    for definition in definitions:
        name = definition["name"]
        value = supplied.get(name)
        if value is None:
            value = resolve_default(definition)
        if value is None or value == "":
            # Only a free-text parameter can be required=False at all
            # (validate_data_config enforces that at save time) -- so
            # trusting the flag here never lets a grant-restricted choice
            # list be silently skipped.
            if not definition.get("required", True):
                resolved[name] = ""
                continue
            raise ParameterError(400, f"Choose a value for {_label(definition)}")
        if len(value) > MAX_VALUE_LENGTH:
            raise ParameterError(400, f"The value for {_label(definition)} is too long")

        options = definition.get("options")
        if options is not None:
            limit = limits.get(name, set())  # a missing entry fails closed
            if limit is not None and value not in limit:
                raise ParameterError(403, f"You don't have access to that {_label(definition)}")
            if value not in {o["value"] for o in options}:
                raise ParameterError(400, f"That isn't a valid choice for {_label(definition)}")
        elif not _value_matches_type(value, definition.get("type", "text")):
            raise ParameterError(400, f"The value for {_label(definition)} isn't a valid {definition.get('type', 'text')}")
        resolved[name] = value
    return resolved


# --- fetching the data -------------------------------------------------


def _make_client() -> httpx.Client:
    # Redirects are never followed: a 30x from a compromised or misconfigured
    # upstream must not be able to bounce the server to another host.
    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)


def _body_escaper(headers: dict[str, str] | None) -> Callable[[str], str]:
    """How a filter value is made safe inside a *raw string* request body, by the
    body's declared Content-Type: a JSON string, XML text or a urlencoded form
    value can't then break out of its slot and add structure (a `"`, a `<`, an
    `&`). A structured (dict/list) body needs none -- it is serialised whole. A
    body of any other type is sent as the plain text it is."""
    content_type = next((v for k, v in (headers or {}).items() if k.lower() == "content-type"), "").lower()
    if "json" in content_type:
        return lambda v: json.dumps(v, ensure_ascii=False)[1:-1]
    if "xml" in content_type or "html" in content_type:
        return lambda v: xml_escape(v, {'"': "&quot;", "'": "&apos;"})
    if "x-www-form-urlencoded" in content_type:
        return lambda v: quote(v, safe="")
    return lambda v: v


def _render_value(value: Any, env: Environment, params: dict[str, str], raw_escape: Callable[[str], str] | None = None) -> Any:
    if isinstance(value, str):
        if raw_escape is not None:
            return env.from_string(value).render(**{k: raw_escape(v) for k, v in params.items()})
        return env.from_string(value).render(**params)
    if isinstance(value, dict):
        return {k: _render_value(v, env, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_value(v, env, params) for v in value]
    return value


def _apply_auth(auth: dict | None, headers: dict[str, str]) -> httpx.Auth | None:
    """`auth` arrives here already resolved to a literal `token`/`password` --
    connections.materialize is the one place a data source or options source
    passes through before reaching this module, and it turns whichever
    credential name (`token_env`/`token_secret`, `password_env`/
    `password_secret`) the config carries into the actual value for this one
    call. Nothing here reads the environment or a Secret directly."""
    if auth is None:
        return None
    if auth["type"] == "bearer":
        headers["Authorization"] = f"Bearer {auth['token']}"
        return None
    return httpx.BasicAuth(auth["username"], auth["password"])


def fetch_report_data(data_source: dict, params: dict[str, str], types: dict[str, str] | None = None) -> dict:
    """Call the report's data source with the already-validated `params`
    and return its JSON object. Raises DataSourceError (safe to show) on
    any failure."""
    kind = data_source.get("type") or "rest"
    if kind == "static":
        return copy.deepcopy(data_source.get("static_data") or {})
    if kind == "jdbc":
        from . import jdbc

        if data_source.get("jdbc") is None:
            raise DataSourceError("The report's database connection wasn't resolved -- ask whoever manages this report")
        return jdbc.run_query(
            data_source["jdbc"],
            data_source["query"],
            params,
            data_source.get("root_key"),
            types=(types or {}) if data_source.get("typed_binding") else None,
        )
    env = _env()
    # Values dropped into the URL are percent-encoded so a value can never
    # add a query parameter or path segment; the body gets the raw values
    # (they land inside JSON string values, which is structure-safe).
    try:
        url = env.from_string(data_source["url"]).render(**{k: quote(v, safe="") for k, v in params.items()})
        template = data_source.get("body_template")
        body = _render_value(template, env, params, _body_escaper(data_source.get("headers")) if isinstance(template, str) else None)
    except UndefinedError as exc:
        # Saved config is validated against the parameters, but the two are
        # edited separately, so a filter can be renamed away from under it.
        _log.error("Data source refers to an undefined filter: %s", exc)
        raise DataSourceError("The report's data source refers to a filter that no longer exists -- ask whoever manages this report") from exc
    headers = dict(data_source.get("headers") or {})
    auth = _apply_auth(data_source.get("auth"), headers)

    request_kwargs: dict[str, Any] = {}
    if isinstance(body, str):
        request_kwargs["content"] = body.encode("utf-8")
    elif body is not None:
        request_kwargs["json"] = body

    try:
        with _make_client() as client:
            with client.stream(data_source.get("method", "GET"), url, headers=headers, auth=auth, **request_kwargs) as response:
                if response.status_code // 100 != 2:
                    _log.warning("Data source returned HTTP %s for %s", response.status_code, url)
                    raise DataSourceError(f"The report's data source responded with an error (HTTP {response.status_code})")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
                    raise DataSourceError("The report's data source response is too large")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise DataSourceError("The report's data source response is too large")
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        _log.warning("Data source request to %s failed: %s", url, exc)
        raise DataSourceError("Couldn't reach the report's data source") from exc

    try:
        data = json.loads(b"".join(chunks))
    except ValueError as exc:
        raise DataSourceError("The report's data source didn't return valid JSON") from exc
    if not isinstance(data, dict):
        raise DataSourceError("The report's data source must return a JSON object")
    return data


def fetch_parameter_options(source: dict) -> list[dict]:
    """Call a parameter's options_source and return its choices as
    ParameterOption-shaped dicts ({"value": ..., "label": ...}), read out of
    the JSON response with the source's JSONPaths (see _map_options). No
    Jinja substitution -- options_source doesn't reference other parameter
    values (see OptionsSource's docstring) -- so the URL/body are sent
    exactly as configured, every time. `source` is already complete: a
    connection, if it named one, has been folded in (connections.materialize).
    Raises DataSourceError (safe to show) on any failure, including a
    response the paths don't fit.

    Deliberately a separate function from fetch_report_data rather than
    a shared refactor of it: that one is well-tested and asserts a JSON
    *object*; this one maps a list of items into options, which
    fetch_report_data has no notion of. Both still go through the same
    _make_client()/_apply_auth() and the same size/timeout/redirect
    discipline below.
    """
    url = source["url"]
    headers = dict(source.get("headers") or {})
    auth = _apply_auth(source.get("auth"), headers)

    request_kwargs: dict[str, Any] = {}
    if source.get("body") is not None:
        request_kwargs["json"] = source["body"]

    try:
        with _make_client() as client:
            with client.stream(source.get("method", "GET"), url, headers=headers, auth=auth, **request_kwargs) as response:
                if response.status_code // 100 != 2:
                    _log.warning("Options source returned HTTP %s for %s", response.status_code, url)
                    raise DataSourceError(f"The options source responded with an error (HTTP {response.status_code})")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
                    raise DataSourceError("The options source response is too large")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise DataSourceError("The options source response is too large")
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        _log.warning("Options source request to %s failed: %s", url, exc)
        raise DataSourceError("Couldn't reach the options source") from exc

    try:
        payload = json.loads(b"".join(chunks))
    except ValueError as exc:
        raise DataSourceError("The options source didn't return valid JSON") from exc
    return _map_options(payload, source)


def _map_options(payload: Any, source: dict) -> list[dict]:
    """Turn a decoded options-source response into ParameterOption-shaped
    dicts, following the source's JSONPaths: `items_path` picks the list out of
    the response (the response itself, when there is none), and each item's
    value and label are read with `value_field` / `label_field` -- a plain key
    like `code`, a path like `name.en`, or a template like `${code} - ${name}`."""
    try:
        items_path = jsonpath.parse(source["items_path"]) if source.get("items_path") else None
        items = jsonpath.find_items(items_path, payload)
        value_expr = jsonpath.parse_expression(source["value_field"], where="value")
        label_expr = jsonpath.parse_expression(source["label_field"], where="label") if source.get("label_field") else None
    except jsonpath.JsonPathError as exc:
        raise DataSourceError(f"The options source: {exc}") from exc

    options: list[dict] = []
    seen: set[str] = set()
    for item in items:
        try:
            value = value_expr.evaluate(item)
            label = label_expr.evaluate(item) if label_expr else None
        except jsonpath.JsonPathError as exc:
            raise DataSourceError(f"The options source: {exc}") from exc
        if value is None:
            raise DataSourceError(f"The options source returned an item without {source['value_field']!r}")
        if not value or value in seen:
            continue  # skip blank/duplicate values rather than failing the whole list
        seen.add(value)
        options.append({"value": value, "label": label})
        if len(options) >= MAX_OPTIONS:
            break
    return options


def resolve_parameter_definitions(
    definitions: list[dict], materialize: Callable[[dict], dict] | None = None
) -> list[dict]:
    """Turn any options_source parameter into a plain static-options one
    by fetching it now, so every downstream consumer (allowed_options,
    resolve_run_parameters, rbac.effective_parameter_limits) only ever
    has to handle the one shape it already understood. Called once per
    run-form/run request -- see routers/reports.py's _authorize_run.

    `materialize` turns a source that names a connection into a complete
    one (base URL, headers, auth filled in) -- see connections.materialize;
    it raises DataSourceError when it can't."""
    resolved: list[dict] = []
    for definition in definitions:
        source = definition.get("options_source")
        if source is None:
            resolved.append(definition)
            continue
        try:
            options = fetch_parameter_options(materialize(source) if materialize else source)
        except DataSourceError as exc:
            raise DataSourceError(f"Couldn't load choices for {_label(definition)}: {exc}") from exc
        resolved.append({**definition, "options": options})
    return resolved
