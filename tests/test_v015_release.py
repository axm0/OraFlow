"""Tests for backend release work: siblings, timeouts, failed audit, near-timeout."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from oraflow.customer_catalog import ResolvedTarget
from oraflow.db import OraflowTimeoutError, _run_sqlplus_csv
from oraflow.models import PingResult, QueryResult, TnsEntry
from oraflow.tns import TnsCatalog
from oraflow.workspace import (
    append_failed_run_log,
    append_run_log,
    format_results_for_output,
)

# ---------------------------------------------------------------------------
# Step 4 -- TnsCatalog.siblings
# ---------------------------------------------------------------------------


def _entry(
    *,
    key: str,
    alias: str | None = None,
    customer: str | None = "kinney",
    environment: str | None = "PROD",
    host_group: str | None = "txkinp01",
    source_tag: str | None = "onprem",
    sid_token: str | None = None,
) -> TnsEntry:
    return TnsEntry(
        key=key,
        alias=alias or key,
        descriptor="(DESCRIPTION=(ADDRESS=(HOST=h)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=svc)))",
        hosts=["h"],
        port=1521,
        sid=None,
        service_name="svc",
        customer=customer,
        environment=environment,
        sid_token=sid_token,
        host_group=host_group,
        source_path="/dev/null",
        source_tag=source_tag,
    )


def test_siblings_groups_same_customer_env_hostgroup_sourcetag():
    a = _entry(key="KINNEY-PROD.TXKINP01-55")
    b = _entry(key="KINNEY-PROD.TXKINP01-67")
    c = _entry(key="KINNEY-PROD.TXKINP01-99")
    catalog = TnsCatalog([a, b, c])
    siblings = catalog.siblings(a)
    keys = [e.key for e in siblings]
    assert keys == ["KINNEY-PROD.TXKINP01-67", "KINNEY-PROD.TXKINP01-99"]
    # And sorted ascending by key.
    assert keys == sorted(keys)


def test_siblings_excludes_self_by_default_includes_with_flag():
    a = _entry(key="KINNEY-PROD.TXKINP01-55")
    b = _entry(key="KINNEY-PROD.TXKINP01-67")
    catalog = TnsCatalog([a, b])
    assert [e.key for e in catalog.siblings(a)] == ["KINNEY-PROD.TXKINP01-67"]
    assert {e.key for e in catalog.siblings(a, include_self=True)} == {
        "KINNEY-PROD.TXKINP01-55",
        "KINNEY-PROD.TXKINP01-67",
    }


def test_siblings_rejects_different_environment():
    prod = _entry(key="KINNEY-PROD.TXKINP01-55", environment="PROD")
    qa = _entry(key="KINNEY-QA.TXKINQ01-55", environment="QA", host_group="txkinq01")
    catalog = TnsCatalog([prod, qa])
    assert catalog.siblings(prod) == []


def test_siblings_rejects_different_host_group_oltp_vs_dw():
    """Kinney TX (OLTP) PROD and DW (warehouse) PROD must not be siblings even
    though they share customer + env + source_tag, because host_group differs."""
    tx = _entry(key="KINNEY-PROD.TXKINP01-55", host_group="txkinp01")
    dw = _entry(key="KINNEY-PROD.DWKINP01-55", host_group="dwkinp01")
    catalog = TnsCatalog([tx, dw])
    assert catalog.siblings(tx) == []
    assert catalog.siblings(dw) == []


def test_siblings_rejects_different_source_tag_cloud_vs_onprem():
    cloud = _entry(key="KINNEY-PROD.x", source_tag="cloud")
    onprem = _entry(key="KINNEY-PROD.y", source_tag="onprem")
    catalog = TnsCatalog([cloud, onprem])
    assert catalog.siblings(cloud) == []


def test_siblings_returns_empty_when_grouping_keys_missing():
    unlabeled = _entry(key="random.alias", customer=None)
    catalog = TnsCatalog([unlabeled, _entry(key="other")])
    # No customer on unlabeled -> we refuse to group it.
    assert catalog.siblings(unlabeled) == []


def test_siblings_case_insensitive_match():
    a = _entry(key="KINNEY-PROD.TXKINP01-55", customer="Kinney", environment="PROD", host_group="TXKINP01")
    b = _entry(key="KINNEY-PROD.TXKINP01-67", customer="KINNEY", environment="prod", host_group="txkinp01")
    catalog = TnsCatalog([a, b])
    assert [e.key for e in catalog.siblings(a)] == ["KINNEY-PROD.TXKINP01-67"]


# ---------------------------------------------------------------------------
# Step 3 -- OraflowTimeoutError attributes (sqlplus path)
# ---------------------------------------------------------------------------


def test_sqlplus_timeout_raises_oraflow_timeout_error_with_structured_fields(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    def fake_run(cmd, *args, input=None, timeout=None, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=cmd, timeout=timeout, output="Connected.\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(OraflowTimeoutError) as exc_info:
        _run_sqlplus_csv(
            "KINNEY-PROD.TXKINP01-55",
            "user",
            "secret",
            "select 1 from dual",
            max_rows=10,
            timeout_s=5,
        )
    err = exc_info.value
    # Must still inherit RuntimeError so existing pytest.raises(RuntimeError) callers pass.
    assert isinstance(err, RuntimeError)
    assert err.alias == "KINNEY-PROD.TXKINP01-55"
    assert err.timeout_s == 5
    assert err.elapsed_s is not None and err.elapsed_s >= 0
    assert err.path == "sqlplus"
    assert err.debug_log_path is not None and Path(err.debug_log_path).is_file()
    as_dict = err.as_dict()
    assert as_dict["error_class"] == "OraflowTimeoutError"
    assert as_dict["alias"] == "KINNEY-PROD.TXKINP01-55"


# ---------------------------------------------------------------------------
# Step 8 -- near-timeout warning in format_results_for_output
# ---------------------------------------------------------------------------


def test_near_timeout_warning_emitted_when_elapsed_exceeds_80pct():
    result = QueryResult(
        columns=["A"],
        rows=[[1]],
        row_count=1,
        truncated=False,
        elapsed_ms=200_000.0,  # 200s
        max_rows=100,
        timeout_ms=240_000,    # 240s; elapsed = 83% of timeout
    )
    out = format_results_for_output(Path("dummy.sql"), [result])
    assert "WARNING" in out
    assert "83% of the 240s timeout" in out


def test_near_timeout_warning_not_emitted_when_well_under_threshold():
    result = QueryResult(
        columns=["A"],
        rows=[[1]],
        row_count=1,
        truncated=False,
        elapsed_ms=100_000.0,  # 100s = 42% of 240s
        max_rows=100,
        timeout_ms=240_000,
    )
    out = format_results_for_output(Path("dummy.sql"), [result])
    # Existing "row_count vs rows" warning must not fire either.
    assert "WARNING" not in out


def test_near_timeout_warning_skipped_when_timeout_unknown():
    """timeout_ms=0 is the synthetic-fixture / unknown sentinel; never warn."""
    result = QueryResult(
        columns=["A"],
        rows=[[1]],
        row_count=1,
        truncated=False,
        elapsed_ms=999_999.0,
        max_rows=100,
        timeout_ms=0,
    )
    out = format_results_for_output(Path("dummy.sql"), [result])
    assert "near-timeout" not in out.lower()


def test_near_timeout_boundary_exactly_80_does_not_warn():
    result = QueryResult(
        columns=["A"],
        rows=[[1]],
        row_count=1,
        truncated=False,
        elapsed_ms=192_000.0,  # exactly 80% of 240_000
        max_rows=100,
        timeout_ms=240_000,
    )
    out = format_results_for_output(Path("dummy.sql"), [result])
    # Strict > 80, so equal-to-80 must NOT trigger.
    assert "WARNING" not in out


# ---------------------------------------------------------------------------
# Step 7 -- failed-run audit row (workspace.append_failed_run_log)
# ---------------------------------------------------------------------------


def _workspace_with_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()
    script = tmp_path / "OraFlow" / "db" / "scripts" / "ad_hoc" / "demo.sql"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("select 1 from dual\n", encoding="utf-8")
    return script


def test_append_failed_run_log_writes_jsonl_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    script = _workspace_with_script(tmp_path, monkeypatch)
    append_failed_run_log(
        script,
        "KINNEY-PROD.TXKINP01-55",
        "user",
        error_class="OraflowTimeoutError",
        error_message="sqlplus timed out after 250s",
        elapsed_ms=250_000.0,
        debug_log_path=str(tmp_path / "OraFlow" / "db" / "logs" / "sqlplus" / "sqlplus_x.log"),
        sibling_aliases=["KINNEY-PROD.TXKINP01-67"],
    )
    rows = (tmp_path / "OraFlow" / "db" / "_audit" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    row = json.loads(rows[0])
    assert row["status"] == "failed"
    assert row["alias_or_key"] == "KINNEY-PROD.TXKINP01-55"
    assert row["error_class"] == "OraflowTimeoutError"
    assert row["sibling_aliases"] == ["KINNEY-PROD.TXKINP01-67"]
    assert row["debug_log_path"].endswith("sqlplus_x.log")
    assert row["sql_sha256"] is not None


def test_append_run_log_now_tags_status_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Happy-path audit row must carry status='ok' so a single jq pass over
    runs.jsonl can filter successes vs failures."""
    script = _workspace_with_script(tmp_path, monkeypatch)
    output_path = tmp_path / "OraFlow" / "db" / "outputs" / "ad_hoc" / "demo_output.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("# ok\n", encoding="utf-8")

    result = QueryResult(columns=["X"], rows=[[1]], row_count=1, truncated=False, elapsed_ms=12.0, max_rows=100)
    append_run_log(script, "ALIAS", "user", [result], output_path, elapsed_ms=12.0)
    row = json.loads((tmp_path / "OraFlow" / "db" / "_audit" / "runs.jsonl").read_text(encoding="utf-8").strip())
    assert row["status"] == "ok"


