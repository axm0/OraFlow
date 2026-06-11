# OraFlow

OraFlow is a **local, read-only investigation assistant** for EnterpriseRx
developer workflows. It combines safe Oracle evidence capture with read-only
JiraFlow ticket/search evidence. Oracle workflows use existing `tnsnames.ora`
aliases (Toad-style connectivity). It ships as:

- a **FastMCP stdio server** (`oraflow-mcp`) that an MCP-aware editor — VS Code
  Copilot Chat, Claude Desktop, Cursor, Cline — can call as tools,
- a **Typer/Rich CLI** (`oraflow`) for the same operations from a shell,
- a **VS Code extension** (`extensions/vscode/`) that bundles a frozen
  PyInstaller build of the server, ships the schema/DDL catalog, manages
  per-workspace MCP config, and writes credentials under
  `~/.oraflow/credentials.toml`.

The core design rule is **read-only is absolute**: Oracle tools validate every
statement (`SELECT` / `WITH ... SELECT` only), Jira tools only read/search/fetch
attachments, the server pins one active Oracle target per workspace, and every
run/fetch writes to a local evidence trail under `OraFlow/db` and
`OraFlow/jira`. The full safety contract lives in
[`ORAFLOW_INSTRUCTIONS.md`](./ORAFLOW_INSTRUCTIONS.md) — that file is bundled
into the server at build time and surfaced over MCP `initialize` so any agent
talking to OraFlow gets the same rules.

---

## Repo layout

```
OraFlow/
├── src/oraflow/                    # Python package: server, CLI, safety, catalogs, JiraFlow
├── tests/                          # pytest suite + fixtures, including lifecycle cleanup coverage
├── scripts/                        # lifecycle, package verification, diagnostics, schema refresh helpers
│   ├── clean-uninstall.ps1         # full clean / upgrade-safe cleanup
│   ├── rebuild-vsix.ps1            # clean frozen-backend + VSIX rebuild
│   ├── verify-vsix.ps1             # package contents, sync, and bloat guardrails
│   ├── verify-vsix-internals.ps1   # internal runtime/string/source-leak audit
│   ├── refresh_schema_catalog.ps1  # re-split TREXONE dumps into schemas/
│   └── split_ddl_dump.py           # DDL splitter used by the schema refresher
├── extensions/vscode/              # VS Code extension source and packaged runtime inputs
│   ├── assets/                     # bundled instructions, customers, help topics
│   ├── bin/win32-x64/              # frozen MCP backend, Instant Client, SQL*Plus fallback
│   ├── oracle-network/admin/       # packaged TNS/sqlnet copies, verified against root
│   └── schemas/                    # packaged schema copy, verified against root schemas/
├── schemas/                        # source DDL catalog (per-table .sql files)
│   ├── oltp/trexone_data/
│   └── olap/{trexone_aud_data,trexone_dw_data,trexone_ods_data}/
├── trexone_data_dumps/             # raw TREXONE_*_tables.sql dump inputs, ignored after extraction
├── oracle-network/                 # source Oracle Net config for bundled/dev resolution
│   ├── admin/                      # tnsnames.ora, cloud-tnsnames.ora, sqlnet.ora
│   ├── log/                        # runtime output, gitignored except .gitkeep
│   └── trace/                      # runtime output, gitignored except .gitkeep
├── prompts/                        # ERXD/L3 prompts and extension upgrade prompt
├── context/                        # historical planning/scratch only; not runtime-loaded
├── OpsDashboard/                   # environment dashboard snapshots/scratch inputs
├── README.md                       # short doc index
├── ORAFLOW_DOCS.md                 # engineering overview and command reference
├── ORAFLOW_ARCHITECTURE_WALKTHROUGH.md  # speaker-ready architecture notes
├── ORAFLOW_INSTALL_UPGRADE_IMPACT.md    # install/download/write/upgrade contract
├── ORAFLOW_INSTRUCTIONS.md         # safety contract bundled into every build
├── AGENTS.md                       # repo-level future-agent change checklist
├── customers.toml                  # friendly customer/env catalog, bundled
├── tnsnames.ora / cloud-tnsnames.ora # root TNS sources, verified against bundled copies
├── oraflow-mcp.spec                # PyInstaller spec for the frozen server
├── pyproject.toml / uv.lock        # uv-managed Python project
└── package.json                    # optional Bun wrapper scripts
```

