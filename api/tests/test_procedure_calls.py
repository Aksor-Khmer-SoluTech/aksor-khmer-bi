"""A procedure call typed straight into a query's SQL box (app/routines.py `parse_call` / `validate_call_query` /
`build_typed_call`): `EXEC dbo.p @a = :x` on SQL Server, `CALL schema.p(:x)` on any database -- with no list of allowed
procedures (the connection's login decides what may run). What is checked is the form, so a filter's value can never
become SQL: one call, a plain name, arguments only filters, numbers, 'text', NULL (DEFAULT in an EXEC); the statement
that runs is rebuilt with every filter and text value bound."""
import httpx
import pytest

from app import jdbc, routines
from app.report_data import DataConfigError
from tests.test_jdbc import _configure, _connection, _register, _secret, http
from tests.test_routines import _BRANCH, _report, _sqlserver, _text, driver_dir  # noqa: F401 -- fixture


@pytest.fixture
def worker(monkeypatch):
    """A fake jdbc-worker (protocol 2) that records every request and answers any call with two result sets."""
    sent: list[dict] = []

    def fake_post(url, json, headers, timeout):
        sent.append(json)
        results = [
            {"columns": ["full_name_en", "total_count"], "rows": [["HENG SOTHY", 22], ["CHUM SOPHEA", 22]],
             "more": [{"columns": ["bureau"], "rows": [["AUD-01"]]}]}
            for _ in json.get("queries") or []
        ]
        return httpx.Response(200, json={"results": results, "protocol": 2})

    monkeypatch.setattr(jdbc.httpx, "post", fake_post)
    return sent


# --- reading the call -----------------------------------------------------------------------------------------------


def test_exec_and_call_are_read_into_their_parts():
    assert routines.parse_call(
        "-- employees\nEXEC dbo.usp_employee_list @bureau_code = :bureau, @search = N'សុខ, ''x''', @page_size = 500;"
    ) == {"verb": "exec", "routine": "dbo.usp_employee_list", "args": [
        {"param": "@bureau_code", "kind": "filter", "value": "bureau"},
        {"param": "@search", "kind": "text", "value": "សុខ, 'x'"},
        {"param": "@page_size", "kind": "number", "value": "500"},
    ]}
    assert routines.parse_call("CALL hr.employee_list(:bureau, NULL, 'F', 50)") == {"verb": "call", "routine": "hr.employee_list", "args": [
        {"param": None, "kind": "filter", "value": "bureau"}, {"param": None, "kind": "null", "value": None},
        {"param": None, "kind": "text", "value": "F"}, {"param": None, "kind": "number", "value": "50"},
    ]}
    assert routines.parse_call("call refresh_totals()")["args"] == [] and routines.parse_call("CALL refresh_totals")["routine"] == "refresh_totals"
    assert routines.parse_call("EXEC usp_employee_list")["routine"] == "dbo.usp_employee_list"  # SQL Server's default schema
    assert routines.parse_call('CALL "hr"."employee_list"(:b)')["routine"] == "hr.employee_list"
    assert routines.is_call("/* x */ exec dbo.p") and routines.is_call("CALL p()") and not routines.is_call("SELECT 'call'")


@pytest.mark.parametrize("sql, fragment", [
    ("EXEC dbo.p :a; DROP TABLE t", "Only one statement"),
    ("EXEC dbo.usp_employee_list @search = :search\nSELECT * FROM dbo.fn_employees(:b)", "Only one statement"),
    ("CALL hr.p(:a); CALL hr.q()", "Only one statement"),
    ("CALL hr.p(:a) SELECT 1", "Only one statement"),
    ("EXEC dbo.p @a = (SELECT 1)", "can't be passed"),
    ("CALL hr.p(GETDATE())", "can't be passed"),
    ("CALL hr.p(:a", "brackets aren't closed"),
    ("CALL hr.p(@a = 1)", "in order, in brackets"),
    ("CALL hr.p(DEFAULT)", "can't be passed"),
    ("EXEC dbo.p @a = :x OUTPUT", "OUTPUT"),
    ("EXEC dbo.p @a = :x, :y", "name the rest too"),
    ("EXEC dbo.p :x,", "ends with a comma"),
    ("EXEC dbo.p @a = :x, @A = :y", "given twice"),
    ("EXEC (N'DROP TABLE t')", "name after EXEC"),
    ("EXEC dbo.[p; DROP TABLE t]", "isn't a procedure name"),
    ('CALL "x; DROP TABLE t"()', "isn't a procedure name"),
])
def test_anything_but_one_plain_call_is_refused(sql, fragment):
    with pytest.raises(DataConfigError) as exc:
        routines.parse_call(sql)
    assert fragment in str(exc.value)


