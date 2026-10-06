"""JDBC data sources: a SQL query against a relational database, as a report's
data. A *connection* of kind "jdbc" (app/connections.py) says which database
and how to authenticate; a report's data source of type "jdbc"
(app/report_data.py) names that connection and carries the query.

Two ways a query is executed, chosen per connection:

* **Built in** -- PostgreSQL, MySQL and MariaDB run in this process through
  native Python drivers (psycopg, PyMySQL). Nothing to install or upload.
* **Uploaded JDBC driver** -- any other engine (Oracle, SQL Server, DB2, ...), or
  any engine whose own vendor driver is preferred. A manager uploads the
  vendor's .jar (Admin > JDBC drivers, `driver:manage`) and the query is sent to
  the `jdbc-worker` sidecar (jdbc-worker/), which loads it in a throwaway JVM.
  A .jar is code the server runs, so it never runs here: the sidecar has no
  database access and no encryption key, only the one connection's credentials
  for the one query.

Why Python can't just take a `jdbc:` URL: JDBC is a Java API, so the URL means
nothing to a Python driver. The portal shows (and builds) the standard URL for
the chosen engine, and for the built-in engines this module reads host, port
and database back out of it -- other URL options are not carried across.

Safety, in layers, because the person writing the SQL is not the person who
holds the database account:

1. The statement must be a single SELECT/WITH with no write, DDL, procedure or
   file/network functions (validate_query) -- a guard, not a sandbox.
2. The session is opened read-only where the engine supports it, with a
   statement timeout. Pointing the connection at a read-only database account
   is the real boundary, and the portal says so.
3. A report's filter values are *bound* parameters (`:fromDate`), never pasted
   into the SQL, so a value can't change the statement.
4. Where the server connects is the connection's configuration only
   (`connection:manage`), never a run's input; link-local/metadata addresses
   are always refused and JDBC_ALLOWED_HOSTS can restrict the rest.
5. Row and time limits, and driver errors never reach the person running the
   report (they go to the log).
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import logging
import os
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Callable
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID

import httpx

from .report_data import DataConfigError, DataSourceError

_log = logging.getLogger("aksor_khmer_bi.jdbc")

MAX_ROWS = int(os.environ.get("JDBC_MAX_ROWS", "20000"))
TIMEOUT_SECONDS = float(os.environ.get("JDBC_TIMEOUT_SECONDS", "30"))
MAX_QUERY_LENGTH = 20_000
MAX_RESULT_BYTES = 5 * 1024 * 1024

SSL_MODES = ("disable", "require", "verify-ca", "verify-full")
SERVICE_TYPES = ("service_name", "sid")

_DEFAULT_ROOT_KEY = "rows"
ROOT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


@dataclass(frozen=True)
class Engine:
    id: str
    label: str
    default_port: int
    driver_class: str
    # Runs in this process with no uploaded driver.
    native: bool
    # SQL a connection test runs: the cheapest statement that proves login works.
    test_query: str
    driver_url: str
    ssl_note: str
    # What the "database" field means for this engine.
    database_label: str = "Database"


ENGINES: dict[str, Engine] = {
    e.id: e
    for e in (
        Engine(
            "oracle", "Oracle", 1521, "oracle.jdbc.OracleDriver", False, "SELECT 1 FROM DUAL",
            "https://www.oracle.com/database/technologies/appdev/jdbc-downloads.html",
            "Anything but Disabled connects over TCPS; the server certificate is checked against the JVM's truststore.",
            "Service name / SID",
        ),
        Engine(
            "postgresql", "PostgreSQL", 5432, "org.postgresql.Driver", True, "SELECT 1",
            "https://jdbc.postgresql.org/download/",
            "Maps to sslmode: disable, require (encrypted, certificate not checked), verify-ca, verify-full.",
        ),
        Engine(
            "mysql", "MySQL", 3306, "com.mysql.cj.jdbc.Driver", True, "SELECT 1",
            "https://dev.mysql.com/downloads/connector/j/",
            "Maps to sslMode: DISABLED, REQUIRED (certificate not checked), VERIFY_CA, VERIFY_IDENTITY.",
        ),
        Engine(
            "sqlserver", "SQL Server", 1433, "com.microsoft.sqlserver.jdbc.SQLServerDriver", False, "SELECT 1",
            "https://learn.microsoft.com/sql/connect/jdbc/download-microsoft-jdbc-driver-for-sql-server",
            "Require encrypts without checking the certificate; the verify modes check it (CA and host name).",
        ),
        Engine(
            "mariadb", "MariaDB", 3306, "org.mariadb.jdbc.Driver", True, "SELECT 1",
            "https://mariadb.com/kb/en/about-mariadb-connector-j/",
            "Maps to sslMode: disable, trust (encrypted, certificate not checked), verify-ca, verify-full.",
        ),
        Engine(
            "db2", "IBM Db2", 50000, "com.ibm.db2.jcc.DB2Driver", False, "SELECT 1 FROM SYSIBM.SYSDUMMY1",
            "https://www.ibm.com/support/pages/db2-jdbc-driver-versions-and-downloads-single-page",
            "Anything but Disabled sets sslConnection=true; the certificate is checked against the JVM's truststore.",
        ),
    )
}


def engine_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": e.id,
            "label": e.label,
            "default_port": e.default_port,
            "driver_class": e.driver_class,
            "built_in": e.native,
            "driver_url": e.driver_url,
            "ssl_note": e.ssl_note,
            "database_label": e.database_label,
            "ssl_modes": list(SSL_MODES),
        }
        for e in ENGINES.values()
    ]


# --- the JDBC URL ------------------------------------------------------------


def _host_for_url(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def build_jdbc_url(config: dict) -> str:
    """The standard JDBC URL for a connection's structured fields."""
    engine = config["engine"]
    host = _host_for_url(config["host"])
    port = config["port"]
    database = quote(config.get("database") or "", safe="")
    mode = config.get("ssl_mode", "disable")

    if engine == "postgresql":
        return f"jdbc:postgresql://{host}:{port}/{database}?sslmode={mode}"
    if engine == "mysql":
        value = {"disable": "DISABLED", "require": "REQUIRED", "verify-ca": "VERIFY_CA", "verify-full": "VERIFY_IDENTITY"}[mode]
        return f"jdbc:mysql://{host}:{port}/{database}?sslMode={value}"
    if engine == "mariadb":
        value = {"disable": "disable", "require": "trust", "verify-ca": "verify-ca", "verify-full": "verify-full"}[mode]
        return f"jdbc:mariadb://{host}:{port}/{database}?sslMode={value}"
    if engine == "sqlserver":
        url = f"jdbc:sqlserver://{host}:{port}"
        if database:
            url += f";databaseName={database}"
        encrypt = mode != "disable"
        trust = mode in ("disable", "require")
        return url + f";encrypt={str(encrypt).lower()};trustServerCertificate={str(trust).lower()}"
    if engine == "db2":
        url = f"jdbc:db2://{host}:{port}/{database}"
        return url + (":sslConnection=true;" if mode != "disable" else "")
    if engine == "oracle":
        sid = config.get("service_type") == "sid"
        if mode == "disable":
            name = config.get("database") or ""
            return f"jdbc:oracle:thin:@{host}:{port}:{name}" if sid else f"jdbc:oracle:thin:@//{host}:{port}/{name}"
        key = "SID" if sid else "SERVICE_NAME"
        return (
            f"jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=tcps)(HOST={config['host']})(PORT={port}))"
            f"(CONNECT_DATA=({key}={config.get('database') or ''})))"
        )
    raise DataConfigError(f"Unknown database engine {engine!r}")