> **Heads-up.** `ORAFLOW_INSTRUCTIONS.md`, `customers.toml`, `tnsnames.ora`,
> and `cloud-tnsnames.ora` must stay at the repo root. They're load-bearing
> for both the dev-mode lookups in `src/oraflow/config.py` and the PyInstaller
> data list in `oraflow-mcp.spec`.

Ignored local/tooling state such as `.venv/`, `.pytest_cache/`, `.ruff_cache/`,
`.idea/`, `build/`, `dist/`, `extensions/vscode/node_modules/`, and workspace
`OraFlow/` evidence folders is not part of the repository architecture.

---

## Setup

```powershell
cd C:\Developer\Workspace\EnterpriseRx\OraFlow
uv sync
```

Optional Bun wrappers (`package.json` exposes `setup`, `mcp`, `tns`, `test`,
`lint`, `check`):

```powershell
bun run setup
```

Copy `.env.example` to `.env` if you want explicit local overrides:

```powershell
Copy-Item .env.example .env
```

### Oracle runtime

OraFlow does not discover or depend on a machine-level Oracle install. Source
mode can use python-oracledb thin mode for development, and the packaged VS Code
extension bundles a frozen MCP backend plus Windows Oracle runtime bits under
`extensions/vscode/bin/`:

- Instant Client 23.x for the normal python-oracledb path.
- SQL\*Plus 12.2 fallback for on-prem PROD aliases with legacy password
  verifier/authentication behavior.

The repo also carries the Oracle Net configuration needed to resolve aliases
under `oracle-network/admin/` and `extensions/vscode/oracle-network/admin/`.
The packaged VS Code extension does not inspect or depend on a machine-level
Oracle install. Its managed MCP config points only at bundled extension assets:
the frozen backend, bundled Instant Client, bundled TNS files, bundled schema
catalog, bundled instructions, and bundled SQL*Plus 12.2 fallback.

### TNS resolution chain

`src/oraflow/config.py :: resolve_tnsnames_path()` checks, in order:

1. `ORAFLOW_TNSNAMES_PATHS` (extension-style semicolon-delimited explicit files)
2. `ORAFLOW_TNSNAMES_PATH` (single explicit file)
3. `ORAFLOW_TNS_ADMIN\tnsnames.ora`
4. repo/bundled `oracle-network\admin\tnsnames.ora`
5. workspace-local `tnsnames.ora` (root fallback)

`resolve_tnsnames_paths()` builds the same explicit/bundled ladder for
**multi-file** loading and additionally pulls in `cloud-tnsnames.ora` from each
candidate directory. It intentionally does not search process `TNS_ADMIN`,
`ORACLE_HOME`, or `PATH`.

---

## MCP server

Run over stdio:

```powershell
uv run oraflow-mcp
# or:
bun run mcp
```

Example MCP client config (`mcpServers` for some clients, `servers` for VS
Code-style configs):

```json
{
  "mcpServers": {
    "oraflow": {
      "type": "stdio",
      "command": "uv",
      "args": ["--directory", "C:\\Developer\\Workspace\\EnterpriseRx\\OraFlow", "run", "oraflow-mcp"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
    }
  }
}
```

For end users we recommend the **VS Code extension** in `extensions/vscode/`
instead — it bundles a frozen `oraflow-mcp.exe`, configures the server per
workspace, manages credentials, and writes the agent-instructions block into
`.github/copilot-instructions.md`.

### Tools currently exposed by the server

