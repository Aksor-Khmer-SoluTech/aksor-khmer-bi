"""Stored procedures and functions as a report's data -- SQL Server, through the JDBC worker.

A report query is a SELECT by rule (jdbc.validate_query): EXEC and friends are refused, because what a procedure does
can't be seen from its name, and it may write. This is the controlled way past that rule:

* a connection manager **approves** routines on a SQL Server connection (`config.routines`): a procedure, a
  table-valued function or a scalar function, by schema-qualified name, with its parameters -- typed in, or picked
  from **Discover** (`discover()`: what the connection's login may execute, read from the catalog);
* a report author **writes the call** in the query's SQL box, as in any report tool -- `EXEC dbo.GetSales
  @branch = :branch` or `CALL hr.get_sales(:branch)` (`validate_call_query()`), on any database and with no list of
  allowed ones: the connection's login decides what may run. (Cards saved by the earlier picker -- a routine plus an
  argument map, `validate_query_routine()` -- keep working against their approved list; the portal opens them as
  the same EXEC text.) Functions need none of this: `SELECT * FROM dbo.fn(:x)` is an ordinary query;
* the call is **built here** (`build_call()`): the name only ever comes from the approved list and is bracket-quoted,
  every value is a bound parameter. A procedure may return several result sets, each mapped to its own name.

Approval is checked when a report is saved and again on every run (connections.materialize), so a routine taken
off the list stops running at once. The connection's database login is still the real limit on what a procedure can
do: the docs (and Discover's `can_write`) say to give it EXECUTE on these routines and nothing that writes.
"""
from __future__ import annotations

import re
from typing import Any

from .report_data import DataConfigError, DataSourceError

KINDS = ("procedure", "table_function", "scalar_function")
KIND_LABEL = {"procedure": "stored procedure", "table_function": "table-valued function", "scalar_function": "scalar function"}
ENGINES = ("sqlserver",)
MAX_ROUTINES = 200
MAX_PARAMETERS = 50
MAX_RESULT_SETS = 10

# schema.name, each part a regular SQL Server identifier -- no brackets, quotes or spaces to escape, so what's
# approved is exactly what's called.
_PART = r"[A-Za-z_#@][A-Za-z0-9_#@$]{0,127}"
NAME_RE = re.compile(rf"^{_PART}\.{_PART}$")
PARAM_RE = re.compile(r"^@[A-Za-z_][A-Za-z0-9_#@$]{0,127}$")
TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_ ,()]{0,59}$")


def _quote(name: str) -> str:
    return ".".join(f"[{part}]" for part in name.split("."))


# --- the approved list, on a connection --------------------------------------------------------------------------


def validate_routines(raw: Any, engine: str) -> list[dict]:
    """A connection's approved routines, cleaned: [{name, kind, parameters: [{name, type}]}]."""
    if raw in (None, []):
        return []
    if engine not in ENGINES:
        raise DataConfigError("Stored procedures and functions can be approved on a SQL Server connection")
    if not isinstance(raw, list):
        raise DataConfigError("The approved routines must be a list")
    if len(raw) > MAX_ROUTINES:
        raise DataConfigError(f"A connection can approve at most {MAX_ROUTINES} procedures and functions")
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise DataConfigError("An approved routine isn't valid")
        name = (item.get("name") or "").strip()
        if not NAME_RE.match(name):
            raise DataConfigError(f"{name!r} isn't a valid routine name -- write it as schema.name, e.g. dbo.GetSales")
        if name.lower() in seen:
            raise DataConfigError(f"{name} is approved twice")
        seen.add(name.lower())
        kind = item.get("kind")
        if kind not in KINDS:
            raise DataConfigError(f"{name}: choose whether it's a stored procedure, a table-valued or a scalar function")
        parameters = []
        for p in item.get("parameters") or []:
            pname = ((p or {}).get("name") or "").strip()
            ptype = ((p or {}).get("type") or "").strip()
            if not PARAM_RE.match(pname):
                raise DataConfigError(f"{name}: {pname!r} isn't a valid parameter name -- SQL Server's start with @, e.g. @branch")
            if ptype and not TYPE_RE.match(ptype):
                raise DataConfigError(f"{name}: {ptype!r} isn't a valid type for {pname}")
            if any(q["name"].lower() == pname.lower() for q in parameters):
                raise DataConfigError(f"{name}: {pname} is listed twice")
            parameters.append({"name": pname, "type": ptype or None})
        if len(parameters) > MAX_PARAMETERS:
            raise DataConfigError(f"{name}: at most {MAX_PARAMETERS} parameters")
        cleaned.append({"name": name, "kind": kind, "parameters": parameters})
    return cleaned


