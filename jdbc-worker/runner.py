"""One query in one JVM (see app.py for why). Reads a job as JSON on stdin and
prints exactly one JSON line on stdout: {"columns", "rows"} or {"error", "detail"}.
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
        cursor = connection.cursor()
        cursor.execute(job["sql"], job["args"])
        columns = [d[0] for d in (cursor.description or [])]
        if not columns:
            print(json.dumps({"error": "query", "detail": "the statement returned no columns"}))
            return
        rows = cursor.fetchmany(job["max_rows"] + 1)
        if len(rows) > job["max_rows"]:
            print(json.dumps({"error": "too_many_rows", "detail": f"more than {job['max_rows']} rows"}))
            return
        print(json.dumps({"columns": columns, "rows": [[_plain(v) for v in row] for row in rows]}))
    except Exception as exc:
        print(json.dumps({"error": "query", "detail": f"{type(exc).__name__}: {exc}"}))
    finally:
        try:
            connection.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