Defined in `src/oraflow/server.py`. Categories follow a risk-based workflow:
discover freely, resolve target precisely, validate every SQL statement, and
use script artifacts for investigations and PROD SQL.

**[meta]**
- `oraflow_config` — effective config + canonical `next_steps` checklist.
- `oraflow_version` — version + attribution metadata.
- `oraflow_help(topic)` — read a help topic (`safety`, `workflow`, `schemas`, …).
- `oraflow_help_topics` — list available topics.

**[discovery]**
- `tns_info` — summary of the loaded TNS catalog.
- `schema_catalog_info` — summary of the bundled DDL catalog.
- `credentials_doctor` — diagnose credential profiles without exposing passwords.
- `list_customers` — friendly customer catalog from `customers.toml`.

**[target]**
- `resolve_target(text_or_customer, env, layer, deployment)` — resolve to TNS alias + profile.
- `set_active_target(text_or_customer, env, layer, deployment)` / `get_active_target` / `clear_active_target`.
- `ping_active_target()` — ping the pinned active target using its stored alias/profile.

> `deployment` is `"cloud"` or `"onprem"` and is honored as a hard constraint.
> Free-text aliases the parser understands: `cloud` / `oci` collapse to
> `cloud`; `onprem` / `on-prem` / `onpremise` collapse to `onprem`. So
> `set_active_target("dev46 cloud")` deterministically resolves against
> `cloud-tnsnames.ora` and refuses to bind to an on-prem alias of the same
> substring.
>
> Target resolution should be treated as **filter, then ask**: deployment,
> environment, customer/name, site number, and schema/layer words narrow the
> TNS candidate list. If exactly one safe candidate remains, use it. If
> multiple remain, list the aliases and ask the user to choose; never silently
> pick between cloud/onprem, QA/DEV, TX/DW, or PROD/non-PROD. `DW`,
> `warehouse`, and `data warehouse` mean `TREXONE_DW_DATA`; `TX`,
> `transactional`, `non-DW`, `oltp`, and `data` mean `TREXONE_DATA`.

**[discovery]** (continued)
- `search_tns(query, deployment=...)` — same TNS catalog search, with an
  optional `deployment` filter that restricts results to entries whose
  `source_tag` matches (`cloud-tnsnames.ora` vs `tnsnames.ora`).
- `oraflow_search_siblings(alias_or_key, include_self=false)` — return alternate
  TNS endpoints that share customer + environment + host group + deployment
  source. This is a discovery/safety surface for multi-endpoint PROD customers
  (for example `TXKINP01-55` and `TXKINP01-67`). OraFlow never auto-fails over;
  the agent surfaces siblings and the human chooses the next endpoint.

**[schema]** (DB-free, runs against bundled DDL)
- `search_schema` — fuzzy search by table/column text.
- `list_schema_tables` — filter by layer/schema/pattern.
- `describe_schema_table` — columns, PK, FKs from local DDL.
- `find_schema_columns` — substring search across columns.

**[script]**
- `author_sql_script` — write a SELECT-only script under `OraFlow/db/scripts/<ticket-or-ad_hoc>/`.
- `list_sql_scripts` — list authored scripts.
- `read_script_results` — read the structured JSON sidecar; source of truth for investigation rows.
- `read_script_output` — read the human-readable companion text output.

**[execute]**
- `run_active_target_script` — run a previously authored script against the
  active target, write JSON/text output, and append a row to `OraFlow/db/_audit/runs.jsonl`.
- `run_sql_script` — run a previously authored script against an explicit alias/profile
  or the active target when alias/profile are omitted. Successful
  rows include `status="ok"`; failed runs include `status="failed"`,
  `error_class`, `error_message`, optional `debug_log_path`, and
  `sibling_aliases` so failures are part of the audit trail too.

