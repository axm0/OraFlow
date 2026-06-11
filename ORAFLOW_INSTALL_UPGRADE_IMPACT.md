# OraFlow Install, Download, and Upgrade Impact Contract

This is the source-of-truth checklist for what OraFlow downloads, writes, cleans,
and preserves. Review it for every code change that touches extension activation,
MCP config, credential setup, runtime resource resolution, build/package scripts,
Jira attachment handling, database execution, or cleanup behavior.

Documentation ownership:

- This file owns the canonical download/write/install/upgrade contract and the
  required change-impact checklist.
- `ORAFLOW_DOCS.md` owns engineering overview and command references; it should
  link here instead of duplicating this contract.
- `prompts/ORAFLOW_EXTENSION_UPGRADE.md` owns the procedural rebuild/upgrade
  prompt; it should call out this checklist but not redefine every location.
- `extensions/vscode/README.md` owns end-user setup and smoke testing; it should
  stay short and point engineers here for the full contract.

## Change Review Gate

No code/docs/package change is considered ready until the checklist in the
`Code Change Impact Checklist` section has been reviewed. If the change adds or
moves a download, cache, user-profile file, temp file, workspace file, MCP
config entry, extension activation behavior, cleanup target, or verifier
expectation, update this contract in the same change.

## Runtime Download Contract

The installed OraFlow VS Code extension must not download runtime dependencies or
backend code. The VSIX is the runtime package. It already contains:

- the frozen `oraflow-mcp` backend executable,
- Python dependency files required by the frozen backend,
- Oracle Instant Client,
- SQL*Plus 12.2 fallback runtime,
- bundled `tnsnames.ora`, `cloud-tnsnames.ora`, and `sqlnet.ora`,
- bundled schema catalog files,
- bundled help topics, customer catalog, and OraFlow instructions,
- the compiled VS Code extension JavaScript.

Expected network activity at runtime is tool-driven only:

- Oracle database connections happen only when DB tools are called.
- Jira HTTPS requests happen only when Jira tools are called.
- Jira attachment files are downloaded only when the tool caller explicitly sets
  the attachment-download option; default Jira fetches capture metadata only.
- OraFlow does not download FastMCP skills, Python packages, npm packages,
  Oracle clients, backend executables, or schema files after installation.

## Build-Time Downloads And Caches

The rebuild process can use local package managers. That is build-time behavior,
not extension runtime behavior.

| Action | What may be downloaded or cached | Where it can appear |
| --- | --- | --- |
| `uv run pyinstaller ...` | Python dependencies/interpreter artifacts if missing | `.venv/`, uv user cache, PyInstaller user cache |
| `npm ci` / `npm install` in `extensions/vscode` | VS Code extension build tooling such as `vsce` and `esbuild` | transient `extensions/vscode/node_modules/`, npm user cache |
| `vsce package` | No runtime dependency install; packages local extension files | `extensions/vscode/oraflow-<version>.vsix` |

`scripts/rebuild-vsix.ps1` bumps the patch version by default (e.g. `0.1.2` ->
`0.1.3`) so every rebuild produces a new version number. This prevents VS Code
from reusing a version-stamped extension folder on reinstall (the same-version
`.obsolete` trap, where the just-installed folder gets queued for deletion). It
syncs all three version sources in lockstep -- `extensions/vscode/package.json`,
`pyproject.toml`, and `src/oraflow/__init__.py` (the `__version__` that
`oraflow_version` reports) -- correcting any pre-existing drift between them.
Use `-Bump none` to rebuild the current version, `-Bump minor`/`-Bump major`, or
`-SetVersion x.y.z` to pin an explicit version.

`scripts/rebuild-vsix.ps1` removes repo-local transient outputs by default:
`build/`, `dist/`, `extensions/vscode/dist/`, and
`extensions/vscode/node_modules/`. It also removes stale VSIX/zip outputs before
building and deletes the previous bundled backend before copying the fresh one.

The script trims the bundled SQL*Plus 12.2 runtime via `Remove-SqlplusBundleBloat`,
which deletes only stray launcher tooling from `sqlplus12\bin` (`*.bat`, `*.cmd`,
`*.com`, and non-`sqlplus.exe` `*.exe`) plus `nls\lbuilder`. It MUST preserve
`sqlplus.exe` and every `*.dll` the executable links against. Filter by file
extension with `Where-Object` -- never `Get-ChildItem -Include` on a literal
directory path, because `-Include` is silently ignored without `-Recurse` or a
wildcard path and then matches EVERY file, which previously wiped the entire
`sqlplus12\bin` (177 files / ~135 MB, including `sqlplus.exe`) from the source
tree on each build and broke the SQL*Plus fallback. The matching audit in
`scripts/verify-vsix-internals.ps1` uses the same extension-based filter so a
restored `bin` of DLLs is not falsely flagged as untrimmed tooling.

