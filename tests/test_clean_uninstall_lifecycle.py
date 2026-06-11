from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEAN_UNINSTALL = REPO_ROOT / "scripts" / "clean-uninstall.ps1"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_fixture(root: Path) -> dict[str, Path]:
    user = root / "user"
    appdata = root / "appdata" / "Roaming"
    temp = root / "temp"
    workspace = root / "workspace"
    for path in (user, appdata, temp, workspace):
        path.mkdir(parents=True, exist_ok=True)

    write_text(user / ".oraflow" / "credentials.toml", 'profile = "keep-or-remove"\n')
    write_text(user / ".oraflow" / "jira.toml", 'jira = "keep-or-remove"\n')

    write_text(user / ".vscode" / "extensions" / "enterpriserx.oraflow-0.1.0" / "old.txt", "old")
    write_text(user / ".vscode" / "extensions" / "mpserx-erx-0.0.1" / "old.txt", "old")
    write_text(
        user / ".vscode" / "extensions" / ".obsolete",
        json.dumps({"enterpriserx.oraflow-0.1.0": True, "other.ext": True}),
    )
    write_text(
        user / ".vscode" / "extensions" / "extensions.json",
        json.dumps(
            [
                {
                    "identifier": {"id": "enterpriserx.oraflow"},
                    "location": {"path": "C:/old/enterpriserx.oraflow-0.1.0"},
                },
                {"identifier": {"id": "other.ext"}, "location": {"path": "C:/ok/other.ext"}},
            ]
        ),
    )

    write_text(appdata / "Code" / "User" / "globalStorage" / "enterpriserx.oraflow" / "state.json", "{}")
    write_text(appdata / "Code" / "CachedExtensionVSIXs" / "oraflow-cache.vsix", "cache")
    write_text(appdata / "Code" / "logs" / "oraflow.log", "log")
    write_text(
        appdata / "Code" / "User" / "workspaceStorage" / "exact" / "workspace.json",
        json.dumps({"folder": workspace.as_uri()}),
    )
    write_text(appdata / "Code" / "User" / "workspaceStorage" / "exact" / "state.vscdb", "state")
    write_text(appdata / "Code" / "User" / "workspaceStorage" / "loose" / "oraflow-cache.txt", "cache")

    write_text(temp / "oraflow-old" / "x.txt", "temp")
    write_text(temp / "github-copilot" / "project-context" / "OraFlow-old" / "x.txt", "context")
    write_text(temp / "github-copilot" / "project-index" / "OraFlow-old" / "x.txt", "index")
    write_text(temp / "v_inspect" / "x.txt", "inspect")
    write_text(temp / "v_lfinal" / "x.txt", "lfinal")

    write_text(workspace / "oraflow-mcp.spec", "# fixture repo marker\n")
    write_text(workspace / "extensions" / "vscode" / "package.json", "{}")
    write_text(workspace / "src" / "oraflow" / "__init__.py", "")
    for relative in (
        "build/old.txt",
        "dist/old.txt",
        "extensions/vscode/dist/old.txt",
        "extensions/vscode/node_modules/old.txt",
        "extensions/vscode/oraflow-old.zip",
    ):
        write_text(workspace / relative, "generated")

    write_text(
        workspace / ".vscode" / "mcp.json",
        json.dumps(
            {
                "servers": {
                    "oraflow": {
                        "type": "stdio",
                        "command": "C:/old/enterpriserx.oraflow-0.1.0/bin/oraflow-mcp.exe",
                        "env": {"ORAFLOW_MANAGED_BY_EXTENSION": "true"},
                    },
                    "other": {"type": "stdio", "command": "ok"},
                }
            }
        ),
    )
    write_text(
        workspace / ".github" / "copilot-instructions.md",
        "user header\n"
        "<!-- BEGIN ORAFLOW AGENT INSTRUCTIONS (managed by OraFlow extension; do not edit between markers) -->\n"
        "managed body\n"
        "<!-- END ORAFLOW AGENT INSTRUCTIONS -->\n"
        "user footer\n",
    )
    write_text(workspace / "OraFlow" / "db" / "scripts" / "ERXD-1" / "q.sql", "select 1 from dual;\n")
    write_text(workspace / "OraFlow" / "jira" / "ERXD-1" / "issue.json", "{}")
    write_text(workspace / "OraFlow" / "session.json", "{}")
    write_text(workspace / "mpserx-erx" / "legacy.txt", "legacy evidence")

    return {"user": user, "appdata": appdata, "temp": temp, "workspace": workspace}


