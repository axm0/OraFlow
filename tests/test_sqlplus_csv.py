"""Tests for `_parse_sqlplus_csv_output` — the CSV slicing/parsing helper that
on-prem PROD reads pass through.

These tests do not require a live database. They feed canned sqlplus stdout
strings through the parser and assert correctness for the bug classes that
the previous `startswith('"')` filter mishandled.
"""

from __future__ import annotations

from oraflow.db import _parse_sqlplus_csv_output

BEGIN = "__ORAFLOW_CSV_BEGIN_test__"
END = "__ORAFLOW_CSV_END_test__"


def _wrap(csv_body: str, *, prologue: str = "Session altered.\n", epilogue: str = "") -> str:
    """Build sqlplus-like stdout: prologue chatter, CSV slice between sentinels, epilogue."""
    return f"{prologue}{BEGIN}\n{csv_body}{END}\n{epilogue}"


def test_number_first_column_returns_rows():
    """Regression: the old filter dropped rows whose first column was a NUMBER (unquoted).

    Q2/Q3/Q4/Q5 in the ERXD-73403 audit script all start with a NUMBER PK; they
    were silently returning 0 rows on PROD before this fix.
    """
    csv_body = (
        '"SYSTEM_AUDIT_NUM","AUDIT_NAME","RX_RECORD_NUM"\n'
        '11421195405,"SecurityAdmin.DataEntryEntryAuditConfig",10009623246\n'
        '11421230211,"PatientAdmin.ERPAudit",10009623246\n'
    )
    output = _wrap(csv_body)
    cols, rows, truncated, begin_found, end_found = _parse_sqlplus_csv_output(
        output, max_rows=100, begin=BEGIN, end=END
    )
    assert begin_found and end_found
    assert cols == ["SYSTEM_AUDIT_NUM", "AUDIT_NAME", "RX_RECORD_NUM"]
    assert len(rows) == 2
    assert rows[0][0] == "11421195405"
    assert rows[0][2] == "10009623246"
    assert truncated is False


def test_multiline_quoted_value_preserved():
    """RFC4180 quoted values can contain literal newlines; csv.reader handles
    that natively when fed the contiguous slice."""
    csv_body = (
        '"ID","COMMENT_TEXT"\n'
        '1,"line one\nline two\nline three"\n'
        '2,"single line"\n'
    )
    output = _wrap(csv_body)
    cols, rows, *_ = _parse_sqlplus_csv_output(output, max_rows=100, begin=BEGIN, end=END)
    assert cols == ["ID", "COMMENT_TEXT"]
    assert len(rows) == 2
    assert rows[0][1] == "line one\nline two\nline three"
    assert rows[1][1] == "single line"


def test_chatter_outside_sentinels_is_ignored():
    """Lines like 'Session altered.', blank lines, and other non-CSV chatter
    outside the sentinel block must not affect parsing."""
    csv_body = '"X"\n"a"\n"b"\n'
    output = (
        "SQL*Plus banner line\n"
        "Session altered.\n"
        "Session altered.\n"
        "\n"
        f"{BEGIN}\n"
        f"{csv_body}"
        f"{END}\n"
        "Disconnected from Oracle Database 19c\n"
    )
    cols, rows, *_ = _parse_sqlplus_csv_output(output, max_rows=10, begin=BEGIN, end=END)
    assert cols == ["X"]
    assert [r[0] for r in rows] == ["a", "b"]


def test_ora_substring_inside_csv_is_not_an_error_signal():
    """A data value containing 'ORA-12345' must not be treated as an Oracle
    error. The parser doesn't enforce this — it just returns the row — but
    this test pins the expectation that such values flow through cleanly.
    The error scan is performed in `_run_sqlplus_csv` against the non-CSV
    portion only; this test guards the parser contract."""
    csv_body = '"ID","NOTE"\n1,"Saw ORA-12345 in the upstream system"\n'
    output = _wrap(csv_body)
    cols, rows, *_ = _parse_sqlplus_csv_output(output, max_rows=10, begin=BEGIN, end=END)
    assert cols == ["ID", "NOTE"]
    assert rows[0][1] == "Saw ORA-12345 in the upstream system"