def find(routines: list[dict] | None, name: str) -> dict | None:
    return next((r for r in routines or [] if r["name"].lower() == (name or "").lower()), None)


# --- a query card that calls one ----------------------------------------------------------------------------------


def validate_query_routine(
    item: dict, routines: list[dict] | None, engine: str | None, parameter_names: set[str], query_name: str
) -> dict:
    """A query card's routine part, cleaned: {routine, arguments, more_results}. `routines`/`engine` are its
    connection's (None: the connection isn't known here -- checked again at run time anyway)."""
    from . import jdbc

    name = (item.get("routine") or "").strip()
    if not NAME_RE.match(name):
        raise DataConfigError(f"Query {query_name!r}: choose the procedure or function it calls")
    if engine is not None and engine not in ENGINES:
        raise DataConfigError(f"Query {query_name!r}: procedures and functions run on a SQL Server connection")
    routine = find(routines, name) if routines is not None else None
    if routines is not None and routine is None:
        raise DataConfigError(
            f"Query {query_name!r}: {name} isn't approved on its connection -- a connection manager approves it under "
            "Manage → Connections"
        )
    raw_args = item.get("arguments") or {}
    if not isinstance(raw_args, dict):
        raise DataConfigError(f"Query {query_name!r}: its arguments must map each parameter to a filter or a value")
    arguments: dict[str, dict] = {}
    for pname, arg in raw_args.items():
        if not PARAM_RE.match(pname or ""):
            raise DataConfigError(f"Query {query_name!r}: {pname!r} isn't a parameter name")
        has_filter = isinstance(arg, dict) and arg.get("filter") is not None
        has_value = isinstance(arg, dict) and arg.get("value") is not None
        if has_filter == has_value:
            raise DataConfigError(f"Query {query_name!r}: give {pname} a filter or a fixed value")
        if has_filter:
            if arg["filter"] not in parameter_names:
                raise DataConfigError(f"Query {query_name!r}: {pname} takes the filter {arg['filter']!r}, which isn't defined")
            arguments[pname] = {"filter": arg["filter"]}
        else:
            value = arg["value"]
            if not isinstance(value, str) or len(value) > 4000 or "\0" in value:
                raise DataConfigError(f"Query {query_name!r}: {pname}'s fixed value isn't valid")
            arguments[pname] = {"value": value}
    if routine is not None:
        declared = {p["name"].lower() for p in routine["parameters"]}
        unknown = [p for p in arguments if p.lower() not in declared]
        if unknown:
            raise DataConfigError(f"Query {query_name!r}: {name} has no parameter {unknown[0]}")
        missing = [p["name"] for p in routine["parameters"] if p["name"].lower() not in {a.lower() for a in arguments}]
        if missing:
            raise DataConfigError(f"Query {query_name!r}: give {', '.join(missing)} a filter or a fixed value")
    more = item.get("more_results") or []
    if more and (routine or {}).get("kind", "procedure") != "procedure":
        raise DataConfigError(f"Query {query_name!r}: only a stored procedure returns more than one result")
    if not isinstance(more, list) or len(more) > MAX_RESULT_SETS - 1:
        raise DataConfigError(f"Query {query_name!r}: at most {MAX_RESULT_SETS} results from one procedure")
    more_results = []
    for index, extra in enumerate(more, start=2):
        rname = ((extra or {}).get("name") or "").strip()
        shape = (extra or {}).get("shape") or "list"
        if not jdbc.ROOT_KEY_RE.match(rname):
            raise DataConfigError(f"Query {query_name!r}: result {index}'s name must be letters, digits and underscores")
        if shape not in ("list", "object", "value"):
            raise DataConfigError(f"Query {query_name!r}: result {index} is a list, an object or a single value")
        more_results.append({"name": rname, "shape": shape})
    out: dict[str, Any] = {"routine": routine["name"] if routine else name, "arguments": arguments}
    if more_results:
        out["more_results"] = more_results
    return out