def run_clean_uninstall(paths: dict[str, Path], *args: str) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is required for clean-uninstall lifecycle tests")
    env = os.environ.copy()
    env.update(
        {
            "USERPROFILE": str(paths["user"]),
            "APPDATA": str(paths["appdata"]),
            "TEMP": str(paths["temp"]),
            "TMP": str(paths["temp"]),
        }
    )
    return subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(CLEAN_UNINSTALL),
            *args,
            "-Workspace",
            str(paths["workspace"]),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def assert_extension_state_removed(paths: dict[str, Path]) -> None:
    user = paths["user"]
    appdata = paths["appdata"]
    temp = paths["temp"]

    assert not (user / ".vscode" / "extensions" / "enterpriserx.oraflow-0.1.0").exists()
    assert not (user / ".vscode" / "extensions" / "mpserx-erx-0.0.1").exists()
    assert "oraflow" not in (user / ".vscode" / "extensions" / ".obsolete").read_text(encoding="utf-8").lower()
    extensions_json = json.loads((user / ".vscode" / "extensions" / "extensions.json").read_text(encoding="utf-8"))
    assert isinstance(extensions_json, list)
    assert "oraflow" not in json.dumps(extensions_json).lower()
    assert [entry["identifier"]["id"] for entry in extensions_json] == ["other.ext"]

    assert not (appdata / "Code" / "User" / "globalStorage" / "enterpriserx.oraflow").exists()
    assert not (appdata / "Code" / "CachedExtensionVSIXs" / "oraflow-cache.vsix").exists()
    assert not (appdata / "Code" / "logs" / "oraflow.log").exists()
    assert not (temp / "oraflow-old").exists()
    assert not (temp / "github-copilot" / "project-context" / "OraFlow-old").exists()
    assert not (temp / "github-copilot" / "project-index" / "OraFlow-old").exists()
    assert not (temp / "v_inspect").exists()
    assert not (temp / "v_lfinal").exists()


def assert_dev_artifacts_removed(workspace: Path) -> None:
    assert not (workspace / "build").exists()
    assert not (workspace / "dist").exists()
    assert not (workspace / "extensions" / "vscode" / "dist").exists()
    assert not (workspace / "extensions" / "vscode" / "node_modules").exists()
    assert not (workspace / "extensions" / "vscode" / "oraflow-old.zip").exists()


def test_clean_uninstall_upgrade_preserves_user_owned_state(tmp_path: Path) -> None:
    paths = make_fixture(tmp_path / "upgrade")

    run_clean_uninstall(paths, "-Upgrade")

    assert_extension_state_removed(paths)
    assert_dev_artifacts_removed(paths["workspace"])
    assert (paths["user"] / ".oraflow" / "credentials.toml").exists()
    assert (paths["user"] / ".oraflow" / "jira.toml").exists()
    assert (paths["workspace"] / "OraFlow" / "db" / "scripts" / "ERXD-1" / "q.sql").exists()
    assert (paths["workspace"] / "OraFlow" / "jira" / "ERXD-1" / "issue.json").exists()
    assert (paths["workspace"] / "mpserx-erx" / "legacy.txt").exists()
    assert (paths["appdata"] / "Code" / "User" / "workspaceStorage" / "exact" / "state.vscdb").exists()

    mcp = json.loads((paths["workspace"] / ".vscode" / "mcp.json").read_text(encoding="utf-8"))
    assert set(mcp["servers"]) == {"oraflow", "other"}

    instructions = (paths["workspace"] / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert "BEGIN ORAFLOW AGENT INSTRUCTIONS" in instructions
    assert "user header" in instructions
    assert "user footer" in instructions


def test_clean_uninstall_full_clean_removes_oraflow_owned_state(tmp_path: Path) -> None:
    paths = make_fixture(tmp_path / "full-clean")

    run_clean_uninstall(paths)

    assert_extension_state_removed(paths)
    assert_dev_artifacts_removed(paths["workspace"])
    assert not (paths["user"] / ".oraflow").exists()
    assert not (paths["workspace"] / "OraFlow").exists()
    assert not (paths["workspace"] / "mpserx-erx").exists()
    assert not (paths["appdata"] / "Code" / "User" / "workspaceStorage" / "exact").exists()

    mcp_path = paths["workspace"] / ".vscode" / "mcp.json"
    raw_mcp = mcp_path.read_bytes()
    assert not raw_mcp.startswith(b"\xef\xbb\xbf")
    mcp = json.loads(raw_mcp.decode("utf-8"))
    assert set(mcp["servers"]) == {"other"}

    instructions = (paths["workspace"] / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert "ORAFLOW AGENT INSTRUCTIONS" not in instructions
    assert "managed body" not in instructions
    assert "user header" in instructions
    assert "user footer" in instructions