def test_truncation_detected_when_extra_row_present():
    """`_run_sqlplus_csv` requests max_rows + 1 from sqlplus so the parser can
    detect truncation. Verify the flag is set and the extra row is dropped."""
    csv_body = '"ID"\n"a"\n"b"\n"c"\n"d"\n'
    output = _wrap(csv_body)
    cols, rows, truncated, *_ = _parse_sqlplus_csv_output(
        output, max_rows=3, begin=BEGIN, end=END
    )
    assert cols == ["ID"]
    assert [r[0] for r in rows] == ["a", "b", "c"]
    assert truncated is True


def test_empty_result_set_returns_header_only():
    """A SELECT that legitimately returns zero rows must come back as
    (columns, [], not truncated, sentinels found)."""
    csv_body = '"ID","NAME"\n'
    output = _wrap(csv_body)
    cols, rows, truncated, begin_found, end_found = _parse_sqlplus_csv_output(
        output, max_rows=10, begin=BEGIN, end=END
    )
    assert begin_found and end_found
    assert cols == ["ID", "NAME"]
    assert rows == []
    assert truncated is False


def test_missing_begin_sentinel_signaled():
    """If sqlplus aborts before reaching the SELECT (e.g., bind/parse error
    fires `whenever sqlerror exit`), the begin sentinel is never emitted.
    The parser must report this so `_run_sqlplus_csv` can raise instead of
    silently returning 0 rows."""
    output = "Session altered.\nORA-00942: table or view does not exist\n"
    cols, rows, truncated, begin_found, end_found = _parse_sqlplus_csv_output(
        output, max_rows=10, begin=BEGIN, end=END
    )
    assert begin_found is False
    assert end_found is False
    assert cols == [] and rows == []


def test_missing_end_sentinel_signaled():
    """If sqlplus is killed mid-stream (e.g., subprocess timeout), the begin
    sentinel may be present but the end sentinel will not. The parser must
    differentiate this from a clean empty result."""
    output = (
        "Session altered.\n"
        f"{BEGIN}\n"
        '"ID"\n'
        '1\n'
        '2\n'  # no END sentinel — interrupted mid-stream
    )
    cols, rows, truncated, begin_found, end_found = _parse_sqlplus_csv_output(
        output, max_rows=10, begin=BEGIN, end=END
    )
    assert begin_found is True
    assert end_found is False
    assert cols == [] and rows == []


def test_blank_lines_inside_csv_block_are_ignored():
    """sqlplus sometimes emits a trailing blank line after the data; csv.reader
    yields [] for it. The parser must drop those without inflating row count."""
    csv_body = '"ID"\n"a"\n\n"b"\n\n'
    output = _wrap(csv_body)
    cols, rows, *_ = _parse_sqlplus_csv_output(output, max_rows=10, begin=BEGIN, end=END)
    assert cols == ["ID"]
    assert [r[0] for r in rows] == ["a", "b"]


def test_leading_blank_line_before_header_does_not_leak_header_into_rows():
    """ERXD-73437 regression: Kinney PROD `-67` runs produced CSV blocks where
    sqlplus emitted a blank line BEFORE the column header line. The old parser
    blindly used parsed[0] as columns, leaving columns=[] and pushing the real
    header into rows[0]. format_results_for_output then rendered `(no result
    set)` for runs that actually had data, and row_count was inflated by 1.
    """
    csv_body = '\n"PROOF_POINT","ROW_COUNT"\n"Q1_SPI_COUNT",1\n'
    output = _wrap(csv_body)
    cols, rows, truncated, begin_found, end_found = _parse_sqlplus_csv_output(
        output, max_rows=10, begin=BEGIN, end=END
    )
    assert begin_found and end_found
    assert cols == ["PROOF_POINT", "ROW_COUNT"]
    assert len(rows) == 1
    assert rows[0] == ["Q1_SPI_COUNT", "1"]
    assert truncated is False