## Install Locations

Installing the VSIX is handled by VS Code. Expected install/cache locations are:

| Owner | Location | Notes |
| --- | --- | --- |
| VS Code | `%USERPROFILE%\.vscode\extensions\enterpriserx.oraflow-*` | Installed extension payload. |
| VS Code Insiders | `%USERPROFILE%\.vscode-insiders\extensions\enterpriserx.oraflow-*` | Only if installed in Insiders. |
| Cursor/Windsurf | `%USERPROFILE%\.cursor\extensions\...`, `%USERPROFILE%\.windsurf\extensions\...` | Only if installed there. |
| VS Code | `%APPDATA%\Code\CachedExtensionVSIXs` / `CachedExtensions` | Optional editor-managed extension caches. |
| VS Code | `%APPDATA%\Code\logs` | Editor and extension logs. |
| VS Code | `%APPDATA%\Code\User\workspaceStorage` | Editor workspace state. Upgrade mode preserves exact workspace storage. |

OraFlow should not install files into arbitrary custom code repositories. It
only writes to a workspace when the user opens that workspace and configures or
uses OraFlow there.

## OraFlow-Created User And Workspace Files

| Location | Created by | Purpose | Upgrade behavior |
| --- | --- | --- | --- |
| `%USERPROFILE%\.oraflow\credentials.toml` | `OraFlow: Setup Credentials` | DB credential profiles | Preserved by `-Upgrade`. |
| `%USERPROFILE%\.oraflow\jira.toml` | `OraFlow: Setup Jira Credentials` | Jira API token config | Preserved by `-Upgrade`. |
| `%USERPROFILE%\.oraflow\managed-workspaces.json` | Configure/activation | Registry of workspaces where OraFlow wrote a managed `mcp.json`/instruction block, so the native `vscode:uninstall` hook can find and undo them | Removed by the uninstall hook; recreated on next configure/activation. |
| `<workspace>\.vscode\mcp.json` | `OraFlow: Configure MCP for Workspace` | Managed `oraflow` MCP server entry | Preserved by `-Upgrade`; extension activation refreshes managed paths. |
| `<workspace>\.github\copilot-instructions.md` | Configure/activation | Managed OraFlow agent instruction block | Preserved by `-Upgrade`; extension activation refreshes the managed block. |
| `<workspace>\OraFlow\db\...` | DB evidence tools | SQL scripts, results, logs, audit JSONL | Preserved by `-Upgrade`. |
| `<workspace>\OraFlow\jira\...` | Jira tools | Ticket JSON, comments, summaries, metadata, optional attachments | Preserved by `-Upgrade`. |
| `<workspace>\OraFlow\session.json` | Active target tools/status bar | Active target state | Preserved by `-Upgrade`. |
| `<workspace>\mpserx-erx\...` | Legacy workspace artifact | Legacy evidence/state from older usage | Preserved by `-Upgrade` for safety. |

Full clean uninstall without `-Upgrade` can remove credentials, workspace
evidence, MCP config entries, managed instruction blocks, and workspace storage.
Use that only when the user explicitly wants a clean slate.

## Upgrade Flow

Routine extension replacement uses upgrade mode:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\clean-uninstall.ps1 `
  -Upgrade `
  -Workspace 'C:\Developer\Workspace\EnterpriseRx\OraFlow','C:\Developer\Workspace\EnterpriseRx\Development\mpserx-erx'