def build_call(query: dict, routines: list[dict] | None, params: dict[str, str]) -> tuple[str, dict[str, str], bool, int]:
    """The statement for a routine query: (sql with :name placeholders, the values to bind -- the filters' plus the
    fixed ones, under private names -- whether it's a CALL, how many result sets to read). Refuses a routine that is
    no longer approved: approval is checked on every run, not only when the report was saved."""
    routine = find(routines, query["routine"])
    if routine is None:
        raise DataSourceError(
            f"The query {query['name']!r} calls {query['routine']}, which its connection no longer allows -- ask whoever manages connections"
        )
    values = dict(params)
    placeholders = []
    args = {k.lower(): v for k, v in (query.get("arguments") or {}).items()}
    for index, parameter in enumerate(routine["parameters"]):
        arg = args.get(parameter["name"].lower())
        if arg is None:
            raise DataSourceError(f"The query {query['name']!r}: {parameter['name']} has no value -- ask whoever manages this report")
        if "filter" in arg:
            placeholders.append(f":{arg['filter']}")
        else:
            key = f"__routine_{query['name']}_{index}"
            values[key] = arg["value"]
            placeholders.append(f":{key}")
    target = _quote(routine["name"])
    joined = ", ".join(placeholders)
    if routine["kind"] == "procedure":
        return f"{{call {target}({joined})}}", values, True, 1 + len(query.get("more_results") or [])
    if routine["kind"] == "table_function":
        return f"SELECT * FROM {target}({joined})", values, False, 1
    return f"SELECT {target}({joined}) AS [value]", values, False, 1


# --- a procedure call typed into the SQL box ---------------------------------------------------------------------
#
# The way people expect from Jasper or BI Publisher: the call is written in the same SQL box as any query, on any
# database the connection reaches --
#     EXEC dbo.usp_employee_list @bureau_code = :bureau, @page_size = 500        (SQL Server)
#     CALL hr.employee_list(:bureau, 500)                                         (Oracle, MySQL, MariaDB, Db2, PostgreSQL)
# No list of allowed procedures: like any query, it runs as the connection's database login, and what that login may
# execute is the limit -- give reports a login that can only read and EXECUTE what they need. What is checked here is
# the *form*, so a filter's value can never become SQL: one call and nothing else, a plain schema.name, and as
# arguments only filters (:name), numbers, 'text', NULL (and DEFAULT, in an EXEC). The statement that runs is rebuilt
# from these parts -- name re-quoted, every filter and text bound -- never the text as typed.

_CALL_HEAD = re.compile(r"^\s*(exec(?:ute)?|call)\b", re.I)
_CALL_TOKEN = re.compile(
    r"""\s*(?:
        (?P<str>N?'(?:[^']|'')*')
      | (?P<filter>:[A-Za-z_][A-Za-z0-9_]*)
      | (?P<param>@[A-Za-z_][A-Za-z0-9_#@$]*)
      | (?P<num>-?\d+(?:\.\d+)?)
      | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
      | (?P<punct>[=,;()])
    )""",
    re.X,
)
_NAME_PART = r"(\[[^\]]+\]|\"[^\"]+\"|`[^`]+`|[A-Za-z_#@][A-Za-z0-9_#@$]*)"
_CALL_NAME = re.compile(rf"^\s*{_NAME_PART}(?:\s*\.\s*{_NAME_PART})?(?:\s*\.\s*{_NAME_PART})?")
_PLAIN_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#@]{0,127}$")


def _code(sql: str) -> str:
    from . import jdbc

    return "".join(text if is_code else " " for text, is_code in jdbc._scan(sql))


def is_call(sql: Any) -> bool:
    """The text is a procedure call -- EXEC / EXECUTE / CALL ... -- not a SELECT; comments before it don't count."""
    if not isinstance(sql, str):
        return False
    try:
        return bool(_CALL_HEAD.match(_code(sql)))
    except DataConfigError:
        return bool(_CALL_HEAD.match(sql))