# ---------------------------------------------------------------------------
# Step 5 -- siblings in PingResult on failure
# ---------------------------------------------------------------------------


def test_ping_result_default_siblings_is_empty_list():
    """PingResult callers may omit siblings; the default remains an empty list."""
    e = _entry(key="alias")
    pr = PingResult(ok=False, entry=e, username="u", error="boom")
    assert pr.siblings == []
    pr2 = PingResult(ok=True, entry=e, username="u", database_name="db")
    assert pr2.siblings == []


def test_manager_enrich_ping_siblings_attaches_on_failure(monkeypatch):
    """ConnectionManager._enrich_ping_siblings should attach siblings only when
    the ping failed and the resolved entry has matching peers in the catalog."""
    from oraflow.db import ConnectionManager

    a = _entry(key="KINNEY-PROD.TXKINP01-55")
    b = _entry(key="KINNEY-PROD.TXKINP01-67")
    catalog = TnsCatalog([a, b])
    mgr = ConnectionManager(catalog=catalog)

    failed = PingResult(ok=False, entry=a, username="u", error="boom")
    enriched = mgr._enrich_ping_siblings(failed)
    assert [e.key for e in enriched.siblings] == ["KINNEY-PROD.TXKINP01-67"]

    ok = PingResult(ok=True, entry=a, username="u", database_name="x")
    # Successful pings are returned unchanged (no siblings attached).
    untouched = mgr._enrich_ping_siblings(ok)
    assert untouched.siblings == []


