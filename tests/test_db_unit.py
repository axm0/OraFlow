"""Unit tests for `oraflow.db` helpers and the python-oracledb execution path.

These cover the cloud DEV / QA branch (`ConnectionManager.run_query`) which
the prior test suite did not touch, plus the pure routing/normalization
helpers (`_json_value`, `_redact_secret`, `_use_sqlplus12_first`,
`_needs_sqlplus_fallback`, `_dsn_with_timeout`). The on-prem PROD branch is
already covered by `test_sqlplus_csv.py` and `test_pipeline.py`.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from oraflow.db import (
    ConnectionManager,
    _dsn_with_timeout,
    _json_value,
    _needs_sqlplus_fallback,
    _redact_secret,
    _use_sqlplus12_first,
)
from oraflow.models import TnsEntry

# ---------------------------------------------------------------------------
# _json_value: cell normaliser used by BOTH the python-oracledb path and the
# sqlplus CSV path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("hello", "hello"),
        (42, 42),
        (1.5, 1.5),
        (True, True),
        (False, False),
        (Decimal("10009623246"), 10009623246),  # Big integer via NUMBER column.
        (Decimal("1.25"), 1.25),  # NUMBER(p,s) with fractional part.
        (Decimal("0"), 0),  # Edge case: zero rounds to int.
        (Decimal("-7.5"), -7.5),  # Negative fractional.
        (date(2026, 5, 8), "2026-05-08"),
        (datetime(2026, 4, 23, 11, 47, 28), "2026-04-23T11:47:28"),
        (
            datetime(2026, 4, 23, 11, 47, 28, tzinfo=UTC),
            "2026-04-23T11:47:28+00:00",
        ),
        (b"\x00\xff\x42", "00ff42"),  # bytes -> hex.
        (b"", ""),  # empty bytes.
    ],
)
def test_json_value_round_trips(value, expected):
    assert _json_value(value) == expected


def test_json_value_falls_back_to_str_for_unknown_types():
    class CustomThing:
        def __str__(self):
            return "custom-repr"

    assert _json_value(CustomThing()) == "custom-repr"


# ---------------------------------------------------------------------------
# _redact_secret: must replace every occurrence, no-op on falsy inputs.
# ---------------------------------------------------------------------------


def test_redact_secret_replaces_all_occurrences():
    msg = "user/topsecret connected; topsecret tried again"
    assert _redact_secret(msg, "topsecret") == "user/*** connected; *** tried again"


@pytest.mark.parametrize("secret", [None, ""])
def test_redact_secret_passthrough_on_empty_secret(secret):
    msg = "anything goes"
    assert _redact_secret(msg, secret) == msg


def test_redact_secret_handles_empty_message():
    assert _redact_secret("", "topsecret") == ""


# ---------------------------------------------------------------------------
# _use_sqlplus12_first: PROD non-cloud routes through bundled SQL*Plus 12.2,
# everything else stays on python-oracledb (subject to env-var overrides).
# ---------------------------------------------------------------------------


def _entry(env: str | None, source_tag: str | None) -> TnsEntry:
    return TnsEntry(
        key="x", alias="x", descriptor="(DESCRIPTION=)", environment=env, source_tag=source_tag
    )


@pytest.mark.parametrize(
    "env, tag, expected",
    [
        ("PROD", "onprem", True),
        ("prod", "onprem", True),  # case-insensitive.
        ("PROD", "cloud", False),  # cloud PROD stays on python-oracledb.
        ("DEV", "cloud", False),
        ("QA", "onprem", False),
        ("UAT", "onprem", False),
        (None, "onprem", False),
        ("PROD", None, True),  # missing source_tag treated as on-prem.
    ],
)
def test_use_sqlplus12_first_routing(env, tag, expected, monkeypatch):
    monkeypatch.delenv("ORAFLOW_SQLPLUS12_FIRST", raising=False)
    monkeypatch.delenv("ORAFLOW_DISABLE_SQLPLUS12_FIRST", raising=False)
    assert _use_sqlplus12_first(_entry(env, tag)) is expected


def test_use_sqlplus12_first_force_via_env(monkeypatch):
    monkeypatch.setenv("ORAFLOW_SQLPLUS12_FIRST", "1")
    monkeypatch.delenv("ORAFLOW_DISABLE_SQLPLUS12_FIRST", raising=False)
    # DEV cloud would normally be False; the override must flip it to True.
    assert _use_sqlplus12_first(_entry("DEV", "cloud")) is True


def test_use_sqlplus12_first_disable_via_env(monkeypatch):
    monkeypatch.setenv("ORAFLOW_DISABLE_SQLPLUS12_FIRST", "1")
    monkeypatch.delenv("ORAFLOW_SQLPLUS12_FIRST", raising=False)
    # PROD onprem would normally be True; the override must flip it to False.
    assert _use_sqlplus12_first(_entry("PROD", "onprem")) is False


# ---------------------------------------------------------------------------
# _needs_sqlplus_fallback: identify Oracle/python-oracledb errors that should
# trigger the bundled SQL*Plus 12.2 fallback path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "msg, expected",
    [
        ("ORA-01017: invalid username/password; logon denied", True),
        ("ORA-12270 incompatible network protocol version", True),
        ("DPY-4011: The connection cannot be established.", True),
        ("ORA-03135: connection lost contact", True),
        ("ORA-00942: table or view does not exist", False),
        ("ORA-12541: TNS:no listener", False),  # different network error.
        ("Random Python error", False),
        ("", False),
    ],
)
def test_needs_sqlplus_fallback(msg, expected):
    assert _needs_sqlplus_fallback(Exception(msg)) is expected


# ---------------------------------------------------------------------------
# _dsn_with_timeout: TNS descriptor rewriter.
# ---------------------------------------------------------------------------


def test_dsn_with_timeout_inserts_timeout_fragment():
    dsn = "(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=h)(PORT=1521))(CONNECT_DATA=(SID=s)))"
    out = _dsn_with_timeout(dsn, 7)
    assert "CONNECT_TIMEOUT=7" in out
    assert "TRANSPORT_CONNECT_TIMEOUT=7" in out
    assert "RETRY_COUNT=0" in out
    # Original payload preserved.
    assert "HOST=h" in out and "SID=s" in out


def test_dsn_with_timeout_is_idempotent_when_already_present():
    dsn = (
        "(DESCRIPTION=(CONNECT_TIMEOUT=99)(ADDRESS=(PROTOCOL=TCP)(HOST=h)(PORT=1521))"
        "(CONNECT_DATA=(SID=s)))"
    )
    out = _dsn_with_timeout(dsn, 5)
    # Pre-existing fragment must be left alone (no duplicate inserted).
    assert out.count("CONNECT_TIMEOUT=") == 1
    assert "CONNECT_TIMEOUT=99" in out


def test_dsn_with_timeout_replaces_server_default():
    dsn = "(DESCRIPTION=(ADDRESS=(SERVER=default)(PORT=1521)))"
    out = _dsn_with_timeout(dsn, 10)
    assert "SERVER=DEDICATED" in out
    assert "SERVER=default" not in out


# ---------------------------------------------------------------------------
# ConnectionManager.run_query: python-oracledb path with a mocked Connection.
# This is the cloud DEV / QA execution path — previously untested.
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_connection():
    """Build a MagicMock Connection that can be `with`-ed into a cursor and
    captures every method call for assertion."""
    cursor = MagicMock(name="cursor")
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)

    connection = MagicMock(name="connection")
    connection.cursor.return_value = cursor
    connection.call_timeout = 0  # gets set by run_query
    return connection, cursor


def test_run_query_executes_set_transaction_read_only_first(fake_connection):
    connection, cursor = fake_connection
    cursor.description = [("ID", None), ("NAME", None)]
    cursor.fetchmany.return_value = [(1, "Alice"), (2, "Bob")]

    mgr = ConnectionManager()
    result = mgr.run_query(
        connection, "select id, name from dual", max_rows=100, timeout_s=60
    )

    # First execute = SET TRANSACTION READ ONLY, second = the SELECT.
    execute_calls = [c.args[0] for c in cursor.execute.call_args_list]
    assert execute_calls[0].upper().startswith("SET TRANSACTION READ ONLY")
    assert "select id, name from dual" in execute_calls[1].lower()
    assert result.row_count == 2
    assert result.columns == ["ID", "NAME"]
    assert result.rows == [[1, "Alice"], [2, "Bob"]]
    assert result.truncated is False


def test_run_query_sets_call_timeout_in_milliseconds(fake_connection):
    connection, cursor = fake_connection
    cursor.description = [("X", None)]
    cursor.fetchmany.return_value = []

    mgr = ConnectionManager()
    mgr.run_query(connection, "select 1 from dual", max_rows=10, timeout_s=45)
    assert connection.call_timeout == 45 * 1000


def test_run_query_uses_default_timeout_when_none_given(fake_connection):
    connection, cursor = fake_connection
    cursor.description = [("X", None)]
    cursor.fetchmany.return_value = []

    mgr = ConnectionManager()
    mgr.run_query(connection, "select 1 from dual", max_rows=10)
    assert connection.call_timeout == mgr.settings.query_timeout_s * 1000


def test_run_query_truncation_flag_when_more_rows_returned(fake_connection):
    connection, cursor = fake_connection
    cursor.description = [("ID", None)]
    # Caller asked for 3; cursor returns 4 (max_rows + 1).
    cursor.fetchmany.return_value = [(1,), (2,), (3,), (4,)]

    mgr = ConnectionManager()
    result = mgr.run_query(connection, "select id from t", max_rows=3)
    assert result.row_count == 3
    assert result.truncated is True
    # Caller-visible rows are capped at max_rows.
    assert [row[0] for row in result.rows] == [1, 2, 3]
    # fetchmany was asked for max_rows + 1 to detect truncation.
    cursor.fetchmany.assert_called_once_with(4)


def test_run_query_normalizes_native_oracle_types(fake_connection):
    """`run_query` must apply `_json_value` so Decimal, datetime, and bytes
    columns become JSON-friendly. Crucial for big NUMBER PKs and dates."""
    connection, cursor = fake_connection
    cursor.description = [
        ("RX_RECORD_NUM", None),
        ("DATESTAMP", None),
        ("PAYLOAD", None),
    ]
    cursor.fetchmany.return_value = [
        (
            Decimal("10009623246"),
            datetime(2026, 4, 23, 11, 47, 28),
            b"\x00\xff\x42",
        ),
    ]
    mgr = ConnectionManager()
    result = mgr.run_query(
        connection, "select rx_record_num, datestamp, payload from t", max_rows=10
    )
    assert result.rows == [
        [10009623246, "2026-04-23T11:47:28", "00ff42"],
    ]


def test_run_query_handles_no_resultset_statement(fake_connection):
    """When `cursor.description is None` the SELECT had no projection
    (rare, but possible for some Oracle metadata calls). Must return an
    empty QueryResult, not raise."""
    connection, cursor = fake_connection
    cursor.description = None
    cursor.rowcount = -1  # python-oracledb's "unknown" sentinel.

    mgr = ConnectionManager()
    result = mgr.run_query(connection, "select 1 from dual", max_rows=5)
    assert result.row_count == 0
    assert result.columns == []
    assert result.rows == []
    assert result.truncated is False


def test_run_query_rolls_back_before_set_transaction(fake_connection):
    """The python-oracledb path issues `connection.rollback()` before
    `SET TRANSACTION READ ONLY` so the read-only mode applies cleanly."""
    connection, cursor = fake_connection
    cursor.description = [("X", None)]
    cursor.fetchmany.return_value = []

    mgr = ConnectionManager()
    mgr.run_query(connection, "select 1 from dual", max_rows=1)
    assert connection.rollback.called


def test_run_query_validates_input_before_executing(fake_connection):
    """Validator must run before any database call so blocked SQL never
    reaches the cursor."""
    connection, cursor = fake_connection

    mgr = ConnectionManager()
    from oraflow.safety import SqlSafetyError

    with pytest.raises(SqlSafetyError):
        mgr.run_query(connection, "delete from t", max_rows=10)
    # No execute call should have happened.
    assert not cursor.execute.called


# ---------------------------------------------------------------------------
# `_use_sqlplus12_first` interaction with environment variable casing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "all"])
def test_use_sqlplus12_first_force_accepts_truthy_values(monkeypatch, value):
    monkeypatch.setenv("ORAFLOW_SQLPLUS12_FIRST", value)
    monkeypatch.delenv("ORAFLOW_DISABLE_SQLPLUS12_FIRST", raising=False)
    assert _use_sqlplus12_first(_entry("DEV", "cloud")) is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "anything-else"])
def test_use_sqlplus12_first_force_ignores_falsy_values(monkeypatch, value):
    monkeypatch.setenv("ORAFLOW_SQLPLUS12_FIRST", value)
    monkeypatch.delenv("ORAFLOW_DISABLE_SQLPLUS12_FIRST", raising=False)
    # DEV cloud falls back to the default (False).
    assert _use_sqlplus12_first(_entry("DEV", "cloud")) is False


# ---------------------------------------------------------------------------
# Small property: CSV path settings carry through both PROD-style routings.
# (Sanity check that the manager's `settings.query_timeout_s` is respected
# by `run_query` and matches the configured default.)
# ---------------------------------------------------------------------------


def test_manager_default_timeout_matches_settings(fake_connection):
    connection, cursor = fake_connection
    cursor.description = [("X", None)]
    cursor.fetchmany.return_value = []

    mgr = ConnectionManager()
    expected_timeout = mgr.settings.query_timeout_s
    mgr.run_query(connection, "select 1 from dual", max_rows=1)
    assert connection.call_timeout == expected_timeout * 1000


def test_repo_workspace_root_is_a_real_directory():
    """Smoke check: the project's workspace_root resolves to something on
    disk so the CLI/server can find tnsnames.ora and bundled assets."""
    from oraflow.config import workspace_root

    root = workspace_root()
    assert root.is_dir()
    assert (root / "src" / "oraflow").is_dir()
    # No assertion on os.environ — keep it independent of dev-machine layout.
    _ = os


# ---------------------------------------------------------------------------
# ping_db defensive header-leak detection (Bug B backstop).
#
# The parser fix (Bug A) already drops header rows that leak into the data
# rows. The defensive check in `_sqlplus_ping` is a second line of defense:
# if a FUTURE sqlplus quirk lets header literals reach the ping result row,
# we must NOT silently return them as real identity values (the AHF/Kinney
# PROD failure mode from the live ERXD-73437 test). These tests bypass the
# parser by monkeypatching `_run_sqlplus_csv` so we can simulate a leak.
# ---------------------------------------------------------------------------


def test_sqlplus_ping_rejects_header_literals_as_identity_values(monkeypatch):
    """If `_run_sqlplus_csv` ever returns a row whose values are literal
    column names, `_sqlplus_ping` must return ok=False with a clear reason."""
    from oraflow import db as db_module
    from oraflow.models import QueryResult

    leaked_result = QueryResult(
        columns=["DATABASE_NAME", "INSTANCE_NAME", "SERVICE_NAME", "VERSION"],
        rows=[["DATABASE_NAME", "INSTANCE_NAME", "SERVICE_NAME", "VERSION"]],
        row_count=1,
        truncated=False,
        elapsed_ms=10.0,
        max_rows=1,
    )
    monkeypatch.setattr(db_module, "_run_sqlplus_csv", lambda *a, **kw: leaked_result)

    entry = TnsEntry(
        key="K", alias="K", descriptor="(DESCRIPTION=)", environment="PROD", source_tag="onprem"
    )
    ping = db_module._sqlplus_ping(entry, "user", "secret", timeout_s=5)

    assert ping.ok is False
    assert ping.error is not None
    assert "header_leak_suspected" in ping.error
    assert "database_name" in ping.error.lower()


def test_sqlplus_ping_accepts_real_identity_values(monkeypatch):
    """Sanity check: when `_run_sqlplus_csv` returns plausible identity values
    that do NOT match column names, the defensive guard must NOT fire."""
    from oraflow import db as db_module
    from oraflow.models import QueryResult

    good_result = QueryResult(
        columns=["DATABASE_NAME", "INSTANCE_NAME", "SERVICE_NAME", "VERSION"],
        rows=[["PXKINP01", "TXKINP01", "txkinp01", "Oracle Database 19c"]],
        row_count=1,
        truncated=False,
        elapsed_ms=10.0,
        max_rows=1,
    )
    monkeypatch.setattr(db_module, "_run_sqlplus_csv", lambda *a, **kw: good_result)

    entry = TnsEntry(
        key="K", alias="K", descriptor="(DESCRIPTION=)", environment="PROD", source_tag="onprem"
    )
    ping = db_module._sqlplus_ping(entry, "user", "secret", timeout_s=5)

    assert ping.ok is True
    assert ping.database_name == "PXKINP01"
    assert ping.instance_name == "TXKINP01"
    assert ping.service_name == "txkinp01"
    assert ping.version == "Oracle Database 19c"


def test_sqlplus_ping_header_leak_check_is_case_insensitive(monkeypatch):
    """The guard must trip whether sqlplus returns 'DATABASE_NAME' or
    'database_name' — we don't trust capitalization quirks across builds."""
    from oraflow import db as db_module
    from oraflow.models import QueryResult

    leaked_result = QueryResult(
        columns=["DATABASE_NAME", "INSTANCE_NAME", "SERVICE_NAME", "VERSION"],
        rows=[["database_name", "instance_name", "service_name", "version"]],
        row_count=1,
        truncated=False,
        elapsed_ms=10.0,
        max_rows=1,
    )
    monkeypatch.setattr(db_module, "_run_sqlplus_csv", lambda *a, **kw: leaked_result)

    entry = TnsEntry(
        key="K", alias="K", descriptor="(DESCRIPTION=)", environment="PROD", source_tag="onprem"
    )
    ping = db_module._sqlplus_ping(entry, "user", "secret", timeout_s=5)
    assert ping.ok is False
    assert "header_leak_suspected" in (ping.error or "")