ERXD, L3, PROD, and evidence-worthy investigations must use script artifacts:
`author_sql_script` -> `run_active_target_script` / `run_sql_script` ->
`read_script_results`. The session/inline tools (`connect`, `run_query`,
`run_query_once`, live `list_tables`, live `describe_table`, live `list_views`)
are advanced non-PROD helpers and are not the investigation path.
If schema catalog tools are not visible in a chat surface, do not substitute
live/session schema tools with placeholder session IDs. Use repository DDL/source
files as the fallback or stop and report that the schema tool group is missing.
Final investigation reports should check `OraFlow/db/_audit/runs.jsonl` and
include both successful and failed script rows in provenance.

Runtime behavior notes:

- Default `query_timeout_s` is 240 seconds. This is an upper bound only; fast
  queries return as soon as they finish.
- SQL\*Plus watchdog timeouts raise `OraflowTimeoutError` and persist redacted
  partial output under `OraFlow/db/logs/sqlplus/sqlplus_*_timeout.log` when available.
- Text output emits a loud `!! WARNING` when a statement consumes more than 80%
  of its configured timeout; narrow the query instead of shipping a fragile
  near-timeout probe.
- `ping_db` / `ping_active_target` failure responses include `siblings` when the target has matching
  alternate endpoints. If identity fields look like column headers (for example
  `DATABASE_NAME`), stop and re-resolve before any PROD reads.

**[jira]** (Atlassian Cloud read-only)
- `jira_get_ticket(key, fetch_attachments=false, max_bytes_per_file, max_bytes_total)` —
  fetch an ERXD-style ticket and write full evidence to
  `OraFlow/jira/<KEY>/`: `issue.json` (REST v3 with `changelog`+`renderedFields`+`names`),
  `comments.json` (all comments, paginated), `summary.md` (human-readable
  digest including description and comment bodies flattened from ADF), and
  attachment metadata. Attachment files are downloaded only when
  `fetch_attachments=true` or via `jira_download_attachment`. JSON-only pipeline — the
  classic XML export is intentionally not fetched (JSON uses ~40% fewer
  tokens for an LLM and has native named fields and arrays for
  comments/changelog). Attachment caps when explicitly enabled: 300 MB per
  file, 1 GB per ticket.
- `jira_list_related_tickets(key)` — inspect an already fetched ticket and write
  `related_index.json` + `related_summary.md` containing formal Jira issue
  links, parent/subtasks, text references in comments/description, and suggested
  JQL searches.
- `jira_fetch_related_tickets(parent_key, related_keys=None, fetch_attachments=false, max_depth=1, max_tickets=10)` —
  fetch selected/direct related tickets under
  `OraFlow/jira/<PARENT>/related/<KEY>/`. Expansion is intentionally bounded;
  OraFlow does not recursively crawl arbitrary Jira trees or download related
  attachments unless explicitly requested.
- `jira_find_similar_tickets(key, max_results=20, include_terms=None)` — derive
  conservative search terms (customer/NPI/Rx/error text/labels/components), run
  JQL searches, and write `similar_tickets.json`. It lists candidates only; use
  `jira_fetch_related_tickets` with selected keys to fetch evidence/attachments.
- `jira_jql_help(topic="l3")` — local JQL syntax/escaping guidance and safe L3
  search patterns. Topics: `overview`, `l3`, `examples`, `escaping`, `fields`,
  `hierarchy` (Initiative/Epic/parent-child JQL), and `process` (Story/Task/Bug,
  workflow status, blocked flag, QA-discovered bug semantics), and
  `ticket_quality` (ticket type decision guide, Bug evidence expectations,
  DoR/DoD, priorities, splitting patterns, and link/dependency semantics).
  `creation` remains a backward-compatible alias for `ticket_quality`; JiraFlow
  stays read-only and does not create/modify Jira tickets by API.
- `jira_search(jql, max_results, start_at)` — POST-based JQL search returning
  issue keys + requested fields only.