_ORACLE_DESCRIPTOR = re.compile(r"\((HOST|PORT|SERVICE_NAME|SID)\s*=\s*([^()\s]+)\)", re.I)


def parse_jdbc_url(url: str) -> dict[str, Any]:
    """Engine, host, port, database (and Oracle's service/SID flavour) out of a
    JDBC URL -- enough to fill the form and to check where it connects.
    Raises DataConfigError for anything it doesn't recognise. Other options in
    the URL are not returned."""
    raw = (url or "").strip()
    if not raw.lower().startswith("jdbc:"):
        raise DataConfigError("A JDBC URL starts with jdbc: -- e.g. jdbc:postgresql://db.example.com:5432/sales")
    body = raw[5:]

    if body.lower().startswith("oracle:"):
        return _parse_oracle(body)
    for engine, prefix in (("postgresql", "postgresql:"), ("mysql", "mysql:"), ("mariadb", "mariadb:"), ("sqlserver", "sqlserver:"), ("db2", "db2:")):
        if body.lower().startswith(prefix):
            rest = body[len(prefix):]
            break
    else:
        raise DataConfigError(
            "That JDBC URL isn't for one of the supported engines "
            f"({', '.join(e.label for e in ENGINES.values())})"
        )

    if not rest.startswith("//"):
        raise DataConfigError(f"Expected {raw.split('//')[0]}//host:port/... in the JDBC URL")
    if engine == "sqlserver":
        authority, _, props = rest[2:].partition(";")
        database = ""
        for pair in props.split(";"):
            key, _, value = pair.partition("=")
            if key.strip().lower() in ("databasename", "database"):
                database = value.strip()
        host, port = _split_authority(authority, engine)
        return {"engine": engine, "host": host, "port": port, "database": database, "service_type": None}

    parts = urlsplit(rest)
    host, port = _split_authority(parts.netloc, engine)
    database = unquote(parts.path.lstrip("/"))
    if engine == "db2":
        database = database.split(":", 1)[0]
    return {"engine": engine, "host": host, "port": port, "database": database, "service_type": None}


