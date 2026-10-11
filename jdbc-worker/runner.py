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
                cursor.execute(statement["sql"], statement["args"])
                columns = [d[0] for d in (cursor.description or [])]
                if not columns:
                    print(json.dumps({"error": "query", "detail": "the statement returned no columns", "index": index}))
                    return
                rows = cursor.fetchmany(job["max_rows"] + 1)
                cursor.close()
            except Exception as exc:
                print(json.dumps({"error": "query", "detail": f"{type(exc).__name__}: {exc}", "index": index}))
                return
            if len(rows) > job["max_rows"]:
                print(json.dumps({"error": "too_many_rows", "detail": f"more than {job['max_rows']} rows", "index": index}))
                return
            results.append({"columns": columns, "rows": [[_plain(v) for v in row] for row in rows]})
        print(json.dumps({"results": results}))
    except Exception as exc:
        print(json.dumps({"error": "query", "detail": f"{type(exc).__name__}: {exc}"}))
    finally:
        try:
            connection.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