def parse_call(sql: str) -> dict:
    """`EXEC name arg, @p = arg` or `CALL name(arg, ...)` as {verb, routine, args: [{param|None, kind, value}]}; kind
    is filter, text, number, null or default. DataConfigError says what's wrong, in the words of someone writing SQL."""
    from . import jdbc

    if len(sql) > jdbc.MAX_QUERY_LENGTH:
        raise DataConfigError(f"The query is too long (max {jdbc.MAX_QUERY_LENGTH} characters)")
    if "\0" in sql:
        raise DataConfigError("The query contains an invalid character")
    # Comments become spaces; string literals stay exactly as written (they're arguments).
    text = "".join(piece if is_code or piece[:1] == "'" else (piece if piece[:1] in '"`' else " ") for piece, is_code in jdbc._scan(sql))
    head = _CALL_HEAD.match(text)
    if head is None:
        raise DataConfigError("A procedure call starts with EXEC or CALL")
    verb = "call" if head.group(1).lower() == "call" else "exec"
    rest = text[head.end():]
    found = _CALL_NAME.match(rest)
    if found is None:
        raise DataConfigError(f"Write the procedure's name after {verb.upper()}, e.g. {verb.upper()} dbo.usp_employee_list")
    parts = [p[1:-1] if p[:1] in '["`' else p for p in found.groups() if p]
    for part in parts:
        if not _PLAIN_PART.match(part):
            raise DataConfigError(f"{'.'.join(parts)!r} isn't a procedure name this can call -- letters, digits and _ only, e.g. hr.employee_list")
    if verb == "exec" and len(parts) == 1:
        parts = ["dbo", parts[0]]
    name = ".".join(parts)
    rest = rest[found.end():]

    pos = 0
    if verb == "call":
        opener = _CALL_TOKEN.match(rest, pos)
        if opener is not None and opener.group("punct") == "(":
            pos = opener.end()
            closing = True
        else:
            closing = False  # CALL name -- no arguments
    else:
        closing = False

    args: list[dict] = []
    expecting = True
    closed = not closing
    n = len(rest)
    while pos < n:
        if not rest[pos:].strip():
            break
        m = _CALL_TOKEN.match(rest, pos)
        if m is None:
            snippet = rest[pos:].strip()[:30]
            raise DataConfigError(f"Can't read the arguments near {snippet!r} -- pass filters (:name), numbers, 'text' or NULL")
        pos = m.end()
        punct = m.group("punct")
        if punct == ")" and closing and not closed:
            if expecting and args:
                raise DataConfigError("The call ends with a comma")
            closed, expecting = True, False
            continue
        if punct == ";":
            if rest[pos:].strip():
                raise DataConfigError("Only one statement is allowed -- each query card runs one; add another query for the next")
            break
        if closed and closing:
            raise DataConfigError("Only one statement is allowed -- each query card runs one; add another query for the next")
        if punct == ",":
            if expecting:
                raise DataConfigError("An argument is missing between two commas")
            expecting = True
            continue
        if punct in ("(", ")", "="):
            raise DataConfigError(f"Can't read {punct!r} there -- pass filters (:name), numbers, 'text' or NULL")
        if not expecting:
            raise DataConfigError(
                "Only one statement is allowed -- each query card runs one; add another query for the next"
                if m.group("word") and m.group("word").lower() in ("select", "with", "exec", "execute", "call")
                else "Separate the arguments with commas"
            )
        param = None
        if m.group("param"):
            if verb == "call":
                raise DataConfigError("CALL takes its arguments in order, in brackets: CALL hr.employee_list(:bureau, 500)")
            param = m.group("param")
            eq = _CALL_TOKEN.match(rest, pos)
            if eq is None or eq.group("punct") != "=":
                raise DataConfigError(f"Give {param} a value: {param} = :filter, a number, 'text', NULL or DEFAULT")
            pos = eq.end()
            m = _CALL_TOKEN.match(rest, pos)
            if m is None:
                near = rest[pos:].strip()[:30]
                raise DataConfigError(
                    f"{param} = {near!r} can't be passed -- use a filter (:name), a number, 'text', NULL or DEFAULT" if near else f"{param} has no value"
                )
            pos = m.end()
        word = (m.group("word") or "").lower()
        if m.group("str") is not None:
            raw = m.group("str")
            arg = {"kind": "text", "value": raw[raw.index("'") + 1 : -1].replace("''", "'")}
        elif m.group("filter"):
            arg = {"kind": "filter", "value": m.group("filter")[1:]}
        elif m.group("num"):
            arg = {"kind": "number", "value": m.group("num")}
        elif word == "null" or (word == "default" and verb == "exec"):
            arg = {"kind": word, "value": None}
        elif word in ("output", "out"):
            raise DataConfigError("OUTPUT parameters aren't supported -- return the values as a result set instead")
        else:
            got = m.group(0).strip()
            raise DataConfigError(f"{got!r} can't be passed -- use a filter (:name), a number, 'text' or NULL")
        if param is None and any(a["param"] for a in args):
            raise DataConfigError("After a named argument (@name = ...), name the rest too")
        args.append({"param": param, **arg})
        expecting = False
        follow = _CALL_TOKEN.match(rest, pos)
        if follow is not None and (follow.group("word") or "").lower() in ("output", "out"):
            raise DataConfigError("OUTPUT parameters aren't supported -- return the values as a result set instead")
    if not closed:
        raise DataConfigError("The call's brackets aren't closed")
    if expecting and args:
        raise DataConfigError("The call ends with a comma")
    if len(args) > MAX_PARAMETERS:
        raise DataConfigError(f"At most {MAX_PARAMETERS} arguments")
    named = [a["param"].lower() for a in args if a["param"]]
    if len(named) != len(set(named)):
        raise DataConfigError("The same parameter is given twice")
    return {"verb": verb, "routine": name, "args": args}