def _split_authority(authority: str, engine: str) -> tuple[str, int]:
    if "@" in authority:
        raise DataConfigError("Don't put a username or password in the JDBC URL -- use the credential below")
    if authority.startswith("["):
        host, _, rest = authority[1:].partition("]")
        port_text = rest.lstrip(":")
    else:
        host, _, port_text = authority.partition(":")
    if not host:
        raise DataConfigError("The JDBC URL has no host")
    try:
        port = int(port_text) if port_text else ENGINES[engine].default_port
    except ValueError:
        raise DataConfigError("The JDBC URL's port isn't a number") from None
    return host, port


def _parse_oracle(body: str) -> dict[str, Any]:
    rest = body[len("oracle:"):]
    if not rest.lower().startswith("thin:@"):
        raise DataConfigError("Only Oracle thin URLs are supported -- jdbc:oracle:thin:@//host:1521/service")
    target = rest[len("thin:@"):]
    if target.startswith("("):
        found = {k.upper(): v for k, v in _ORACLE_DESCRIPTOR.findall(target)}
        if "HOST" not in found:
            raise DataConfigError("The Oracle connect descriptor has no HOST")
        service_type = "sid" if "SID" in found and "SERVICE_NAME" not in found else "service_name"
        return {
            "engine": "oracle",
            "hosts": [host for _, host in _ORACLE_DESCRIPTOR.findall(target) if _.upper() == "HOST"],
            "host": found["HOST"],
            "port": int(found["PORT"]) if found.get("PORT", "").isdigit() else 1521,
            "database": found.get("SERVICE_NAME") or found.get("SID") or "",
            "service_type": service_type,
        }
    if target.startswith("//"):
        authority, _, service = target[2:].partition("/")
        host, port = _split_authority(authority, "oracle")
        return {"engine": "oracle", "host": host, "port": port, "database": service.split("?")[0], "service_type": "service_name"}
    # host:port:SID  (or host:port/service)
    match = re.match(r"^([^:/]+):(\d+)([:/])(.+)$", target)
    if not match:
        raise DataConfigError("Couldn't read that Oracle URL -- use jdbc:oracle:thin:@//host:1521/service")
    host, port, sep, name = match.groups()
    return {"engine": "oracle", "host": host, "port": int(port), "database": name, "service_type": "sid" if sep == ":" else "service_name"}


# --- where a connection may point -----------------------------------------------

_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.$#@\-]{1,128}$")
_BLOCKED_NAMES = {"metadata.google.internal", "metadata", "instance-data"}


def _blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved


def _allow_list() -> list[str]:
    return [item.strip().lower() for item in os.environ.get("JDBC_ALLOWED_HOSTS", "").split(",") if item.strip()]


def _matches_allow_list(host: str, allowed: list[str]) -> bool:
    host = host.lower()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    for item in allowed:
        if "/" in item and ip is not None:
            try:
                if ip in ipaddress.ip_network(item, strict=False):
                    return True
            except ValueError:
                continue
        elif item.startswith("*."):
            if host.endswith(item[1:]):
                return True
        elif host == item:
            return True
    return False


def check_host(host: str) -> str:
    """The host as it will be stored, or DataConfigError. No DNS here -- see
    assert_resolves_safely for what a run additionally checks."""
    cleaned = (host or "").strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    if not cleaned:
        raise DataConfigError("Enter the database host")
    try:
        ip = ipaddress.ip_address(cleaned)
    except ValueError:
        ip = None
        if not _HOST_RE.match(cleaned):
            raise DataConfigError(f"{cleaned!r} isn't a valid host name or IP address")
        if cleaned.lower() in _BLOCKED_NAMES:
            raise DataConfigError(f"{cleaned!r} can't be used as a database host")
    if ip is not None and _blocked_ip(ip):
        raise DataConfigError(f"{cleaned} is a link-local or reserved address and can't be used as a database host")
    allowed = _allow_list()
    if allowed and not _matches_allow_list(cleaned, allowed):
        raise DataConfigError(
            f"{cleaned!r} isn't on this server's list of allowed database hosts (JDBC_ALLOWED_HOSTS) -- ask whoever runs the server"
        )
    return cleaned


