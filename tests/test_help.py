"""Tests for oraflow.help (oraflow_help MCP tool backing)."""

from __future__ import annotations

from pathlib import Path

import pytest

from oraflow import help as help_mod


@pytest.fixture
def fake_topics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    f = tmp_path / "help-topics.toml"
    f.write_text(
        '''
[overview]
title = "OraFlow"
body = """
# Overview body
Hello.
"""

[safety]
title = "Safety"
body = """
# Safety body
Read-only.
"""
'''.strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORAFLOW_HELP_TOPICS_PATH", str(f))
    return f


def test_get_topic_returns_body(fake_topics: Path) -> None:
    body = help_mod.get_topic("overview")
    assert "Overview body" in body
    assert "Hello." in body


def test_get_topic_default_is_overview(fake_topics: Path) -> None:
    assert help_mod.get_topic() == help_mod.get_topic("overview")
    assert help_mod.get_topic(None) == help_mod.get_topic("overview")


def test_get_topic_unknown_lists_available(fake_topics: Path) -> None:
    out = help_mod.get_topic("does-not-exist")
    assert "Unknown topic 'does-not-exist'" in out
    assert "overview" in out and "safety" in out


def test_load_help_topics_normalizes_keys(fake_topics: Path) -> None:
    topics = help_mod.load_help_topics()
    assert set(topics.keys()) == {"overview", "safety"}
    assert topics["overview"]["title"] == "OraFlow"


def test_list_topics_falls_back_to_known_topics_when_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no help-topics.toml can be located, list_topics() falls back to KNOWN_TOPICS."""
    monkeypatch.setattr(help_mod, "help_topics_path", lambda: None)
    topics = help_mod.list_topics()
    assert topics == list(help_mod.KNOWN_TOPICS)


def test_get_topic_when_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the resolver to behave as if no file exists anywhere.
    monkeypatch.setattr(help_mod, "help_topics_path", lambda: None)
    out = help_mod.get_topic("overview")
    assert "Help topics are not bundled" in out


def test_ships_with_known_topics() -> None:
    """The bundled help-topics.toml in extensions/vscode/assets must cover KNOWN_TOPICS."""
    # No env override -> uses the dev-tree fallback.
    topics = help_mod.load_help_topics()
    if not topics:
        pytest.skip("help-topics.toml not present in this checkout")
    for required in help_mod.KNOWN_TOPICS:
        assert required in topics, f"missing bundled help topic: {required}"
        assert topics[required]["body"], f"empty body for help topic: {required}"


def test_tools_topic_is_a_categorized_catalog() -> None:
    """The 'tools' topic must give a one-call catalog grouped by every tool
    category so a fresh session can self-orient without opening docs."""
    topics = help_mod.load_help_topics()
    if not topics:
        pytest.skip("help-topics.toml not present in this checkout")
    body = topics["tools"]["body"]
    # Every category prefix used in the live tool descriptions must appear.
    for category in (
        "[meta]", "[discovery]", "[target]", "[schema]",
        "[script]", "[execute]", "[jira]",
        "[simple-nonprod-only]", "[advanced-session-only]",
    ):
        assert category in body, f"tools catalog missing category {category}"
    # Representative tools from each area must be listed so the catalog can't rot.
    for tool in (
        "oraflow_config", "search_tns", "set_active_target", "search_schema",
        "author_sql_script", "run_active_target_script", "read_script_results",
        "jira_get_ticket", "run_query_once", "connect",
    ):
        assert tool in body, f"tools catalog missing tool {tool}"


def test_config_info_includes_next_steps() -> None:
    from oraflow.config import CANONICAL_NEXT_STEPS, config_info

    info = config_info()
    assert info.next_steps, "ConfigInfo.next_steps must be populated"
    assert info.next_steps == CANONICAL_NEXT_STEPS
    # Each step is tagged with a [category] prefix that agents can filter on.
    assert all(step.startswith("[") and "]" in step for step in info.next_steps)
    # Workflow ordering guard: discovery must precede execute.
    joined = "\n".join(info.next_steps)
    assert joined.index("[discovery]") < joined.index("[execute]")
    assert "run_active_target_script" in joined
    assert "read_script_results" in joined


def test_config_info_uses_credentials_path_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from oraflow.config import config_info, get_settings

    credentials = tmp_path / "credentials.toml"
    credentials.write_text(
        '[onprem.qa]\nusername = "qa_user"\npassword = "qa_password"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ORAFLOW_CREDENTIALS_PATH", str(credentials))
    monkeypatch.delenv("ORAFLOW_DBCREDS_PATH", raising=False)
    get_settings.cache_clear()
    try:
        info = config_info()
    finally:
        get_settings.cache_clear()

    assert info.credentials_path == str(credentials)


def test_config_info_uses_explicit_tnsnames_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from oraflow.config import config_info, get_settings

    first = tmp_path / "tnsnames.ora"
    second = tmp_path / "cloud-tnsnames.ora"
    first.write_text(
        "LOCAL=(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=db)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=svc)))\n",
        encoding="utf-8",
    )
    second.write_text(
        "CLOUD=(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=db)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=svc)))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ORAFLOW_TNSNAMES_PATHS", f"{first};{second}")
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("TNS_ADMIN", raising=False)
    monkeypatch.delenv("ORACLE_HOME", raising=False)
    get_settings.cache_clear()
    try:
        info = config_info()
    finally:
        get_settings.cache_clear()

    assert info.tnsnames_path == str(first)
    assert info.tnsnames_paths == [str(first), str(second)]
    assert info.tns_admin == str(tmp_path)
    assert info.workspace_dir == str(tmp_path)
    assert info.oracle_home is None


def test_extension_assets_use_current_credentials_env_var() -> None:
    root = Path(__file__).resolve().parents[1]
    extension = (root / "extensions" / "vscode" / "extension.js").read_text(encoding="utf-8")
    verifier = (root / "scripts" / "verify-vsix-internals.ps1").read_text(encoding="utf-8")

    assert "ORAFLOW_CREDENTIALS_PATH" in extension
    assert "ORAFLOW_CREDENTIALS_PATH" in verifier
    assert "ORAFLOW_DBCREDS_PATH" not in extension
    assert "stale OraFlow env/config names" in verifier


def test_mcp_instructions_lock_in_investigation_routing() -> None:
    root = Path(__file__).resolve().parents[1]
    instructions = (root / "ORAFLOW_INSTRUCTIONS.md").read_text(encoding="utf-8")
    packaged = (root / "extensions" / "vscode" / "assets" / "ORAFLOW_INSTRUCTIONS.md").read_text(encoding="utf-8")

    assert packaged == instructions
    assert "Hard execution routing rule" in instructions
    assert "never use `connect`, `run_query`, `run_query_once`" in instructions
    assert "do not substitute live/session schema tools" in instructions
    assert "Before finalizing an investigation report, check `OraFlow/db/_audit/runs.jsonl`" in instructions
    assert "run_active_target_script" in instructions
    assert "read_script_results" in instructions
    assert "Do not treat a run as evidence unless `read_script_results` succeeds" in instructions


def test_help_topics_prefer_active_target_json_workflow() -> None:
    topics = help_mod.load_help_topics()
    safety = topics["safety"]["body"]
    workflow = topics["workflow"]["body"]

    assert "ping_active_target" in safety
    assert "run_active_target_script" in safety
    assert "read_script_results" in safety
    assert "Never use `connect`, `run_query`, `run_query_once`" in safety
    assert "do not substitute live `describe_table`" in safety
    assert "check `OraFlow/db/_audit/runs.jsonl`" in workflow
    assert "JSON sidecar" in workflow


def test_find_bundled_resource_prefers_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The shared resource resolver must honor the env override above all else."""
    from oraflow.config import find_bundled_resource

    target = tmp_path / "ORAFLOW_INSTRUCTIONS.md"
    target.write_text("env wins", encoding="utf-8")
    monkeypatch.setenv("ORAFLOW_INSTRUCTIONS_PATH", str(target))
    resolved = find_bundled_resource("ORAFLOW_INSTRUCTIONS_PATH", "ORAFLOW_INSTRUCTIONS.md")
    assert resolved == target.resolve()


def test_find_bundled_resource_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from oraflow.config import find_bundled_resource

    monkeypatch.setenv("ORAFLOW_NONEXISTENT_PATH", str(tmp_path / "nope.txt"))
    # dev_relative path is also missing, so resolver must return None.
    out = find_bundled_resource(
        "ORAFLOW_NONEXISTENT_PATH",
        "definitely-not-a-real-file.xyz",
        dev_relative=Path("nope") / "nope.xyz",
    )
    assert out is None