def validate_call_query(item: dict, engine: str | None, parameter_names: set[str], query_name: str) -> dict:
    """A query card whose SQL is a procedure call, cleaned: {query, call: {verb, routine, args}, more_results?}.
    `engine` is its connection's (None: not known here)."""
    where = f"Query {query_name!r}"
    try:
        parsed = parse_call(item.get("query") or "")
    except DataConfigError as exc:
        raise DataConfigError(f"{where}: {exc}") from exc
    if parsed["verb"] == "exec" and engine is not None and engine != "sqlserver":
        raise DataConfigError(f"{where}: EXEC is SQL Server's -- on this database write CALL {parsed['routine']}(...)")
    unknown = sorted({a["value"] for a in parsed["args"] if a["kind"] == "filter"} - parameter_names)
    if unknown:
        raise DataConfigError(f"{where} uses {', '.join(':' + f for f in unknown)} but no filter with that name is defined")
    for a in parsed["args"]:
        if a["kind"] == "text" and (len(a["value"]) > 4000 or "\0" in a["value"]):
            raise DataConfigError(f"{where}: a text argument is too long")
    out: dict[str, Any] = {"query": item["query"].strip(), "call": parsed}
    more = validate_query_routine(
        {"routine": parsed["routine"], "arguments": {}, "more_results": item.get("more_results") or []},
        None, None, parameter_names, query_name,
    ).get("more_results")
    if more:
        out["more_results"] = more
    return out


def _bind_args(query: dict, params: dict[str, str]) -> tuple[list[dict], dict[str, str]]:
    """The call's arguments as SQL fragments: filters and text bound (:placeholders), the rest exactly as checked."""
    values = dict(params)
    out = []
    for index, arg in enumerate(query["call"]["args"]):
        kind, value = arg.get("kind"), arg.get("value")
        if kind == "filter" and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(value)):
            expr = f":{value}"
        elif kind == "text" and isinstance(value, str):
            key = f"__call_{query['name']}_{index}"
            values[key] = value
            expr = f":{key}"
        elif kind == "number" and re.match(r"^-?\d+(?:\.\d+)?$", str(value)):
            expr = str(value)
        elif kind in ("null", "default"):
            expr = kind.upper()
        else:
            raise DataSourceError(f"The query {query['name']!r} has an argument that isn't valid -- open it and save it again")
        param = arg.get("param")
        if param and not PARAM_RE.match(param):
            raise DataSourceError(f"The query {query['name']!r} names a parameter that isn't valid")
        out.append({"param": param, "expr": expr})
    return out, values