def assert_resolves_safely(host: str) -> None:
    """At run time, a name that resolves to a link-local/reserved address (the
    cloud metadata service, say) is refused -- the saved host name was fine
    when it was checked, DNS can change underneath it."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        _log.warning("JDBC host %s doesn't resolve: %s", host, exc)
        raise DataSourceError("Couldn't reach the report's database") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if _blocked_ip(ip):
            _log.error("JDBC host %s resolves to a blocked address (%s)", host, ip)
            raise DataSourceError("The report's database address isn't allowed")


# --- validating a connection's config ---------------------------------------------


def validate_config(config: dict, secret_names: set[str] | None, drivers: dict[str, dict] | None) -> dict:
    """Strict validation + normalization of a JDBC connection's config.

    `drivers` is {driver id: {"engine": ...}} for the organization's uploaded
    drivers (None skips the existence check). Raises DataConfigError with a
    message the person filling in the form can act on."""
    from . import report_data  # late: report_data imports nothing from here, but keep the graph one-way

    engine_id = (config.get("engine") or "").strip().lower()
    engine = ENGINES.get(engine_id)
    if engine is None:
        raise DataConfigError(f"Database engine {engine_id!r} isn't supported -- choose one of: {', '.join(ENGINES)}")

    host = check_host(config.get("host") or "")
    port = config.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise DataConfigError("The port must be a number between 1 and 65535")

    database = (config.get("database") or "").strip()
    if not database and engine_id in ("oracle", "db2", "postgresql"):
        raise DataConfigError(f"Enter the {engine.database_label.lower()}")
    if database and not _NAME_RE.match(database):
        raise DataConfigError(f"{database!r} isn't a valid {engine.database_label.lower()}")

    service_type = config.get("service_type")
    if engine_id == "oracle":
        service_type = service_type or "service_name"
        if service_type not in SERVICE_TYPES:
            raise DataConfigError("Oracle's connection type must be a service name or a SID")
    else:
        service_type = None

    ssl_mode = config.get("ssl_mode") or "disable"
    if ssl_mode not in SSL_MODES:
        raise DataConfigError(f"Secure connection mode must be one of: {', '.join(SSL_MODES)}")

    driver_id = (config.get("driver_id") or "").strip() or None
    if driver_id is None and not engine.native:
        raise DataConfigError(
            f"{engine.label} needs its JDBC driver -- upload the vendor's .jar under Admin > JDBC drivers, then choose it here"
        )
    if driver_id is not None and drivers is not None:
        found = drivers.get(driver_id)
        if found is None:
            raise DataConfigError("That JDBC driver doesn't exist in this organization -- upload it under Admin > JDBC drivers")
        if found["engine"] != engine_id:
            raise DataConfigError(f"That driver is for {ENGINES[found['engine']].label}, not {engine.label}")

    jdbc_url = (config.get("jdbc_url") or "").strip() or None
    if jdbc_url is not None:
        if driver_id is None:
            raise DataConfigError("A custom JDBC URL is only used with an uploaded driver -- the built-in drivers build theirs from the fields above")
        if len(jdbc_url) > 1000:
            raise DataConfigError("The JDBC URL is too long (max 1000 characters)")
        if any(c in jdbc_url for c in "\r\n\0"):
            raise DataConfigError("The JDBC URL can't contain line breaks")
        parsed = parse_jdbc_url(jdbc_url)
        if parsed["engine"] != engine_id:
            raise DataConfigError(f"That URL is for {ENGINES[parsed['engine']].label}, not {engine.label}")
        # The URL, not the form fields, decides where a custom-URL connection
        # connects -- so it is the one that gets the host check, for *every* address in it
        # (an Oracle descriptor can list several; the first is not the only one tried).
        for each in parsed.get("hosts") or [parsed["host"]]:
            check_host(each)
        host, port = parsed["host"], parsed["port"]
        risky = _RISKY_URL_OPTIONS.search(jdbc_url)
        if risky:
            raise DataConfigError(
                f"The JDBC URL option {risky.group(1)!r} isn't allowed -- it can load code or read files on the driver service"
            )

    auth_in = config.get("auth") or {}
    if auth_in.get("type") not in (None, "basic"):
        raise DataConfigError("A database login is a username and password")
    username = (auth_in.get("username") or "").strip()
    if not username:
        raise DataConfigError("Enter the database username")
    if len(username) > 128 or any(ord(c) < 32 for c in username):
        raise DataConfigError("That username isn't valid")
    _, auth = report_data._validate_headers_and_auth(
        {"auth": {"type": "basic", **{k: auth_in.get(k) for k in ("username", "password_env", "password_secret")}}},
        "connection",
        secret_names,
    )

    return {
        "engine": engine_id,
        "host": host,
        "port": port,
        "database": database,
        "service_type": service_type,
        "ssl_mode": ssl_mode,
        "driver_id": driver_id,
        "jdbc_url": jdbc_url,
        "auth": auth,
    }


# Driver properties that load a class by name, read or write local files, or reach other
# hosts, or carry a password into config that would be stored and shown in clear -- never needed
# to run a report query, and dangerous in a URL a person types.
_RISKY_URL_OPTIONS = re.compile(
    r"[?&;:,(]\s*("
    r"socketFactory\w*|sslfactory\w*|sslhostnameverifier|sslpasswordcallback|sslpassword|sslcert|sslkey|sslrootcert|"
    r"loggerFile|loggerLevel|autoDeserialize|allowLoadLocalInfile\w*|allowUrlInLocalInfile|allowMultiQueries|"
    r"queryInterceptors|statementInterceptors|connectionLifecycleInterceptors|authenticationPluginClassName|"
    r"trustStore\w*|keyStore\w*|jaasLoginModuleName|gsslib|clientCertificate\w*|"
    r"driverManager|initSql|connectionInitSql|ConnectionInitSql|propertiesFile|serverPropertiesFile|"
    r"password|passwd|pwd"
    r")\s*=",
    re.I,
)


def display_url(config: dict) -> str:
    """What the connections list shows: the effective JDBC URL (no credentials in it)."""
    try:
        return config.get("jdbc_url") or build_jdbc_url(config)
    except (KeyError, DataConfigError):
        return ""


# --- the SQL ------------------------------------------------------------------------

_FORBIDDEN_WORDS = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|into|lock|exec|execute|call|copy|vacuum)\b",
    re.I,
)
_FORBIDDEN_CALLS = re.compile(
    r"\b(pg_read_file|pg_read_binary_file|pg_ls_dir|pg_sleep|pg_terminate_backend|lo_import|lo_export|load_file|"
    r"sleep|benchmark|waitfor|xp_\w+|sp_\w+|openrowset|opendatasource|opendatabase|utl_\w+|dbms_\w+|sys_exec|sys_eval|"
    r"dblink\w*|query_to_xml|database_to_xml|current_setting|set_config)\b",
    re.I,
)
_PLACEHOLDER = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")


def _scan(sql: str) -> list[tuple[str, bool]]:
    """Split `sql` into (text, is_code) pieces: string literals, quoted
    identifiers and comments are not code, so a keyword or `:name` inside one
    means nothing. Comments are recognised only as `-- ` and `/* */`. A backslash is deliberately *not* an escape: engines
    disagree about it, and reading a quote as closing when the database reads
    it as escaped can only make this stricter, never hide code in a string."""
    pieces: list[tuple[str, bool]] = []
    code_start = 0
    i, n = 0, len(sql)

    def flush(end: int) -> None:
        if end > code_start:
            pieces.append((sql[code_start:end], True))

    while i < n:
        c = sql[i]
        if c in "'\"`":
            flush(i)
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:  # doubled quote = escaped
                        j += 2
                        continue
                    break
                j += 1
            else:
                raise DataConfigError(
                    "The query has an unclosed quote (a backslash doesn't escape a quote here -- write '' for a literal ')"
                )
            pieces.append((sql[i : j + 1], False))
            i = code_start = j + 1
        elif sql.startswith("--", i) and (i + 2 >= n or sql[i + 2] in " \t\r\n\f\v"):
            # A comment only where *every* engine agrees it is one: MySQL needs whitespace after
            # `--` (`1--1` is arithmetic there), and `#` is an operator in PostgreSQL. Reading a
            # comment where the database sees code would hide a second statement from the checks
            # below; reading code where the database sees a comment can only be stricter.
            flush(i)
            j = sql.find("\n", i)
            j = n if j == -1 else j
            pieces.append((sql[i:j], False))
            i = code_start = j
        elif sql.startswith("/*", i):
            if sql.startswith("/*!", i) or sql.startswith("/*M!", i):
                raise DataConfigError("MySQL/MariaDB executable comments (/*! ... */) aren't allowed in a report query")
            flush(i)
            j = sql.find("*/", i + 2)
            if j == -1:
                raise DataConfigError("The query has an unclosed /* comment")
            pieces.append((sql[i : j + 2], False))
            i = code_start = j + 2
        else:
            i += 1
    flush(n)
    return pieces


def validate_query(sql: Any) -> list[str]:
    """The query is acceptable -- returns the `:name` placeholders it uses, in
    order of first use -- or DataConfigError says why not."""
    if not isinstance(sql, str) or not sql.strip():
        raise DataConfigError("Enter the SQL query")
    if len(sql) > MAX_QUERY_LENGTH:
        raise DataConfigError(f"The query is too long (max {MAX_QUERY_LENGTH} characters)")
    if "\0" in sql:
        raise DataConfigError("The query contains an invalid character")

    code = "".join(text if is_code else " " for text, is_code in _scan(sql))
    stripped = code.strip().rstrip(";").strip()
    if ";" in stripped:
        raise DataConfigError("Only one statement is allowed -- remove the extra ; and what follows it")
    first = re.match(r"^\(*\s*(\w+)", stripped)
    if first is None or first.group(1).lower() not in ("select", "with"):
        raise DataConfigError("The query must start with SELECT (or WITH ... SELECT)")
    word = _FORBIDDEN_WORDS.search(stripped)
    if word:
        raise DataConfigError(
            f"{word.group(1).upper()} isn't allowed -- a report query can only read data. "
            "(If it's a column name, quote it, e.g. \"update\".)"
        )
    call = _FORBIDDEN_CALLS.search(stripped)
    if call:
        raise DataConfigError(f"{call.group(0)} isn't allowed in a report query")

    seen: list[str] = []
    for name in _PLACEHOLDER.findall(code):
        if name not in seen:
            seen.append(name)
    return seen


def compile_query(sql: str, style: str, values: dict[str, str]) -> tuple[str, Any]:
    """`sql` with its `:name` placeholders in the driver's own style, plus the
    bound values: pyformat (%(name)s, a dict), qmark (?, a list) or named
    (:name, a dict). Only code is touched; a `%` in a literal is escaped for
    the styles that need it."""
    out: list[str] = []
    ordered: list[str] = []

    def sub(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise DataSourceError("The report's query refers to a filter that no longer exists -- ask whoever manages this report")
        ordered.append(name)
        if style == "pyformat":
            return f"%({name})s"
        if style == "qmark":
            return "?"
        return match.group(0)

    for text, is_code in _scan(sql):
        if style == "pyformat":
            text = text.replace("%", "%%")
        out.append(_PLACEHOLDER.sub(sub, text) if is_code else text)
    compiled = "".join(out).strip().rstrip(";")
    if style == "qmark":
        return compiled, [values[name] for name in ordered]
    return compiled, {name: values[name] for name in ordered}


# --- values -> JSON -----------------------------------------------------------------


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() and value.as_tuple().exponent >= 0 else float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    return str(value)


def _rows_to_data(columns: list[str], rows: list[Any], root_key: str) -> dict:
    names: list[str] = []
    for index, column in enumerate(columns):
        name = column or f"column{index + 1}"
        while name in names:  # two columns with one name would silently lose one
            name += "_"
        names.append(name)
    data = [{name: json_safe(value) for name, value in zip(names, row)} for row in rows]
    return {root_key: data}


# --- running it -----------------------------------------------------------------------


def _ca_bundle() -> str | None:
    """A CA file the verify modes check the server's certificate against, when the deployment's
    database certificates aren't signed by a public CA (JDBC_CA_BUNDLE); otherwise the system's."""
    return os.environ.get("JDBC_CA_BUNDLE", "").strip() or None


def _ssl_context(mode: str) -> ssl.SSLContext | None:
    if mode == "disable":
        return None
    if mode == "verify-full":
        return ssl.create_default_context(cafile=_ca_bundle())
    context = ssl.create_default_context(cafile=_ca_bundle())
    context.check_hostname = False
    if mode == "require":
        context.verify_mode = ssl.CERT_NONE
    return context


def _connect_postgresql(conn: dict, password: str):
    import psycopg

    extra: dict[str, str] = {}
    if conn["ssl_mode"] in ("verify-ca", "verify-full"):
        # libpq looks for ~/.postgresql/root.crt by default, which a container never has -- so the
        # verify modes would always fail. Use the deployment's CA file, else the system store (libpq 16+).
        root = _ca_bundle() or ("system" if psycopg.pq.version() >= 160000 else None)
        if root:
            extra["sslrootcert"] = root
    connection = psycopg.connect(
        host=conn["host"], port=conn["port"], dbname=conn["database"], user=conn["username"], password=password,
        sslmode=conn["ssl_mode"], connect_timeout=int(TIMEOUT_SECONDS), **extra,
    )
    # Read-only and the time limit are set inside the transaction, not as startup options: a
    # connection pooler (PgBouncer, the usual thing on an unusual port) refuses unknown startup
    # parameters outright ("unsupported startup parameter: statement_timeout"). SET LOCAL lasts for
    # this transaction -- the query's own -- and is safe in any pooling mode.
    connection.read_only = True
    with connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL statement_timeout = {int(TIMEOUT_SECONDS * 1000)}")
    return connection


def _connect_mysql_family(conn: dict, password: str):
    import pymysql

    connection = pymysql.connect(
        host=conn["host"], port=conn["port"], user=conn["username"], password=password,
        database=conn["database"] or None, connect_timeout=int(TIMEOUT_SECONDS), read_timeout=int(TIMEOUT_SECONDS),
        ssl=_ssl_context(conn["ssl_mode"]), charset="utf8mb4",
    )
    with connection.cursor() as cursor:
        cursor.execute("SET SESSION TRANSACTION READ ONLY")
        try:
            if conn["engine"] == "mariadb":
                cursor.execute(f"SET SESSION max_statement_time={TIMEOUT_SECONDS}")
            else:
                cursor.execute(f"SET SESSION MAX_EXECUTION_TIME={int(TIMEOUT_SECONDS * 1000)}")
        except Exception:  # an old server without the setting: the read timeout above still applies
            pass
    return connection


# engine -> (connect(conn, password) -> DB-API connection, paramstyle). Tests replace entries.
_NATIVE: dict[str, tuple[Callable[[dict, str], Any], str]] = {
    "postgresql": (_connect_postgresql, "pyformat"),
    "mysql": (_connect_mysql_family, "pyformat"),
    "mariadb": (_connect_mysql_family, "pyformat"),
}


def database_alias(conn: dict) -> str:
    """A stable stand-in for a database's address -- `postgresql#3fa91c` -- to put in logs and messages
    instead of its host and port. The same database always gets the same alias, so repeated failures can be
    matched up without the address being shown."""
    digest = hashlib.sha256(f"{conn.get('engine')}|{conn.get('host')}|{conn.get('port')}|{conn.get('database')}".encode()).hexdigest()
    return f"{conn.get('engine') or 'db'}#{digest[:6]}"


# (reason, what the user is told) -- by what the driver's error says. None of the messages carries the
# driver's text: it names hosts, ports and sometimes user names.
_CONNECT_FAILURES: list[tuple[tuple[str, ...], str, str]] = [
    (("timeout", "timed out", "time out"), "timeout", "The report's database didn't answer in time. Try again in a moment, and if it keeps happening tell whoever runs the server."),
    (("refused",), "refused", "The report's database isn't accepting connections right now. Tell whoever runs the server."),
    (("translate host", "name or service not known", "nodename nor servname", "getaddrinfo", "unknown host", "name resolution"), "dns", "The report's database address can't be found. Tell whoever manages the report's connection."),
    (("unreachable", "no route"), "network", "The report's database can't be reached from the server. Tell whoever runs the server."),
    (("password authentication", "access denied", "authentication failed", "login failed", "no pg_hba"), "auth", "The report's database refused the saved login. Tell whoever manages the report's connection."),
    (("ssl", "tls", "certificate"), "tls", "The secure connection to the report's database couldn't be set up. Tell whoever manages the report's connection."),
]


def classify_connect_error(exc: BaseException) -> tuple[str, str]:
    """(short reason for the log, message for the user) for a failed connect."""
    text = str(exc).lower()
    for needles, reason, message in _CONNECT_FAILURES:
        if any(n in text for n in needles):
            return reason, message
    return "unknown", "Couldn't connect to the report's database. Tell whoever runs the server."


def typed_values(params: dict[str, str], types: dict[str, str]) -> dict[str, Any]:
    """`params` with each value turned into what its filter's type says it is -- a date, a time, a number -- so
    the driver sends a real DATE or NUMERIC and the query needs no CAST. A value that doesn't convert is
    refused rather than guessed at (the run form's own check should already have caught it). An empty value
    -- only a text filter can be left empty -- and any text filter stay text."""
    out: dict[str, Any] = {}
    for name, value in params.items():
        kind = types.get(name, "text")
        try:
            if value == "" or kind == "text":
                out[name] = value
            elif kind == "number":
                number = Decimal(value)  # exact: a float would turn 0.1 into 0.1000000000000000055...
                if not number.is_finite():
                    raise ValueError(value)
                out[name] = int(value) if re.fullmatch(r"[+-]?\d+", value.strip()) else number
            elif kind == "date":
                out[name] = date.fromisoformat(value)
            elif kind == "datetime":
                out[name] = datetime.fromisoformat(value)
            elif kind == "time":
                out[name] = time.fromisoformat(value)
            else:
                out[name] = value
        except (ValueError, ArithmeticError):
            raise DataSourceError(f"The value for the filter {name!r} isn't a valid {kind}") from None
    return out


def _run_native(conn: dict, sql: str, params: dict[str, Any], root_key: str) -> dict:
    connect, style = _NATIVE[conn["engine"]]
    compiled, bound = compile_query(sql, style, params)
    try:
        connection = connect(conn, conn["password"])
    except ImportError as exc:
        _log.error("JDBC driver for %s isn't installed: %s", conn["engine"], exc)
        raise DataSourceError("This server doesn't have the driver for that database installed") from exc
    except Exception as exc:
        reason, message = classify_connect_error(exc)
        # The log names the database by an alias too (see database_alias): it is read by more people than
        # can see the saved connection, and the host and port never need to leave it. Debug level has them.
        _log.warning("JDBC connect to %s failed (%s): %s", database_alias(conn), reason, type(exc).__name__)
        _log.debug("JDBC connect to %s:%s failed: %s", conn["host"], conn["port"], exc)
        raise DataSourceError(message) from exc
    try:
        cursor = connection.cursor()
        cursor.execute(compiled, bound)
        columns = [d[0] for d in (cursor.description or [])]
        if not columns:
            raise DataSourceError("The report's query didn't return any rows or columns")
        rows = cursor.fetchmany(MAX_ROWS + 1)
    except DataSourceError:
        raise
    except Exception as exc:
        _log.warning("JDBC query on %s:%s failed: %s", conn["host"], conn["port"], exc)
        raise DataSourceError("The report's database rejected the query") from exc
    finally:
        try:
            connection.close()
        except Exception:
            pass
    if len(rows) > MAX_ROWS:
        raise DataSourceError(f"The report's query returned more than {MAX_ROWS:,} rows -- narrow it with a filter or a LIMIT")
    return _rows_to_data(columns, rows, root_key)


class WorkerNotConfigured(DataSourceError):
    """Uploaded drivers run in the jdbc-worker service, and this deployment hasn't set it up."""


def worker_settings() -> tuple[str, str]:
    url = os.environ.get("JDBC_WORKER_URL", "").strip().rstrip("/")
    token = os.environ.get("JDBC_WORKER_TOKEN", "").strip()
    return url, token


def _run_via_worker(conn: dict, sql: str, params: dict[str, str], root_key: str) -> dict:
    url, token = worker_settings()
    if not url or not token:
        _log.error("A JDBC driver upload was used but JDBC_WORKER_URL / JDBC_WORKER_TOKEN aren't set")
        raise WorkerNotConfigured(
            "This server isn't set up to run uploaded JDBC drivers (the jdbc-worker service). "
            "Choose the built-in driver if the engine has one, or ask whoever runs the server to enable it"
        )
    driver = conn["driver"]
    compiled, args = compile_query(sql, "qmark", params)
    payload = {
        "driver_file": driver["file"],
        "driver_sha256": driver["sha256"],
        "driver_class": driver["class_name"],
        "jdbc_url": conn["jdbc_url"],
        "username": conn["username"],
        "password": conn["password"],
        "sql": compiled,
        "args": args,
        "timeout_seconds": TIMEOUT_SECONDS,
        "max_rows": MAX_ROWS,
    }
    try:
        response = httpx.post(f"{url}/query", json=payload, headers={"X-Worker-Token": token}, timeout=TIMEOUT_SECONDS + 20)
    except httpx.HTTPError as exc:
        _log.error("JDBC worker unreachable: %s", exc)
        raise DataSourceError("Couldn't reach the JDBC driver service -- ask whoever runs the server") from exc
    if response.status_code != 200:
        # The worker's message is already safe, but it can still name hosts: log it, say less.
        _log.warning("JDBC worker answered HTTP %s: %s", response.status_code, response.text[:500])
        kind = response.json().get("kind") if response.headers.get("content-type", "").startswith("application/json") else None
        if kind == "too_many_rows":
            raise DataSourceError(f"The report's query returned more than {MAX_ROWS:,} rows -- narrow it with a filter or a LIMIT")
        if kind == "connect":
            raise DataSourceError("Couldn't connect to the report's database. Tell whoever runs the server.")
        if kind == "timeout":
            raise DataSourceError("The report's query took too long and was stopped")
        if kind == "driver":
            raise DataSourceError("The report's database driver can't be loaded -- ask whoever manages connections")
        raise DataSourceError("The report's database rejected the query")
    if len(response.content) > MAX_RESULT_BYTES:
        raise DataSourceError("The report's query result is too large")
    body = response.json()
    return _rows_to_data(body["columns"], body["rows"], root_key)


def resolved_url(conn: dict) -> str:
    return conn.get("jdbc_url") or build_jdbc_url(conn)


def run_query(conn: dict, sql: str, params: dict[str, str], root_key: str | None = None, types: dict[str, str] | None = None) -> dict:
    """Execute a report's query against a resolved connection (see
    connections.materialize: credentials already decrypted for this one call).
    `types` (filter name -> input type) turns on typed binding: a built-in driver is then handed real dates and
    numbers. An uploaded driver (the worker) always gets text -- how its JDBC driver would take a date can't be
    known here -- so a query there still converts in SQL.
    Raises DataSourceError -- safe to show whoever is running the report."""
    assert_resolves_safely(conn["host"])
    key = root_key or _DEFAULT_ROOT_KEY
    if conn.get("driver"):
        return _run_via_worker({**conn, "jdbc_url": resolved_url(conn)}, sql, params, key)
    if conn["engine"] not in _NATIVE:
        raise DataSourceError("This connection needs a JDBC driver that hasn't been uploaded")
    return _run_native(conn, sql, typed_values(params, types) if types is not None else params, key)


def check_login(conn: dict) -> None:
    """Log in and run the engine's trivial statement, or raise DataSourceError."""
    run_query(conn, ENGINES[conn["engine"]].test_query, {}, "rows")