- `jira_download_attachment(key, filename_or_id, max_bytes)` — explicit
  on-demand attachment fetch for files skipped by a cap or added after the
  initial fetch.
- `jira_credentials_doctor` — diagnose `~/.oraflow/jira.toml` without
  exposing the API token.

> Jira credentials live in `~/.oraflow/jira.toml` (separate from
> Oracle `credentials.toml`). Required keys: `base_url`, `email`, `api_token`.
> Generate a token at https://id.atlassian.com/manage-profile/security/api-tokens.
> All Jira calls are read-only; the token is redacted from every log,
> error message, and audit row.

> Simple non-PROD one-statement SELECTs may run inline after validation.
> Multi-statement scripts, investigations, and PROD SQL should produce evidence
> artifacts under `OraFlow/db/scripts` + `OraFlow/db/outputs`. For PROD SQL, confirm the
> exact alias/profile/deployment once per investigation, then proceed with
> validated read-only follow-ups unless target or scope changes. See
> `ORAFLOW_INSTRUCTIONS.md` for the full policy.

---

## CLI quick reference

```powershell
uv run oraflow config                                 # detected config
uv run oraflow tns info                               # summarize loaded aliases
uv run oraflow tns search "mayo prod" --limit 10
uv run oraflow tns describe ALIAS_OR_KEY
uv run oraflow creds list                             # profile names, no passwords
uv run oraflow sql check "select * from dual"         # static safety check
uv run oraflow db ping ALIAS_OR_KEY --user YOUR_USER
uv run oraflow db ping 19CDB --profile CLOUD.DEV --tnsnames .\cloud-tnsnames.ora
uv run oraflow db query ALIAS_OR_KEY "select * from dual" --user YOUR_USER --max-rows 10
uv run oraflow db tables ALIAS_OR_KEY --user YOUR_USER --owner YOUR_SCHEMA --limit 25
uv run oraflow db views  ALIAS_OR_KEY --user YOUR_USER --owner YOUR_SCHEMA --limit 25
uv run oraflow db describe ALIAS_OR_KEY YOUR_SCHEMA YOUR_TABLE --user YOUR_USER
```

---

## Build the standalone server (PyInstaller)

The VS Code extension bundles a frozen build of the MCP server. Reproduce it
with:

```powershell
uv run pyinstaller .\oraflow-mcp.spec --clean --noconfirm
```

Outputs go to `dist\oraflow-mcp\`. The spec ships
`ORAFLOW_INSTRUCTIONS.md`, `customers.toml`, and the extension's
`help-topics.toml` inside the bundle so the frozen executable can resolve them
via `sys._MEIPASS` (see `bundle_root()` / `find_bundled_resource()` in
`src/oraflow/config.py`).

## Clean rebuild the VS Code extension

`ORAFLOW_INSTALL_UPGRADE_IMPACT.md` is the source of truth for what OraFlow
downloads, writes, preserves, and cleans. Review its change checklist before
changing rebuild, install, upgrade, resource path, MCP config, download, or
file-write behavior.

Use the wrapper script when you want a fresh VSIX with the current source and
bundled backend, without changing the extension version:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\rebuild-vsix.ps1
```

The script rebuilds `oraflow-mcp.exe`, replaces the bundled backend, packages
`extensions/vscode/oraflow-<version>.vsix`, and cleans transient repo outputs by
default. It does not edit `package.json` or `pyproject.toml` versions. See
`ORAFLOW_INSTALL_UPGRADE_IMPACT.md` for the full output/download/cache contract.

## Clean upgrade checklist

Every code change that touches extension activation, cleanup, resource paths,
MCP config, credentials, Jira attachments, DB/Jira evidence, or build/package
output must be checked against `ORAFLOW_INSTALL_UPGRADE_IMPACT.md` before it is
considered ready.

Use this when replacing an installed OraFlow VSIX, especially on a machine that
has used OraFlow from `mpserx-erx`:

