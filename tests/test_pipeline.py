"""End-to-end pipeline tests for the on-prem PROD path.

These tests stitch together the full chain that runs whenever the user types
"run script X on AHF-PROD..." in Copilot:

    author_sql_script -> validate_script_file -> _run_sqlplus_csv
                      -> format_results_for_output

By patching `subprocess.run`, we feed in canned sqlplus stdout shaped exactly
like real PROD output (CSV between sentinels, with the kinds of column types
investigative queries actually return). This proves the parser fix, the
splitter fix, the CLOB / TZ formatting, the per-call sentinel scheme, and the
audit logging all behave correctly together — without needing a live database.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from oraflow.db import _run_sqlplus_csv
from oraflow.workspace import (
    author_sql_script,
    format_results_for_output,
    results_to_json_payload,
    script_output_paths,
    validate_script_file,
)


@pytest.fixture
def sqlplus_mock(monkeypatch):
    """Patch `subprocess.run` to synthesise sqlplus stdout dynamically.

    `_run_sqlplus_csv` generates per-call sentinels via ``uuid.uuid4()``. The
    fixture extracts the begin/end pair from the script written to subprocess
    stdin and splices ``state['csv_body']`` between them. Tests set
    ``state['csv_body']`` (and optionally ``state['returncode']`` /
    ``state['raw_stdout_override']``) before invoking ``_run_sqlplus_csv``.
    """

    state: dict[str, object] = {
        "csv_body": "",
        "returncode": 0,
        "raw_stdout_override": None,
    }

    def _extract_sentinels(script: str) -> tuple[str, str]:
        begin = end = ""
        for line in script.splitlines():
            stripped = line.strip()
            if stripped.startswith("prompt __ORAFLOW_CSV_BEGIN_"):
                begin = stripped[len("prompt ") :]
            elif stripped.startswith("prompt __ORAFLOW_CSV_END_"):
                end = stripped[len("prompt ") :]
        return begin, end

    def fake_run(cmd, *args, input=None, **kwargs):
        if state["raw_stdout_override"] is not None:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=int(state["returncode"]),
                stdout=str(state["raw_stdout_override"]),
                stderr="",
            )
        begin, end = _extract_sentinels(input or "")
        stdout = (
            "Connected.\n"
            "Session altered.\n"
            "Session altered.\n"
            f"{begin}\n"
            f"{state['csv_body']}"
            f"{end}\n"
            "Disconnected from Oracle Database 19c.\n"
        )
        return subprocess.CompletedProcess(
            args=cmd, returncode=int(state["returncode"]), stdout=stdout, stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    return state


# ---------------------------------------------------------------------------
# Phase 1 — single-query realistic shapes through `_run_sqlplus_csv`.
# ---------------------------------------------------------------------------


def test_number_first_column_returns_rows(sqlplus_mock):
    sqlplus_mock["csv_body"] = (
        '"SYSTEM_AUDIT_NUM","AUDIT_NAME","RX_RECORD_NUM"\n'
        '11421195405,"PatientAdmin.ERPAudit",10009623246\n'
        '11421230211,"PatientAdmin.ERPAudit",10009623246\n'
        '11681954129,"Workflow.ERPAudit",10010481115\n'
    )
    result = _run_sqlplus_csv(
        "alias",
        "user",
        "secret",
        "select system_audit_num, audit_name, rx_record_num from trexone_data.system_audit",
        max_rows=100,
        timeout_s=5,
    )
    assert result.row_count == 3
    assert result.columns == ["SYSTEM_AUDIT_NUM", "AUDIT_NAME", "RX_RECORD_NUM"]
    assert result.rows[0][0] == "11421195405"
    assert result.rows[2][1] == "Workflow.ERPAudit"
    assert result.truncated is False


def test_clob_size_value_passes_through(sqlplus_mock):
    long_value = "USER_MODIFIED_TARGET_DATE=07022026, " * 140  # ~5040 chars
    sqlplus_mock["csv_body"] = f'"ID","ADDITIONAL_PROPS"\n1,"{long_value}"\n'
    result = _run_sqlplus_csv(
        "alias",
        "user",
        "secret",
        "select 1 as id, additional_props from trexone_data.system_audit",
        max_rows=10,
        timeout_s=5,
    )
    assert result.row_count == 1
    assert len(result.rows[0][1]) > 5000


def test_multiline_value_with_embedded_commas_and_newlines(sqlplus_mock):
    sqlplus_mock["csv_body"] = (
        '"ID","COMMENT_TEXT"\n'
        '1,"line one,\nline two\nline three"\n'
        '2,"plain"\n'
    )
    result = _run_sqlplus_csv(
        "alias",
        "user",
        "secret",
        "select id, comment_text from trexone_data.system_audit",
        max_rows=10,
        timeout_s=5,
    )
    assert result.row_count == 2
    assert result.rows[0][1] == "line one,\nline two\nline three"
    assert result.rows[1][1] == "plain"


def test_ora_substring_in_data_does_not_trigger_error(sqlplus_mock):
    sqlplus_mock["csv_body"] = (
        '"ID","NOTE"\n'
        '1,"AuthorizationCode=null, MessageIdentifier=B288, ORA-01403 in upstream"\n'
    )
    result = _run_sqlplus_csv(
        "alias",
        "user",
        "secret",
        "select id, note from trexone_data.system_audit",
        max_rows=10,
        timeout_s=5,
    )
    assert result.row_count == 1
    assert "ORA-01403" in result.rows[0][1]


def test_truncation_flag_set_when_more_rows_available(sqlplus_mock):
    rows = "\n".join(f'{i},"val{i}"' for i in range(1, 6))
    sqlplus_mock["csv_body"] = f'"ID","V"\n{rows}\n'
    result = _run_sqlplus_csv(
        "alias", "user", "secret", "select id, v from t", max_rows=4, timeout_s=5
    )
    assert result.row_count == 4
    assert result.truncated is True


def test_partial_output_raises_with_diagnostic(monkeypatch, tmp_path):
    """Begin sentinel emitted but end missing (mid-stream cancel/kill) must
    raise instead of silently reporting 0 rows."""
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    def runner(cmd, *args, input=None, **kwargs):
        for line in (input or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("prompt __ORAFLOW_CSV_BEGIN_"):
                begin = stripped[len("prompt ") :]
                stdout = f"Connected.\n{begin}\n\"ID\"\n1\n"
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=stdout, stderr=""
                )
        raise AssertionError("no begin sentinel found in script")

    monkeypatch.setattr(subprocess, "run", runner)
    with pytest.raises(RuntimeError, match="interrupted mid-stream"):
        _run_sqlplus_csv(
            "alias",
            "user",
            "secret",
            "select rx_record_num from trexone_data.h_rx",
            max_rows=10,
            timeout_s=5,
        )
    assert list((tmp_path / "OraFlow" / "db" / "logs" / "sqlplus").glob("sqlplus_*_no_end.log"))


def test_pre_select_failure_raises_with_diagnostic(sqlplus_mock):
    sqlplus_mock["raw_stdout_override"] = "ORA-00942: table or view does not exist\n"
    sqlplus_mock["returncode"] = 942
    with pytest.raises(RuntimeError, match=r"ORA-00942"):
        _run_sqlplus_csv(
            "alias",
            "user",
            "secret",
            "select 1 from no_such_table",
            max_rows=10,
            timeout_s=5,
        )


def test_password_is_redacted_in_error_messages(sqlplus_mock):
    password = "S3cret!Pa55"
    sqlplus_mock["raw_stdout_override"] = (
        f"SP2-0306: option {password} not recognized\n"
    )
    sqlplus_mock["returncode"] = 1
    with pytest.raises(RuntimeError) as exc:
        _run_sqlplus_csv(
            "alias", "user", password, "select 1 from dual", max_rows=1, timeout_s=5
        )
    assert password not in str(exc.value)
    assert "***" in str(exc.value)


def test_empty_result_set_returns_zero_rows_not_error(sqlplus_mock):
    sqlplus_mock["csv_body"] = '"ID","NAME"\n'
    result = _run_sqlplus_csv(
        "alias",
        "user",
        "secret",
        "select id, name from t where 1 = 0",
        max_rows=10,
        timeout_s=5,
    )
    assert result.row_count == 0
    assert result.columns == ["ID", "NAME"]
    assert result.truncated is False


# ---------------------------------------------------------------------------
# Phase 2 — script splitter -> validator: realistic multi-statement scripts.
# ---------------------------------------------------------------------------


def test_authored_script_with_inline_comments_splits_into_individual_selects(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    body = """
WITH chain AS (SELECT 1 AS n FROM dual)
SELECT * FROM chain; -- statement 1

