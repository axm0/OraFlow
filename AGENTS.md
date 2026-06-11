# OraFlow Agent Instructions

Before making or accepting any code, build, package, cleanup, extension, MCP,
credential, Jira, database evidence, or documentation change, review
`ORAFLOW_INSTALL_UPGRADE_IMPACT.md`.

Every change must explicitly consider whether it affects:

- runtime downloads or network calls,
- build-time package downloads or caches,
- `%USERPROFILE%`, `%APPDATA%`, `%TEMP%`, `.vscode/`, `.github/`, or workspace
  `OraFlow/` writes,
- extension activation and managed `.vscode/mcp.json` refresh,
- bundled backend, Instant Client, SQL*Plus, TNS, schema, help, customer, or
  instruction paths,
- credentials, Jira evidence, Jira attachments, DB scripts, DB outputs, logs,
  audit files, or active-target state,
- clean uninstall and upgrade preservation behavior,
- rebuild, VSIX contents, verifier scripts, or package bloat.

If a change adds or moves any download, cache, generated output, user file,
workspace file, cleanup target, or verifier expectation, update
`ORAFLOW_INSTALL_UPGRADE_IMPACT.md`, the relevant docs, and the cleanup/rebuild
verifier scripts in the same change.

For routine validation after install/upgrade-impacting changes, run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\rebuild-vsix.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-vsix.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-vsix-internals.ps1
uv run pytest
uv run ruff check .
```

Also smoke the packaged MCP server with extension-style environment variables
and confirm it starts over stdio, lists tools, reports the expected OraFlow
version, uses bundled TNS paths, reports `oracle_home` as `null`, and leaves no
`oraflow-mcp` process behind.