def test_ping_db_tool_enriches_unenriched_manager_failure(monkeypatch):
    """Even if a mocked manager returns a bare ok=False PingResult, the MCP
    tool layer should attach siblings so the agent can present alternatives."""
    from oraflow import server as server_module

    a = _entry(key="KINNEY-PROD.TXKINP01-55")
    b = _entry(key="KINNEY-PROD.TXKINP01-67")
    catalog = TnsCatalog([a, b])

    class _StubManager:
        def __init__(self, catalog):
            self.catalog = catalog

        def ping(self, *args, **kwargs):
            return PingResult(ok=False, entry=a, username="u", error="timeout")

    monkeypatch.setattr(server_module, "manager", _StubManager(catalog))
    result = server_module.ping_db("KINNEY-PROD.TXKINP01-55", username="u", password="p")
    assert result.ok is False
    assert [e.key for e in result.siblings] == ["KINNEY-PROD.TXKINP01-67"]


# ---------------------------------------------------------------------------
# Step 6 -- oraflow_search_siblings MCP tool (smoke via the underlying function)
# ---------------------------------------------------------------------------


def test_oraflow_search_siblings_tool_returns_alternate_endpoints(monkeypatch):
    """The MCP tool resolves the alias then hands off to catalog.siblings;
    verify the wired-up tool against a synthetic catalog."""
    from oraflow import db as db_module
    from oraflow.server import oraflow_search_siblings

    a = _entry(key="KINNEY-PROD.TXKINP01-55")
    b = _entry(key="KINNEY-PROD.TXKINP01-67")
    catalog = TnsCatalog([a, b])

    class _StubManager:
        def __init__(self, catalog):
            self.catalog = catalog

    monkeypatch.setattr(db_module, "manager", _StubManager(catalog))
    # Re-import the server module symbol so its reference to `manager` follows the patch.
    from oraflow import server as server_module

    monkeypatch.setattr(server_module, "manager", _StubManager(catalog))

    siblings = oraflow_search_siblings("KINNEY-PROD.TXKINP01-55")
    assert [e.key for e in siblings] == ["KINNEY-PROD.TXKINP01-67"]