```powershell
# 1. Close VS Code first so extension logs/storage are not locked.

# 2. Remove old installed extension/cache/build state while preserving
#    user-owned upgrade state. See ORAFLOW_INSTALL_UPGRADE_IMPACT.md.
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\clean-uninstall.ps1 `
  -Upgrade `
  -Workspace 'C:\Developer\Workspace\EnterpriseRx\OraFlow','C:\Developer\Workspace\EnterpriseRx\Development\mpserx-erx'

# 3. Rebuild a fresh package. The script wipes stale bundled backend files
#    before copying the newly frozen backend.
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\rebuild-vsix.ps1

# 4. Verify the package before installing.
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-vsix.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-vsix-internals.ps1
```

The VSIX verifier fails on accidental package bloat: source folders, cache/temp
files, debug artifacts, stale VSIX/zip outputs, optional FastMCP download
helpers, or package size jumps beyond the documented ceilings.

Extension activation refreshes managed `.vscode/mcp.json` and the managed
`.github/copilot-instructions.md` block after upgrade. The managed config is
bundled-only. Do not use full-clean deletion for routine upgrades unless the
goal is to discard local credentials, evidence/output folders, MCP config,
workspace storage, and managed instructions.

## Clean uninstall / workspace cleanup

Use `scripts/clean-uninstall.ps1` to wipe old OraFlow extension state before a
fresh install. Close VS Code first so workspace storage databases are not
locked. For routine upgrades, use `-Upgrade`; see
`ORAFLOW_INSTALL_UPGRADE_IMPACT.md` for the exact preserve/remove contract.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\clean-uninstall.ps1 `
  -Workspace 'C:\Developer\Workspace\EnterpriseRx\Development\mpserx-erx'
```

Use `-KeepCredentials`, `-KeepWorkspaceData`, `-KeepMcpConfig`,
`-KeepCopilotInstructions`, or `-KeepWorkspaceStorage` separately when you need
one specific preservation behavior. Use `-KeepDevArtifacts` only when you
intentionally want to keep local OraFlow build outputs. Re-run the script after
closing VS Code if it reports a locked log file.

---

## Refreshing the bundled schema catalog

The DDL catalog under `schemas/` is what powers the `[schema]` MCP tools (no
DB connection required). To refresh it after pulling new dumps into
`trexone_data_dumps/`:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\refresh_schema_catalog.ps1
```

Layer mapping handled by the script:

| Schema             | Layer  | Folder                                  |
| ------------------ | ------ | --------------------------------------- |
| `TREXONE_DATA`     | `oltp` | `schemas/oltp/trexone_data/`            |
| `TREXONE_ODS_DATA` | `olap` | `schemas/olap/trexone_ods_data/`        |
| `TREXONE_AUD_DATA` | `olap` | `schemas/olap/trexone_aud_data/`        |
| `TREXONE_DW_DATA`  | `olap` | `schemas/olap/trexone_dw_data/`         |

---

## Test and lint

```powershell
uv run pytest
uv run ruff check .