SELECT count(*) FROM trexone_data.rx_base; -- statement 2

SELECT rx_record_num
FROM   trexone_data.system_audit
WHERE  partition_date > add_months(sysdate, -24); -- statement 3

WITH x AS (SELECT 1 n FROM dual)
SELECT * FROM x; -- statement 4

SELECT 'has;semicolon' AS s FROM dual; -- statement 5
""".strip()

    artifact = author_sql_script(
        "erxd_pipeline_smoke", body, description="pipeline smoke"
    )
    statements = validate_script_file(artifact.script_path)
    assert len(statements) == 5
    assert Path(artifact.script_path).parent == tmp_path / "OraFlow" / "db" / "scripts" / "ad_hoc"
    assert Path(artifact.output_path).parent == tmp_path / "OraFlow" / "db" / "outputs" / "ad_hoc"
    assert all(
        s.lower().lstrip("( ").startswith(("select", "with")) for s in statements
    )


def test_author_sql_script_buckets_ticket_named_scripts(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    artifact = author_sql_script("ERXD-73437_diagnostic", "select 1 from dual")

    assert Path(artifact.script_path).parent == tmp_path / "OraFlow" / "db" / "scripts" / "ERXD-73437"
    assert Path(artifact.output_path).parent == tmp_path / "OraFlow" / "db" / "outputs" / "ERXD-73437"


def test_script_containing_write_is_rejected_by_validator(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    body = """
SELECT 1 FROM dual;
UPDATE trexone_data.rx_base SET rx_status_num = 9 WHERE rownum = 1;
SELECT 2 FROM dual;
""".strip()

    from oraflow.safety import SqlSafetyError

    with pytest.raises(SqlSafetyError):
        author_sql_script("erxd_write_blocked", body, description="should fail")


# ---------------------------------------------------------------------------
# Phase 3 — output formatting: ensure markdown structure stays sane.
# ---------------------------------------------------------------------------


def test_format_results_emits_one_section_per_statement(tmp_path: Path):
    from oraflow.models import QueryResult

    results = [
        QueryResult(
            columns=["A", "B"],
            rows=[["1", "x"], ["2", "y"]],
            row_count=2,
            truncated=False,
            elapsed_ms=12.3,
            max_rows=100,
        ),
        QueryResult(
            columns=["ID"],
            rows=[],
            row_count=0,
            truncated=False,
            elapsed_ms=5.0,
            max_rows=100,
        ),
    ]
    out = format_results_for_output(Path("dummy.sql"), results)
    assert "## Q1" in out
    assert "## Q2" in out
    assert "Rows: 2; Truncated: False; Elapsed ms: 12.3" in out
    assert "Rows: 0; Truncated: False; Elapsed ms: 5.0" in out
    assert "A\tB" in out
    assert "1\tx" in out
    assert "2\ty" in out


# ---------------------------------------------------------------------------
# Phase 4 — durable evidence: JSON sidecar + warning when row bodies are missing.
# ---------------------------------------------------------------------------


def test_results_json_payload_round_trips(tmp_path: Path):
    import json

    from oraflow.models import QueryResult

    results = [
        QueryResult(
            columns=["ID", "NAME"],
            rows=[[1, "alpha"], [2, None]],
            row_count=2,
            truncated=False,
            elapsed_ms=11.1,
            max_rows=100,
        )
    ]
    payload = json.loads(results_to_json_payload(Path("inv.sql"), results))
    assert payload["script_path"].endswith("inv.sql")
    assert len(payload["statements"]) == 1
    stmt = payload["statements"][0]
    assert stmt["index"] == 1
    assert stmt["columns"] == ["ID", "NAME"]
    assert stmt["row_count"] == 2
    assert stmt["rows"] == [[1, "alpha"], [2, None]]


def test_format_results_warns_when_row_bodies_missing_but_count_positive(tmp_path: Path):
    """Regression: if backend reports 104 rows but rows=[], make the evidence
    file shout about it instead of looking innocently empty."""
    from oraflow.models import QueryResult

    results = [
        QueryResult(
            columns=["A"],
            rows=[],
            row_count=104,
            truncated=False,
            elapsed_ms=1.0,
            max_rows=100,
        )
    ]
    out = format_results_for_output(Path("dummy.sql"), results)
    assert "WARNING" in out
    assert "row_count=104" in out


def test_script_output_paths_uses_db_outputs_bucket(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    sql = tmp_path / "OraFlow" / "db" / "scripts" / "ERXD-1" / "x.sql"
    sql.parent.mkdir(parents=True)
    sql.write_text("select 1 from dual", encoding="utf-8")
    txt, js = script_output_paths(sql)
    assert txt == tmp_path / "OraFlow" / "db" / "outputs" / "ERXD-1" / "x_output.txt"
    assert js == tmp_path / "OraFlow" / "db" / "outputs" / "ERXD-1" / "x_output.json"


def test_script_output_paths_rejects_non_db_script_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    sql = tmp_path / "OraFlow" / "sql" / "x.sql"
    sql.parent.mkdir(parents=True)
    sql.write_text("select 1 from dual", encoding="utf-8")

    with pytest.raises(ValueError, match="SQL script must be under"):
        script_output_paths(sql)


def test_author_sql_script_does_not_clobber_populated_output(
    tmp_path: Path, monkeypatch
):
    """Regression: re-authoring a script (e.g. description tweak, typo fix)
    must NOT destroy the populated evidence file from a prior run_sql_script.
    """
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    artifact = author_sql_script("inv_clobber", "select 1 from dual", description="v1")
    populated_marker = "ROW=10009623246 important evidence"
    Path(artifact.output_path).write_text(populated_marker, encoding="utf-8")

    # Re-author the same script with a tweaked description.
    author_sql_script("inv_clobber", "select 1 from dual", description="v2")

    surviving = Path(artifact.output_path).read_text(encoding="utf-8")
    assert populated_marker in surviving, "author_sql_script clobbered prior evidence"


def test_read_script_output_rejects_paths_outside_oraflow_outputs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings
    from oraflow.server import read_script_output

    get_settings.cache_clear()
    outside = tmp_path / "secret.txt"
    outside.write_text("do not read", encoding="utf-8")

    with pytest.raises(ValueError, match="outside OraFlow workspace"):
        read_script_output(str(outside))


def test_read_script_results_allows_only_oraflow_db_scripts_and_outputs(tmp_path: Path, monkeypatch):
    import json

    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings
    from oraflow.server import read_script_results

    get_settings.cache_clear()
    root = tmp_path / "OraFlow"
    sql_dir = root / "db" / "scripts" / "ad_hoc"
    outputs_dir = root / "db" / "outputs" / "ad_hoc"
    sql_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)
    script = sql_dir / "safe.sql"
    script.write_text("select 1 from dual", encoding="utf-8")
    payload = {"ok": True}
    (outputs_dir / "safe_output.json").write_text(json.dumps(payload), encoding="utf-8")

    assert read_script_results(str(script)) == payload

    outside_json = tmp_path / "outside_output.json"
    outside_json.write_text(json.dumps({"secret": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="outside OraFlow workspace"):
        read_script_results(str(outside_json))


def test_sqlplus_parser_drops_header_leak_as_first_row(sqlplus_mock):
    """Regression: 12.2 SQL*Plus sometimes re-emits column headers as a data
    row, producing literal placeholder values in ping_db (AHF-PROD bug).
    The parser must drop a leading data row that equals the column header.
    """
    sqlplus_mock["csv_body"] = (
        '"DATABASE_NAME","INSTANCE_NAME","SERVICE_NAME","VERSION"\n'
        '"DATABASE_NAME","INSTANCE_NAME","SERVICE_NAME","VERSION"\n'
        '"PXAHFP01","TXAHFP01","txahfp01","Oracle Database 19c"\n'
    )
    result = _run_sqlplus_csv(
        "alias", "user", "secret", "select * from dual", max_rows=10, timeout_s=5
    )
    assert result.row_count == 1
    assert result.rows[0] == ["PXAHFP01", "TXAHFP01", "txahfp01", "Oracle Database 19c"]


def test_sqlplus_timeout_dumps_partial_output_and_raises_clear_error(
    monkeypatch, tmp_path
):
    """Regression: when sqlplus is killed by the watchdog (subprocess.TimeoutExpired),
    OraFlow must (a) raise a descriptive RuntimeError that mentions the timeout
    and the offending alias, and (b) persist whatever partial stdout/stderr the
    child managed to emit to OraFlow/db/logs/sqlplus/ so L3 has something to read.
    """
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    # The debug dump path is computed via the workspace dir → flush caches.
    from oraflow.config import get_settings

    get_settings.cache_clear()

    partial_stdout = "Connected.\nSession altered.\nprompt __ORAFLOW_CSV_BEGIN_xxx__\n"

    def fake_run(cmd, *args, input=None, timeout=None, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=cmd, timeout=timeout, output=partial_stdout, stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc:
        _run_sqlplus_csv(
            "ALIAS-PROD",
            "user",
            "secret",
            "select 1 from dual",
            max_rows=10,
            timeout_s=5,
        )

    msg = str(exc.value)
    assert "timed out" in msg
    assert "ALIAS-PROD" in msg
    # The error must point the investigator at the dump file.
    assert "Partial sqlplus output saved to:" in msg

    # Confirm the dump file actually exists and contains the partial output.
    logs_dir = tmp_path / "OraFlow" / "db" / "logs" / "sqlplus"
    assert logs_dir.is_dir(), "timeout path should create the logs directory"
    dumps = list(logs_dir.glob("sqlplus_*_timeout.log"))
    assert dumps, "expected at least one *_timeout.log under OraFlow/db/logs/sqlplus/"
    contents = dumps[0].read_text(encoding="utf-8")
    assert "Connected." in contents
    # Password must NOT leak into the dump file.
    assert "secret" not in contents


def test_sqlplus_timeout_redacts_password_from_dump(monkeypatch, tmp_path):
    """Tighter assertion: even when sqlplus stalls and partial output happens
    to contain the password (it shouldn't, but be paranoid), the dump file
    must redact it before writing to disk."""
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    password = "P@ss-Word-123"
    leaky_partial = f"Connected as user/{password}\nSession altered.\n"

    def fake_run(cmd, *args, input=None, timeout=None, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=cmd, timeout=timeout, output=leaky_partial, stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError):
        _run_sqlplus_csv(
            "ALIAS-PROD",
            "user",
            password,
            "select 1 from dual",
            max_rows=10,
            timeout_s=5,
        )

    dumps = list((tmp_path / "OraFlow" / "db" / "logs" / "sqlplus").glob("sqlplus_*_timeout.log"))
    assert dumps
    contents = dumps[0].read_text(encoding="utf-8")
    assert password not in contents
    assert "***" in contents