# ---------------------------------------------------------------------------
# Step 7 wire-up smoke -- run_sql_script writes failed audit on exception
# ---------------------------------------------------------------------------


def test_run_sql_script_writes_failed_audit_row_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """End-to-end: when run_query_once raises OraflowTimeoutError, run_sql_script
    must append a status='failed' row to runs.jsonl with sibling enrichment
    and return a structured error payload. Mirrors the live Kinney PROD scenario."""
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    # Author a real script via the workspace helper so validate_script_file works.
    from oraflow.workspace import author_sql_script as write_sql_script

    artifact = write_sql_script("erxd_timeout_smoke", "select 1 from dual", description="timeout smoke")
    script_path = artifact.script_path

    # Stub the manager.catalog.resolve + .siblings + .run_query_once.
    from oraflow import db as db_module
    from oraflow import server as server_module

    a = _entry(key="KINNEY-PROD.TXKINP01-55")
    b = _entry(key="KINNEY-PROD.TXKINP01-67")
    catalog = TnsCatalog([a, b])

    class _StubManager:
        def __init__(self, catalog):
            self.catalog = catalog

        def run_query_once(self, *args, **kwargs):
            raise OraflowTimeoutError(
                "synthetic timeout",
                alias=a.key,
                timeout_s=5,
                elapsed_s=5.1,
                debug_log_path=str(tmp_path / "OraFlow" / "db" / "logs" / "sqlplus" / "synth.log"),
                path="sqlplus",
            )

    stub = _StubManager(catalog)
    monkeypatch.setattr(db_module, "manager", stub)
    monkeypatch.setattr(server_module, "manager", stub)

    payload = server_module.run_sql_script(
        "KINNEY-PROD.TXKINP01-55",
        script_path,
        username="user",
        password="secret",
    )

    assert payload["ok"] is False
    assert payload["error_class"] == "OraflowTimeoutError"
    assert payload["alias_or_key"] == "KINNEY-PROD.TXKINP01-55"
    assert payload["sibling_aliases"] == ["KINNEY-PROD.TXKINP01-67"]
    assert payload["debug_log_path"].endswith("synth.log")

    rows = (tmp_path / "OraFlow" / "db" / "_audit" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert rows, "expected a failed audit row in db/_audit/runs.jsonl"
    row = json.loads(rows[-1])
    assert row["status"] == "failed"
    assert row["error_class"] == "OraflowTimeoutError"
    assert row["alias_or_key"] == "KINNEY-PROD.TXKINP01-55"
    assert row["sibling_aliases"] == ["KINNEY-PROD.TXKINP01-67"]
    assert row["debug_log_path"].endswith("synth.log")
    # Verify no happy-row was written.
    assert not any(json.loads(r).get("status") == "ok" for r in rows)


def test_run_sql_script_uses_active_target_when_alias_omitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The documented active-target flow must be real: after set_active_target,
    script execution can omit alias/profile and still write durable evidence."""
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    from oraflow.target import set_active_target
    from oraflow.workspace import author_sql_script as write_sql_script

    artifact = write_sql_script("erxd_active_target_smoke", "select 1 as one from dual")
    active = ResolvedTarget(
        customer="kinney",
        display_name="KINNEY",
        env="prod",
        layer="oltp",
        tns_alias="KINNEY-PROD.TXKINP01-55",
        profile="ONPREM.PROD",
        requires_confirm=True,
        source="tns",
        deployment="onprem",
    )
    set_active_target(active)

    from oraflow import server as server_module

    entry = _entry(key="KINNEY-PROD.TXKINP01-55")
    calls: list[tuple[str, str, str, str]] = []

    class _StubManager:
        def __init__(self, catalog):
            self.catalog = catalog

        def run_query_once(self, alias, username, password, statement, **kwargs):
            calls.append((alias, username, password, statement))
            return QueryResult(
                columns=["ONE"],
                rows=[[1]],
                row_count=1,
                truncated=False,
                elapsed_ms=1.0,
                max_rows=kwargs.get("max_rows") or 100,
            )

    monkeypatch.setattr(server_module, "manager", _StubManager(TnsCatalog([entry])))
    payload = server_module.run_sql_script(script_path=artifact.script_path, username="user", password="secret")

    assert calls and calls[0][0] == "KINNEY-PROD.TXKINP01-55"
    assert payload["active_target"]["profile"] == "ONPREM.PROD"
    assert payload["results_json_path"].endswith("erxd_active_target_smoke_output.json")
    rows = (tmp_path / "OraFlow" / "db" / "_audit" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[-1])["status"] == "ok"
    get_settings.cache_clear()


def test_ping_active_target_uses_pinned_alias_and_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    from oraflow.config import get_settings

    get_settings.cache_clear()

    from oraflow.target import set_active_target

    active = ResolvedTarget(
        customer="kinney",
        display_name="KINNEY",
        env="prod",
        layer="oltp",
        tns_alias="KINNEY-PROD.TXKINP01-55",
        profile="ONPREM.PROD",
        requires_confirm=True,
        source="tns",
        deployment="onprem",
    )
    set_active_target(active)

    from oraflow import server as server_module

    entry = _entry(key="KINNEY-PROD.TXKINP01-55")
    calls: list[tuple[str, str, str]] = []

    class _StubManager:
        def __init__(self, catalog):
            self.catalog = catalog

        def ping(self, alias, username, password):
            calls.append((alias, username, password))
            return PingResult(ok=True, entry=entry, username=username, database_name="KINNEY")

    monkeypatch.setattr(server_module, "manager", _StubManager(TnsCatalog([entry])))
    result = server_module.ping_active_target(username="user", password="secret")

    assert result.ok is True
    assert calls == [("KINNEY-PROD.TXKINP01-55", "user", "secret")]
    get_settings.cache_clear()


def test_run_query_once_returns_structured_timeout_payload(monkeypatch, tmp_path: Path):
    """Inline discovery queries do not have a script artifact/audit row, but
    timeout failures still need machine-readable siblings/debug path."""
    from oraflow import server as server_module

    a = _entry(key="KINNEY-QA.TXKINQ01-55", environment="QA")
    b = _entry(key="KINNEY-QA.TXKINQ01-67", environment="QA")
    catalog = TnsCatalog([a, b])

    class _StubManager:
        def __init__(self, catalog):
            self.catalog = catalog

        def run_query_once(self, *args, **kwargs):
            raise OraflowTimeoutError(
                "synthetic inline timeout",
                alias=a.key,
                timeout_s=5,
                elapsed_s=5.1,
                debug_log_path=str(tmp_path / "OraFlow" / "logs" / "inline.log"),
                path="sqlplus",
            )

    monkeypatch.setattr(server_module, "manager", _StubManager(catalog))
    payload = server_module.run_query_once(
        "KINNEY-QA.TXKINQ01-55",
        "select 1 from dual",
        username="user",
        password="secret",
    )

    assert payload["ok"] is False
    assert payload["error_class"] == "OraflowTimeoutError"
    assert payload["sibling_aliases"] == ["KINNEY-QA.TXKINQ01-67"]
    assert payload["debug_log_path"].endswith("inline.log")


def test_run_query_once_refuses_prod_inline(monkeypatch):
    from oraflow import server as server_module

    entry = _entry(key="KINNEY-PROD.TXKINP01-55")

    class _StubManager:
        def __init__(self, catalog):
            self.catalog = catalog

        def run_query_once(self, *args, **kwargs):
            raise AssertionError("PROD inline query should be refused before execution")

    monkeypatch.setattr(server_module, "manager", _StubManager(TnsCatalog([entry])))
    payload = server_module.run_query_once(
        "KINNEY-PROD.TXKINP01-55",
        "select 1 from dual",
        username="user",
        password="secret",
    )

    assert payload["ok"] is False
    assert payload["error_class"] == "ProdInlineQueryRefused"
    assert "read_script_results" in payload["error"]


def test_run_query_rejects_dummy_and_alias_session_ids(monkeypatch):
    from oraflow import server as server_module

    entry = _entry(key="KINNEY-PROD.TXKINP01-55")

    class _StubManager:
        def __init__(self, catalog):
            self.catalog = catalog

        def run_query_by_session(self, *args, **kwargs):
            raise AssertionError("invalid session ids should not reach execution")

    monkeypatch.setattr(server_module, "manager", _StubManager(TnsCatalog([entry])))

    dummy = server_module.run_query("dummy", "select 1 from dual")
    alias = server_module.run_query("KINNEY-PROD.TXKINP01-55", "select 1 from dual")

    assert dummy["ok"] is False
    assert dummy["error_class"] == "InvalidSessionForQueryTool"
    assert alias["ok"] is False
    assert "TNS alias" in alias["error"]


def test_live_schema_session_tools_reject_placeholder_session_ids(monkeypatch):
    from oraflow import server as server_module

    entry = _entry(key="KINNEY-PROD.TXKINP01-55")

    class _StubManager:
        def __init__(self, catalog):
            self.catalog = catalog

        def get_connection(self, *args, **kwargs):
            raise AssertionError("placeholder session ids should not reach connection lookup")

        def list_tables(self, *args, **kwargs):
            raise AssertionError("placeholder session ids should not list live tables")

        def describe_table(self, *args, **kwargs):
            raise AssertionError("placeholder session ids should not describe live tables")

        def list_views(self, *args, **kwargs):
            raise AssertionError("placeholder session ids should not list live views")

    monkeypatch.setattr(server_module, "manager", _StubManager(TnsCatalog([entry])))

    table_payload = server_module.describe_table("schema_catalog", "TREXONE_DATA", "PRESCRIBER_ADDRESS")
    list_payload = server_module.list_tables("dummy", owner="TREXONE_DATA")
    view_payload = server_module.list_views("schema", owner="TREXONE_DATA")

    for payload in (table_payload, list_payload, view_payload):
        assert payload["ok"] is False
        assert payload["error_class"] == "InvalidSessionForQueryTool"
        assert "describe_schema_table" in payload["schema_next_step"]
        assert "read_script_results" in payload["investigation_next_step"]


def test_live_schema_session_tools_reject_alias_session_ids(monkeypatch):
    from oraflow import server as server_module

    entry = _entry(key="KINNEY-PROD.TXKINP01-55")

    class _StubManager:
        def __init__(self, catalog):
            self.catalog = catalog

        def get_connection(self, *args, **kwargs):
            raise AssertionError("alias session ids should not reach connection lookup")

    monkeypatch.setattr(server_module, "manager", _StubManager(TnsCatalog([entry])))

    payload = server_module.describe_table("KINNEY-PROD.TXKINP01-55", "TREXONE_DATA", "PRESCRIBER")

    assert payload["ok"] is False
    assert payload["error_class"] == "InvalidSessionForQueryTool"
    assert "TNS alias" in payload["error"]