def test_multiple_leading_blank_lines_before_header_tolerated():
    """Belt-and-braces: even if sqlplus emits several blank lines in a row,
    blank-row filtering before header pick must still produce correct columns."""
    csv_body = '\n\n\n"ID","NAME"\n1,"alpha"\n2,"beta"\n'
    output = _wrap(csv_body)
    cols, rows, *_ = _parse_sqlplus_csv_output(output, max_rows=10, begin=BEGIN, end=END)
    assert cols == ["ID", "NAME"]
    assert rows == [["1", "alpha"], ["2", "beta"]]


def test_blank_lines_around_header_and_data_preserve_correct_row_count():
    """Mixed leading / interleaved / trailing blanks should never inflate
    row_count past the actual data rows."""
    csv_body = '\n\n"A","B"\n\n1,"x"\n\n2,"y"\n\n'
    output = _wrap(csv_body)
    cols, rows, *_ = _parse_sqlplus_csv_output(output, max_rows=10, begin=BEGIN, end=END)
    assert cols == ["A", "B"]
    assert rows == [["1", "x"], ["2", "y"]]


def test_long_clob_like_value_passes_through_intact():
    """CLOB columns (e.g. system_audit.additional_props) can return values
    much longer than the SQL*Plus default LONG=80. With `set long 1000000`
    in the prologue, sqlplus emits the full quoted value; the parser must
    return it intact without truncation."""
    long_value = "USER_MODIFIED_TARGET_DATE=07022026, " * 200  # ~7400 chars
    csv_body = f'"ID","ADDITIONAL_PROPS"\n1,"{long_value}"\n'
    output = _wrap(csv_body)
    cols, rows, *_ = _parse_sqlplus_csv_output(output, max_rows=10, begin=BEGIN, end=END)
    assert cols == ["ID", "ADDITIONAL_PROPS"]
    assert len(rows) == 1
    assert rows[0][1] == long_value
    assert len(rows[0][1]) > 7000


def test_utf8_multibyte_value_preserved():
    """NLS_LANG=AL32UTF8 + Python text=utf-8 means non-ASCII characters in
    VARCHAR2 columns must round-trip cleanly."""
    csv_body = '"ID","NAME"\n1,"María José"\n2,"O\'Brien"\n3,"日本語"\n'
    output = _wrap(csv_body)
    cols, rows, *_ = _parse_sqlplus_csv_output(output, max_rows=10, begin=BEGIN, end=END)
    assert cols == ["ID", "NAME"]
    assert rows[0][1] == "María José"
    assert rows[1][1] == "O'Brien"
    assert rows[2][1] == "日本語"


def test_null_fields_become_empty_strings():
    """sqlplus markup csv emits NULLs as empty unquoted positions (`,,`).
    `csv.reader` returns "" for those. Treat as empty string consistently."""
    csv_body = '"ID","A","B","C"\n1,,"x",\n2,"y",,\n'
    output = _wrap(csv_body)
    cols, rows, *_ = _parse_sqlplus_csv_output(output, max_rows=10, begin=BEGIN, end=END)
    assert cols == ["ID", "A", "B", "C"]
    assert rows[0] == ["1", "", "x", ""]
    assert rows[1] == ["2", "y", "", ""]


def test_timestamp_with_tz_value_passes_through():
    """`alter session set nls_timestamp_tz_format='YYYY-MM-DD"T"HH24:MI:SS.FF TZR'`
    in the prologue makes TIMESTAMP WITH TIME ZONE columns ISO-friendly. The
    parser only needs to preserve the quoted value verbatim."""
    csv_body = '"ID","STARTED_AT"\n1,"2026-04-23T11:47:28.123456 America/New_York"\n'
    output = _wrap(csv_body)
    cols, rows, *_ = _parse_sqlplus_csv_output(output, max_rows=10, begin=BEGIN, end=END)
    assert cols == ["ID", "STARTED_AT"]
    assert rows[0][1] == "2026-04-23T11:47:28.123456 America/New_York"