# --- in a report: no list of allowed procedures ---------------------------------------------------------------------


def test_any_procedure_runs_with_exec_no_approval_needed(auth_headers, worker):
    _sqlserver(auth_headers)  # nothing approved on it
    report_id = _report(auth_headers, "{{ rows | length }} · {{ rows[0].full_name_en }} · {{ bureaus[0].bureau }}")
    sql = "EXEC dbo.usp_employee_list @bureau_code = :branch, @search = N'O''Neil', @page_size = 500"
    saved = _configure(auth_headers, report_id, [_BRANCH], {
        "type": "jdbc", "connection": "erp-mssql",
        "queries": [{"name": "rows", "shape": "list", "query": sql, "more_results": [{"name": "bureaus", "shape": "list"}]}],
    })
    assert saved["data_source"]["queries"][0]["query"] == sql
    nasty = "AUD-01'); DROP TABLE dbo.dbm_employee; --"
    run = http.post(f"/api/v1/reports/{report_id}/run", json={"parameters": {"branch": nasty}, "format": "docx"}, headers=auth_headers)
    assert run.status_code == 200, run.text
    assert _text(run.content) == "2 · HENG SOTHY · AUD-01"
    # Rebuilt, not passed through: the name bracket-quoted, the filter and the text bound, the number as written.
    [request] = worker
    assert request["queries"] == [{
        "sql": "EXEC [dbo].[usp_employee_list] @bureau_code = ?, @search = ?, @page_size = 500",
        "args": [nasty, "O'Neil"], "call": True, "result_sets": 2,
    }]


def test_call_through_an_uploaded_driver_uses_jdbcs_call_escape(auth_headers, worker):
    _sqlserver(auth_headers)
    report_id = _report(auth_headers, "{{ rows | length }}")
    _configure(auth_headers, report_id, [_BRANCH], {"type": "jdbc", "connection": "erp-mssql", "query": "CALL hr.employee_list(:branch, NULL, 50)"})
    run = http.post(f"/api/v1/reports/{report_id}/run", json={"parameters": {"branch": "AUD-01"}, "format": "docx"}, headers=auth_headers)
    assert run.status_code == 200, run.text
    [request] = worker
    assert request["queries"] == [{"sql": "{call hr.employee_list(?, NULL, 50)}", "args": ["AUD-01"], "call": True, "result_sets": 1}]


def test_call_on_a_built_in_driver(auth_headers, monkeypatch):
    seen = {}

    def fake_native(conn, sql, params, root_key):
        seen.update(sql=sql, params=params)
        return {root_key: [{"full_name_en": "HENG SOTHY"}]}

    monkeypatch.setattr(jdbc, "_run_native", fake_native)
    monkeypatch.setattr(jdbc, "assert_resolves_safely", lambda host: None)
    _secret(auth_headers)
    _connection(auth_headers, name="hr-pg")  # PostgreSQL, built in
    report_id = _report(auth_headers, "{{ rows[0].full_name_en }}")
    _configure(auth_headers, report_id, [_BRANCH], {"type": "jdbc", "connection": "hr-pg", "query": "CALL hr.employee_list(:branch, 'x')"})
    run = http.post(f"/api/v1/reports/{report_id}/run", json={"parameters": {"branch": "AUD-01"}, "format": "docx"}, headers=auth_headers)
    assert run.status_code == 200, run.text
    assert seen["sql"] == "CALL hr.employee_list(:branch, :__call_rows_1)"
    assert seen["params"]["branch"] == "AUD-01" and seen["params"]["__call_rows_1"] == "x"


@pytest.mark.parametrize("data_source, fragment", [
    ({"query": "EXEC dbo.p @a = :missing"}, ":missing but no filter"),
    ({"query": "SELECT 1; EXEC dbo.p"}, "one statement"),
])
def test_a_call_is_checked_when_saved(auth_headers, worker, data_source, fragment):
    _sqlserver(auth_headers)
    report_id = _register(auth_headers)
    resp = _configure(auth_headers, report_id, [], {"type": "jdbc", "connection": "erp-mssql", **data_source}, expect=400)
    assert fragment.lower() in resp["detail"].lower(), resp


def test_exec_is_refused_where_it_isnt_sql(auth_headers):
    _secret(auth_headers)
    _connection(auth_headers, name="hr-pg")
    report_id = _register(auth_headers)
    resp = _configure(auth_headers, report_id, [], {"type": "jdbc", "connection": "hr-pg", "query": "EXEC dbo.p"}, expect=400)
    assert "write CALL dbo.p(...)" in resp["detail"]
