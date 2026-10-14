"""One request in one JVM (see app.py for why): its statements, in order, over
one connection. Reads a job as JSON on stdin and prints exactly one JSON line on
stdout: {"results": [{"columns", "rows"}, ...]} or {"error", "detail", "index"}
(`index`: which statement failed, when it was one of them).
Run as a child process of the service, never imported."""
import base64
import datetime
import decimal
import json
import sys


def _plain(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() and value.as_tuple().exponent >= 0 else float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(bytes(value)).decode("ascii")
    return str(value)


class _TooMany(Exception):
    pass


class _NoResult(Exception):
    pass


def _read(cursor, max_rows: int) -> dict:
    columns = [d[0] for d in (cursor.description or [])]
    if not columns:
        raise _NoResult("the statement returned no columns")
    rows = cursor.fetchmany(max_rows + 1)
    if len(rows) > max_rows:
        raise _TooMany()
    return {"columns": columns, "rows": [[_plain(v) for v in row] for row in rows]}


def _select(cursor, statement: dict, max_rows: int) -> list[dict]:
    cursor.execute(statement["sql"], statement["args"])
    return [_read(cursor, max_rows)]


def _call(connection, cursor, statement: dict, max_rows: int) -> list[dict]:
    """A stored procedure, through JDBC's CALL: its result sets in order, up to the number asked for. The row counts
    SQL Server sends before them (no SET NOCOUNT ON) are skipped. Values are read by the cursor's own converters, so
    a date or a decimal comes back exactly as it does from a SELECT."""
    cursor._close_last()
    prepared = connection.jconn.prepareCall(statement["sql"])
    cursor._prep = prepared
    cursor._set_stmt_parms(prepared, statement["args"])
    is_result = prepared.execute()
    wanted = max(1, int(statement.get("result_sets") or 1))
    sets: list[dict] = []
    while True:
        if is_result:
            cursor._rs = prepared.getResultSet()
            cursor._meta = cursor._rs.getMetaData()
            cursor._description = None
            sets.append(_read(cursor, max_rows))
            if len(sets) >= wanted:
                break
        elif prepared.getUpdateCount() == -1:
            break  # no more results of any kind
        is_result = prepared.getMoreResults()
    if not sets:
        raise _NoResult("the procedure returned no result set")
    return sets


def main() -> None:
    job = json.load(sys.stdin)
    try:
        import jaydebeapi

        connection = jaydebeapi.connect(job["class"], job["url"], [job["user"], job["password"]], job["jar"])
    except Exception as exc:
        print(json.dumps({"error": "connect", "detail": f"{type(exc).__name__}: {exc}"}))
        return
    try:
        try:
            connection.jconn.setReadOnly(True)
        except Exception:
            pass  # not every driver supports it; the database account being read-only is the real guard
        results = []
        for index, statement in enumerate(job["queries"]):
            try:
                cursor = connection.cursor()
                sets = _call(connection, cursor, statement, job["max_rows"]) if statement.get("call") else _select(cursor, statement, job["max_rows"])
                cursor.close()
            except _TooMany:
                print(json.dumps({"error": "too_many_rows", "detail": f"more than {job['max_rows']} rows", "index": index}))
                return
            except _NoResult as exc:
                print(json.dumps({"error": "query", "detail": str(exc), "index": index}))
                return
            except Exception as exc:
                print(json.dumps({"error": "query", "detail": f"{type(exc).__name__}: {exc}", "index": index}))
                return
            first, *more = sets
            results.append({**first, **({"more": more} if more else {})})
        print(json.dumps({"results": results, "protocol": 2}))
    except Exception as exc:
        print(json.dumps({"error": "query", "detail": f"{type(exc).__name__}: {exc}"}))
    finally:
        try:
            connection.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
