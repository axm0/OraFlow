"""Tests for `load_sql_file_statements` — the SQL splitter that runs before
every script execution. The previous implementation split on any line whose
trailing character was ``;`` after whitespace was removed, which silently
absorbed the next statement when a user wrote an inline trailing comment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oraflow.sqlfile import load_sql_file_statements


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "script.sql"
    path.write_text(body, encoding="utf-8")
    return path


def test_two_statements_each_terminated_normally(tmp_path: Path):
    body = "select 1 from dual;\nselect 2 from dual;\n"
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert statements == ["select 1 from dual", "select 2 from dual"]


def test_inline_comment_after_terminator(tmp_path: Path):
    """Regression: ``SELECT ... ; -- end`` used to leak the trailing comment
    onto the next line, merging two statements and tripping the validator."""
    body = (
        "select 1 from dual; -- end of first\n"
        "select 2 from dual; -- end of second\n"
    )
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert len(statements) == 2
    assert "select 1 from dual" in statements[0]
    assert "select 2 from dual" in statements[1]


def test_block_comment_containing_semicolon_not_split(tmp_path: Path):
    body = (
        "/* note: this comment has a ; inside it */\n"
        "select 1 from dual;\n"
    )
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert len(statements) == 1
    assert "select 1 from dual" in statements[0]


def test_string_literal_containing_semicolon_not_split(tmp_path: Path):
    body = "select 'a;b' from dual;\nselect 2 from dual;\n"
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert len(statements) == 2
    assert "'a;b'" in statements[0]
    assert "select 2 from dual" in statements[1]


@pytest.mark.parametrize(
    "literal",
    [
        "q'[a;b]'",
        "q'(a;b)'",
        "q'{a;b}'",
        "q'<a;b>'",
        "q'!a;b!'",
        "Q'[A;B]'",
    ],
)
def test_q_quoted_literal_containing_semicolon_not_split(tmp_path: Path, literal: str):
    body = f"select {literal} as s from dual;\nselect 2 from dual;\n"
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert len(statements) == 2
    assert literal in statements[0]
    assert "select 2 from dual" in statements[1]


def test_escaped_quote_inside_string_literal(tmp_path: Path):
    body = "select 'O''Brien' from dual;\nselect 2 from dual;\n"
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert len(statements) == 2
    assert "O''Brien" in statements[0]


def test_sqlplus_directives_stripped(tmp_path: Path):
    body = (
        "SET LINESIZE 200\n"
        "SET PAGESIZE 100\n"
        "COLUMN x FORMAT A20\n"
        "PROMPT starting\n"
        "SPOOL output.log\n"
        "select 1 from dual;\n"
    )
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert len(statements) == 1
    assert statements[0].strip().lower().startswith("select")


def test_blank_lines_and_full_line_comments_ignored(tmp_path: Path):
    body = (
        "-- header comment\n"
        "\n"
        "-- another comment\n"
        "select 1 from dual;\n"
        "\n"
        "-- between\n"
        "select 2 from dual;\n"
    )
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert len(statements) == 2


def test_multi_line_statement_with_only_final_semicolon(tmp_path: Path):
    body = (
        "select a, b, c\n"
        "from   trexone_data.rx_base\n"
        "where  rx_record_num = 10009623246\n"
        ";\n"
    )
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert len(statements) == 1
    assert "trexone_data.rx_base" in statements[0]


def test_trailing_statement_without_semicolon(tmp_path: Path):
    body = "select 1 from dual;\nselect 2 from dual"
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert len(statements) == 2
    assert "select 2 from dual" in statements[1]


def test_with_cte_and_inline_comments(tmp_path: Path):
    body = (
        "with chain_rx as (\n"
        "    select 1 as n from dual\n"
        "    union all select 2 from dual -- middle row\n"
        ")\n"
        "select * from chain_rx; -- end of first\n"
        "select count(*) from dual; -- end of second\n"
    )
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert len(statements) == 2
    assert "with chain_rx" in statements[0].lower()


@pytest.mark.parametrize(
    "body, expected",
    [
        ("", 0),
        ("\n\n\n", 0),
        ("-- only comment\n", 0),
        ("SET LINESIZE 200\n", 0),
    ],
)
def test_empty_or_directive_only_files_yield_no_statements(
    tmp_path: Path, body: str, expected: int
):
    statements = load_sql_file_statements(_write(tmp_path, body))
    assert len(statements) == expected