def build_typed_call(query: dict, params: dict[str, str], engine: str, via_worker: bool) -> tuple[str, dict[str, str], bool, int]:
    """The statement for a typed procedure call: (sql with :name placeholders, values to bind, whether to run it as a
    call -- JDBC prepareCall, through the worker -- and how many result sets to read)."""
    call = query["call"]
    parts = call["routine"].split(".")
    if not all(_PLAIN_PART.match(p) for p in parts):
        raise DataSourceError(f"The query {query['name']!r} calls a name that isn't valid -- open it and save it again")
    args, values = _bind_args(query, params)
    sets = 1 + len(query.get("more_results") or [])
    if call["verb"] == "exec":
        target = ".".join(f"[{p}]" for p in parts)
        listed = ", ".join(f"{a['param']} = {a['expr']}" if a["param"] else a["expr"] for a in args)
        return f"EXEC {target}" + (f" {listed}" if listed else ""), values, True, sets
    listed = ", ".join(a["expr"] for a in args)
    if via_worker:
        # JDBC's own call escape: every driver turns it into its database's syntax.
        return f"{{call {call['routine']}({listed})}}", values, True, sets
    if sets > 1:
        raise DataSourceError(f"The query {query['name']!r} names more result sets, which this database's built-in driver can't read -- remove them")
    return f"CALL {call['routine']}({listed})", values, False, 1


# --- Discover: what the login may run ----------------------------------------------------------------------------

# Every routine the connection's login may run, with its parameters -- one row per parameter (or one with no
# parameter), read from the catalog. Fixed text: nothing of anyone's is pasted in.
DISCOVER_SQL = """
SELECT s.name AS schema_name, o.name AS object_name, RTRIM(o.type) AS object_type,
       p.parameter_id, p.name AS parameter_name, TYPE_NAME(p.user_type_id) AS type_name,
       p.max_length, p.is_output
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
LEFT JOIN sys.parameters p ON p.object_id = o.object_id AND p.parameter_id > 0
WHERE o.type IN ('P', 'IF', 'TF', 'FN') AND o.is_ms_shipped = 0
  AND HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT',
                        CASE WHEN o.type IN ('P', 'FN') THEN 'EXECUTE' ELSE 'SELECT' END) = 1
ORDER BY s.name, o.name, p.parameter_id
"""

# Whether the login could change data -- the one thing an approved procedure must not be able to do.
CAN_WRITE_SQL = """
SELECT CASE WHEN IS_ROLEMEMBER('db_owner') = 1 OR IS_ROLEMEMBER('db_datawriter') = 1 OR IS_ROLEMEMBER('db_ddladmin') = 1
            OR EXISTS (SELECT 1 FROM fn_my_permissions(NULL, 'DATABASE')
                       WHERE permission_name IN ('INSERT', 'UPDATE', 'DELETE', 'ALTER', 'CONTROL'))
       THEN 1 ELSE 0 END AS can_write
"""

_KIND_BY_TYPE = {"P": "procedure", "IF": "table_function", "TF": "table_function", "FN": "scalar_function"}


def _type_text(type_name: str | None, max_length: Any) -> str | None:
    if not type_name:
        return None
    if type_name in ("nvarchar", "nchar") and isinstance(max_length, int):
        return f"{type_name}({'max' if max_length == -1 else max_length // 2})"
    if type_name in ("varchar", "char", "varbinary") and isinstance(max_length, int):
        return f"{type_name}({'max' if max_length == -1 else max_length})"
    return type_name


def discover(conn: dict) -> dict:
    """{routines: [{name, kind, parameters}], can_write} for a resolved SQL Server connection, via the worker."""
    from . import jdbc

    if conn.get("engine") not in ENGINES:
        raise DataConfigError("Discover reads SQL Server's catalog -- this isn't a SQL Server connection")
    rows = jdbc.run_batch_via_worker(conn, [("routines", DISCOVER_SQL), ("can_write", CAN_WRITE_SQL)], {})
    found: dict[str, dict] = {}
    skipped_output = set()
    for row in rows["routines"]:
        name = f"{row['schema_name']}.{row['object_name']}"
        if not NAME_RE.match(name):
            continue  # a name that would need quoting: not something this can call safely
        entry = found.setdefault(name, {"name": name, "kind": _KIND_BY_TYPE.get(row["object_type"], "procedure"), "parameters": []})
        if row.get("parameter_name"):
            if row.get("is_output") in (1, True, "1", "true", "True"):
                skipped_output.add(name)
                continue
            entry["parameters"].append({"name": row["parameter_name"], "type": _type_text(row.get("type_name"), row.get("max_length"))})
    for name in skipped_output:
        found.pop(name, None)  # OUTPUT parameters aren't supported: don't offer what can't be called
    can_write = bool((rows["can_write"] or [{}])[0].get("can_write"))
    return {"routines": list(found.values()), "can_write": can_write, "skipped_output": sorted(skipped_output)}