```

Upgrade mode preserves user-owned state:

- `%USERPROFILE%\.oraflow\`,
- workspace `OraFlow/` evidence and outputs,
- workspace `mpserx-erx/` legacy artifacts,
- managed `.vscode/mcp.json`,
- managed `.github/copilot-instructions.md`,
- VS Code workspaceStorage for the selected workspaces.

Upgrade mode still removes extension-managed stale state:

- installed OraFlow/mpserx extension folders,
- VS Code extension index entries,
- editor logs/caches/temp files with OraFlow/mpserx names,
- Copilot temp project-context and project-index caches,
- OraFlow repo build outputs and generated zip files.

After installing the new VSIX and reopening the workspace, extension activation
refreshes any managed `oraflow` MCP entry to the currently installed extension
paths: backend executable, Instant Client, SQL*Plus fallback, TNS files, schema
catalog, instructions, help topics, customers file, and credentials path.

## Native Uninstall Hook (`vscode:uninstall`)

The extension ships a `uninstall.js` at the VSIX root, wired through the
`"vscode:uninstall": "node ./uninstall.js"` script in `package.json`. VS Code
runs it in a bare Node process (no `vscode` API, no workspace context) when the
extension is **fully uninstalled** — not on upgrade/version replacement.

Because the hook has no workspace context, the extension records every workspace
it configures into `%USERPROFILE%\.oraflow\managed-workspaces.json`
(`recordManagedWorkspace`). On uninstall the hook reads that registry and, for
each recorded workspace, undoes only OraFlow-managed edits:

- removes the managed `oraflow` server from `<workspace>\.vscode\mcp.json`
  (detected via `ORAFLOW_MANAGED_BY_EXTENSION=true` or an
  `enterpriserx.oraflow-*` / `oraflow-mcp(.exe)` command path); deletes the file
  and its now-empty `.vscode` dir if nothing else remains,
- strips the `BEGIN/END ORAFLOW AGENT INSTRUCTIONS` block from
  `<workspace>\.github\copilot-instructions.md`; deletes the file and its
  now-empty `.github` dir only if no hand-written content remains,
- deletes the registry file and removes `%USERPROFILE%\.oraflow\` only if it is
  empty.

The hook deliberately preserves user-owned state: hand-written `mcp.json`
servers, hand-written `copilot-instructions.md` content outside the markers, and
credentials (`credentials.toml`, `jira.toml`). It is best-effort — every step is
wrapped so one failure never aborts cleanup of the remaining workspaces — and
strips a leading UTF-8 BOM before JSON parsing for robustness.

`scripts/verify-vsix-internals.ps1` asserts that `uninstall.js` is packaged and
that `package.json` declares the `vscode:uninstall` hook.

## Code Change Impact Checklist

For every code change, answer these before calling the build good:

1. Does this change add a new runtime download, package install, HTTP call,
   file extraction, or cache location? If yes, document the trigger, destination,
   cleanup behavior, and whether it is allowed at runtime.
2. Does this change add or move any file written under `%USERPROFILE%`,
   `%APPDATA%`, `%TEMP%`, `.vscode/`, `.github/`, or workspace `OraFlow/`? If
   yes, update this document and `scripts/clean-uninstall.ps1`.
3. Does this change alter `.vscode/mcp.json`, extension activation, server env
   vars, bundled resource paths, or command IDs? If yes, test upgrade refresh
   from an old managed config.
4. Does this change touch credentials, Jira token handling, SQL output, Jira
   evidence, attachments, logs, or audit files? If yes, verify `-Upgrade`
   preserves user-owned state and full clean uninstall removes it only when
   intended.
5. Does this change add build output, package output, or generated assets? If
   yes, update `scripts/rebuild-vsix.ps1`, `scripts/verify-vsix.ps1`, and
   `scripts/verify-vsix-internals.ps1` as needed.
6. Does this change add bundled dependencies or third-party helpers that can
   download code or check for updates? If yes, either remove/stub that behavior
   or document why it is safe, then add a verifier guard.
7. Does this change affect files inside user repositories other than the active
   workspace `OraFlow/`, `.vscode/mcp.json`, or managed `.github` block? If yes,
   stop and require explicit design review.

Minimum validation after install/upgrade-impacting changes:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\rebuild-vsix.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-vsix.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-vsix-internals.ps1
uv run pytest
uv run ruff check .
```

`scripts/verify-vsix.ps1` also checks that duplicated source, extension, and
packaged VSIX copies stay in sync for TNS files, `sqlnet.ora`, OraFlow
instructions, customer/help assets, and the schema catalog. It also enforces
package-bloat guardrails: no top-level source/cache/temp/debug artifacts in the
VSIX, no optional FastMCP CLI/skill download helpers, and current size ceilings
for the compressed VSIX, uncompressed package, frozen backend, Instant Client,
SQL*Plus fallback, and total packaged file count. If a legitimate runtime change
needs more space, update the ceiling and explain why in the same change.

Also smoke the packaged MCP server with extension-style environment variables
and confirm:

- server starts over stdio,
- tool list loads,
- `oraflow_version` reports the expected version,
- `oraflow_config` reports the active workspace as `workspace_dir`,
- bundled TNS path count is `2`,
- `oracle_home` is `null`,
- no `oraflow-mcp` process remains after the client exits.