# or with Bun:
bun run check
```

### Testing strategy

OraFlow has two execution paths and both are covered by tests:

- **Cloud / modern path**: `ConnectionManager.run_query` uses python-oracledb.
  Tests assert `SET TRANSACTION READ ONLY`, rollback-before-read-only,
  `call_timeout`, `fetchmany(max_rows + 1)` truncation detection, native Oracle
  type normalization (`Decimal`, `datetime`, `bytes`), and pre-execution SQL
  safety validation.
- **On-prem PROD / legacy path**: `_run_sqlplus_csv` uses bundled SQL\*Plus 12.2.
  Tests assert sentinel-framed CSV parsing, NUMBER-first rows, full-precision
  large IDs, CLOB/long audit text, UTF-8, NULL fields, TIMESTAMP WITH TIME ZONE,
  multiline quoted values, password redaction, missing-sentinel failures,
  structured timeout diagnostics, and truncation detection.
- **Jira path**: `oraflow.jira` uses Atlassian Cloud REST v3 over `httpx`,
  flattens ADF bodies for summaries, captures attachment metadata by default,
  streams attachment files only when explicitly requested with size caps, and
  writes evidence under `OraFlow/jira/<KEY>/`. Jira HTTPS uses the OS trust
  store so enterprise TLS roots are honored for attachment downloads. Tests use
  `httpx.MockTransport` and do not connect to Atlassian.

Key test files:

| File | Purpose |
| --- | --- |
| `tests/test_safety.py` + `tests/test_safety_extended.py` | SELECT/WITH allowlist and DML/DDL/admin/package/schema denylist coverage. |
| `tests/test_sqlfile.py` | Script splitter: semicolons in strings, Oracle q-quotes, comments, SQL\*Plus directives, inline `; -- comment`. |
| `tests/test_sqlplus_csv.py` | Pure SQL\*Plus CSV parser behavior. |
| `tests/test_pipeline.py` | Mocked end-to-end SQL\*Plus path: parser, splitter, validator, formatter. |
| `tests/test_db_unit.py` | python-oracledb path and DB helper/routing behavior. |
| `tests/test_tns.py` / `tests/test_customer_target.py` | TNS catalog, deployment filtering, and customer/target resolution. |
| `tests/test_jira.py` | Jira credentials, REST client, ADF flattening, attachment caps, and evidence writer. |
| `tests/test_v015_release.py` | Backend regressions: sibling grouping, structured timeout fields, failed-run audit rows, near-timeout warnings, and sibling MCP tool wiring. |

These are **local automated tests**. They do not connect to live Oracle
instances such as `txndcd46` or `QA11.ZDWNDCQ11`. After rebuilding the packaged
backend, run a live smoke test from Copilot/OraFlow as a separate operational
check: ping the target, run `SELECT 1 AS one FROM dual`, run a tiny multi-query
script, and verify write statements are rejected before execution.

---

## VS Code extension

See [`extensions/vscode/README.md`](./extensions/vscode/README.md) for the
end-user install + workspace-config flow. The extension:

- ships a frozen `oraflow-mcp.exe` and the `_internal/` runtime under
  `extensions/vscode/bin/`,
- writes per-workspace MCP config and an agent-instructions block,
- bundles the schema catalog, customer catalog, and help topics under
  `extensions/vscode/assets/`.

---

## Where things live (cheat sheet)

| Need to… | Look at |
| --- | --- |
| Understand the safety contract | [`ORAFLOW_INSTRUCTIONS.md`](./ORAFLOW_INSTRUCTIONS.md) |
| Understand path resolution | `src/oraflow/config.py` |
| Add or change an MCP tool | `src/oraflow/server.py` |
| Tighten SQL safety | `src/oraflow/safety.py` + `tests/test_safety.py` |
| Refresh the schema catalog | `scripts/refresh_schema_catalog.ps1` |
| Clean rebuild the VSIX | `scripts/rebuild-vsix.ps1` |
| Clean uninstall / workspace cleanup | `scripts/clean-uninstall.ps1` |
| Verify packaged VSIX contents | `scripts/verify-vsix.ps1` + `scripts/verify-vsix-internals.ps1` |
| Run the quick L3 triage prompt | [`prompts/ERXD_L3_TRIAGE.md`](./prompts/ERXD_L3_TRIAGE.md) |
| Run the L3 prompt | [`prompts/ERXD_L3_INVESTIGATION.md`](./prompts/ERXD_L3_INVESTIGATION.md) |
| Read planning notes / history | [`context/README.md`](./context/README.md) |
| Build the frozen server | `oraflow-mcp.spec` |
| Ship to teammates | `extensions/vscode/` |

---

## License

MIT — see [`extensions/vscode/LICENSE.txt`](./extensions/vscode/LICENSE.txt)
for the extension's bundled license file. The Python project metadata is
declared in `pyproject.toml`.
