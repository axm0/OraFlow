# OraFlow Architecture Walkthrough

This document is written as a speaker-ready architecture breakdown. You can read the main walkthrough verbatim, then use the later sections as backup detail for questions.

## Short Version

OraFlow is a local, read-only investigation assistant for EnterpriseRx. It gives Copilot a controlled tool layer for Oracle database evidence, schema discovery, target selection, and Jira ticket evidence. The important point is that OraFlow is not a general database chat bot. It is a safety-first evidence system.

The VS Code extension installs and configures a local MCP server. That server runs on stdio, not as a web service. It exposes tools for discovery, target binding, schema lookup, script authoring, script execution, Jira fetches, and audit review. Oracle reads are validated as SELECT-only, run with read-only transaction behavior, and written to local script, text, JSON, and audit artifacts under the workspace `OraFlow/` folder. Jira fetches are also read-only and write durable evidence under `OraFlow/jira/`.

The design goal is simple: make L3 investigations reproducible, auditable, and safe enough for customer and PROD evidence, while keeping credentials and outputs local.

## Verbatim Walkthrough

I am going to walk through OraFlow from the outside in: what problem it solves, how it is packaged, how the extension starts it, how the MCP server is structured, how database evidence is captured, how Jira evidence is captured, and how the safety model is enforced.

OraFlow exists because an EnterpriseRx L3 investigation usually needs several things at the same time. We need the Jira ticket, comments, attachment metadata or selected attachment files, related issues, schema knowledge, customer environment resolution, database evidence, and a clean audit trail of what was actually queried. Without a tool layer, an agent can easily do the wrong thing: guess a schema column, run an inline query that leaves no artifact, pick the wrong database alias, or mix up PROD and QA. OraFlow is built to prevent that.

At a high level, OraFlow has three layers. The first layer is the VS Code extension. That is the user-facing installer and setup experience. It bundles the backend executable, Oracle network files, schema catalog, instructions, help topics, customer catalog, Instant Client, and SQL*Plus fallback runtime. It also creates credential templates and writes the workspace MCP config. The second layer is the Python MCP server, `oraflow-mcp`. That is the real tool surface Copilot calls. It exposes metadata, discovery, target, schema, script, execution, and Jira tools. The third layer is the local evidence workspace. That is the `OraFlow/` folder inside the current repository, where database scripts, outputs, JSON sidecars, SQL run audit rows, Jira issue JSON, comments, attachment metadata or selected attachment files, summaries, and related-ticket evidence are written.

The extension is intentionally small. It does not implement database logic itself. Its job is to install and configure the local server in a predictable way. When the user runs `OraFlow: Configure MCP for Workspace`, the extension writes `.vscode/mcp.json` with a single stdio MCP server named `oraflow`. The command points to the bundled `oraflow-mcp.exe`. The environment points the backend to the bundled TNS files, schema catalog, instructions file, customer catalog, help topics, credential path, workspace path, SQL*Plus 12.2 fallback home, and clean Oracle network settings. That means the same server behavior is available in each workspace without asking the user to hand-build MCP config.

Credentials are deliberately outside the workspace. Database credentials live in `~/.oraflow/credentials.toml`, and Jira credentials live in `~/.oraflow/jira.toml`. The extension can create both templates and tries to restrict file permissions. The MCP config never contains passwords. It contains paths and environment variables only. That separation matters because workspace config may be shared or committed by accident, while credentials should remain local to the user profile.

Once the MCP server starts, it loads the same safety contract every time. The main safety text is `ORAFLOW_INSTRUCTIONS.md`, and it is bundled into the server at build time. The extension also writes managed Copilot agent instructions into `.github/copilot-instructions.md` so the agent sees the OraFlow workflow even before or outside a specific MCP tool call. This gives us two layers of guidance: instructions sent through MCP initialization and persistent workspace guidance for Copilot Agent mode.

The server exposes tools by risk category. Metadata and discovery tools are low risk: `oraflow_config`, `oraflow_help`, `tns_info`, `schema_catalog_info`, `credentials_doctor`, and `list_customers`. Target tools are more sensitive: `resolve_target`, `set_active_target`, `get_active_target`, `clear_active_target`, and `ping_active_target`. Schema tools are database-free: `search_schema`, `list_schema_tables`, `describe_schema_table`, and `find_schema_columns` operate against the bundled DDL catalog rather than a live database. Script and execution tools are the evidence path: `author_sql_script`, `run_active_target_script`, `run_sql_script`, and `read_script_results`. Jira tools are read-only evidence tools: fetch the ticket, list related tickets, fetch selected related tickets, search similar tickets, and provide JQL help.

The most important workflow concept is active target binding. OraFlow does not want an agent casually typing an alias in each query. Instead, the agent resolves the intended customer, environment, deployment, and schema layer, then pins that target into `OraFlow/session.json`. After that, `ping_active_target` verifies database identity before any reads. For PROD, this is critical. If there are sibling endpoints, OraFlow surfaces them and asks the human to choose; it does not silently fail over. If the ping response looks suspicious, such as identity fields coming back as literal header names like `DATABASE_NAME`, OraFlow tells the agent to stop and re-resolve before reading.

The second important workflow concept is script artifacts. For ERXD, L3, PROD, and evidence-worthy investigations, OraFlow does not use inline `run_query` as the main path. Instead, the agent authors a SQL script with `author_sql_script`. That writes a SELECT-only `.sql` file under `OraFlow/db/scripts/<ticket-or-ad_hoc>/`. Then the agent executes that existing script using `run_active_target_script` or, only when explicitly needed, `run_sql_script` with an alias/profile. Execution writes a human-readable text output file, a structured JSON output sidecar, and an audit row in `OraFlow/db/_audit/runs.jsonl`. The JSON sidecar is the source of truth for rows.

This artifact pattern solves several investigation problems. First, it preserves the exact SQL that was run. Second, it preserves the exact target and user profile used. Third, it preserves both successful and failed attempts. Fourth, it gives the agent structured output instead of relying on copied table text from chat. Fifth, it gives the L3 report a provenance trail: the report can point to the script, the output JSON, and the audit row.

The SQL safety layer is strict. OraFlow validates SQL with a parser and denylist before execution. Only `SELECT` and `WITH` read-only statements are allowed. It blocks DML, DDL, PL/SQL, transaction control, `FOR UPDATE`, `SELECT INTO`, blocked package references like `DBMS_` and `UTL_`, and direct `SYS` or `SYSTEM` references. On execution, Oracle reads are wrapped in read-only transaction behavior. So the design is not just "please be careful". The backend enforces the read-only boundary.

There are two Oracle execution paths. The normal packaged-extension path uses python-oracledb thick mode with the bundled Instant Client and bundled Oracle Net files. OraFlow does not hunt for a machine-level Oracle client. For legacy on-prem PROD aliases that have older authentication behavior, OraFlow can fall back to the bundled SQL*Plus 12.2 runtime. That fallback is still controlled by the same script artifact and audit workflow. It uses CSV framing, random sentinels, redacted debug logs, timeout handling, and writes results back into the same JSON/text evidence format.

Schema discovery is intentionally separate from live database sessions. OraFlow ships a bundled DDL catalog under `schemas/`, split by schema family: `TREXONE_DATA`, `TREXONE_AUD_DATA`, `TREXONE_DW_DATA`, and `TREXONE_ODS_DATA`. The schema catalog tools read that local DDL and expose table lookup, fuzzy search, and column search. This keeps schema discovery fast and safe, and it prevents the agent from opening a live database session just to ask whether a column exists. If the schema tool group is not visible in a chat surface, the instructions explicitly tell the agent not to fake it with live `describe_table` calls or placeholder session IDs.

JiraFlow follows the same evidence principle as the database side. When the agent calls `jira_get_ticket`, OraFlow retrieves the issue JSON, comments, attachment metadata, and a human-readable summary. Attachment files are downloaded only when explicitly requested, and then they respect size caps. It writes evidence under `OraFlow/jira/<KEY>/`. Related-ticket tools create `related_index.json`, `related_summary.md`, nested related-ticket evidence folders when selected, and similar-ticket search results when needed. Jira operations are read-only. They do not comment, edit, transition, upload, or change tickets.

The L3 investigation prompts sit on top of these mechanics. A full L3 prompt tells the agent to start with the ERXD key, fetch Jira first, classify the ticket, decide which evidence lanes are needed, and only bind a customer PROD database if DB evidence is actually needed. The shorter triage prompt does the same thing at a lighter level: fetch Jira, classify the case, and recommend whether the next step is process response, code/docs review, DB evidence, app-option/config evidence, Splunk/app logs, server logs, batch logs, integration evidence, or the full L3 investigation.

The local file layout is part of the architecture. `OraFlow/db/scripts/` contains authored SQL. `OraFlow/db/outputs/` contains text and JSON outputs. `OraFlow/db/_audit/runs.jsonl` contains the append-only SQL run log. `OraFlow/db/logs/sqlplus/` contains redacted fallback diagnostic logs when needed. `OraFlow/jira/<KEY>/` contains Jira issue, comments, summary, attachments, related indexes, and similar-ticket output. That means the evidence stays local to the user's workspace, but it is organized enough for repeatable review.

From a build and distribution perspective, the Python project is packaged with PyInstaller using `oraflow-mcp.spec`. The VS Code extension bundles that frozen backend under `extensions/vscode/bin/win32-x64/oraflow-mcp`, plus Instant Client, SQL*Plus 12.2 fallback, Oracle network config, schema catalog, and assets. The extension manifest is versioned independently as the VSIX version. The current rebuilt extension is version `0.1.2`. The rebuild script removes generated outputs, rebuilds the frozen backend, refreshes the bundled backend, builds the extension JavaScript with esbuild, and packages the VSIX. Verification scripts then inspect the VSIX for required files, source/package asset sync, internal environment strings, clean sqlnet configuration, package-bloat ceilings, optional download helpers, required assets, schema files, and obvious source or secret leakage.

If I had to summarize the architecture in one sentence, I would say this: OraFlow is a local, read-only MCP evidence layer that turns Copilot from a free-form assistant into a controlled EnterpriseRx investigation workflow, with pinned targets, schema-aware SQL, durable JSON evidence, Jira evidence capture, and auditability built into the tool path.

## Architecture Map

```text
User in VS Code / Copilot Agent mode
        |
        | Command Palette setup and MCP tool calls
        v
OraFlow VS Code extension
        |
        | writes .vscode/mcp.json and managed agent instructions
        | sets ORAFLOW_* environment variables
        v
Local FastMCP stdio server: oraflow-mcp
        |
        +-- Metadata/help tools
        +-- TNS/customer/target tools
        +-- DB-free schema catalog tools
        +-- SQL script authoring tools
        +-- Oracle execution tools
        +-- Jira read-only evidence tools
        |
        v
Local evidence workspace: <repo>/OraFlow/
        |
        +-- db/scripts/<ticket-or-ad_hoc>/*.sql
        +-- db/outputs/<ticket-or-ad_hoc>/*_output.txt
        +-- db/outputs/<ticket-or-ad_hoc>/*_output.json
        +-- db/_audit/runs.jsonl
        +-- db/logs/sqlplus/*.log
        +-- jira/<KEY>/issue.json, comments.json, summary.md, attachments/
        +-- jira/<KEY>/related_index.json, related_summary.md, similar_tickets.json
```

## Component Breakdown

### VS Code Extension

The extension lives under `extensions/vscode/`. It contributes four main command palette commands:

- `OraFlow: Setup Credentials`
- `OraFlow: Setup Jira Credentials`
- `OraFlow: Configure MCP for Workspace`
- `OraFlow: Show Bundled Backend Path`

The extension is responsible for user setup, not database execution. Its important responsibilities are:

- Locate the bundled `oraflow-mcp.exe` backend.
- Create/open `~/.oraflow/credentials.toml`.
- Create/open `~/.oraflow/jira.toml`.
- Harden credential file permissions on a best-effort basis.
- Write `.vscode/mcp.json` with the `oraflow` stdio server.
- Set environment variables for TNS files, schema catalog, instructions, customer catalog, help topics, credential path, workspace path, SQL*Plus fallback, and Oracle client config.
- Write managed Copilot agent instructions into `.github/copilot-instructions.md`.
- Show a status bar target summary.

### Packaging and Lifecycle Guardrails

The install and upgrade contract lives in `ORAFLOW_INSTALL_UPGRADE_IMPACT.md`. That file is the source of truth for what OraFlow downloads, writes, preserves, and cleans.

The packaged extension is intentionally bundled-only at runtime. It does not download backend code, Oracle clients, Python packages, npm packages, schema files, or FastMCP skills after installation. Runtime network activity is tool-driven: Oracle connections when DB tools are called, Jira HTTPS when Jira tools are called, and Jira attachment file downloads only when explicitly requested.

Routine upgrades use `scripts/clean-uninstall.ps1 -Upgrade`. That removes installed extension folders, editor caches/logs/temp files, stale extension index entries, and repo build outputs while preserving user-owned credentials, workspace evidence, managed MCP config, managed Copilot instructions, and VS Code workspace storage. Full clean uninstall is separate and should only be used when the goal is to discard local OraFlow state.

`scripts/verify-vsix.ps1` and `scripts/verify-vsix-internals.ps1` guard the package before install. They check source/package asset sync, required runtime files, extension environment strings, SQL*Plus trim state, FastMCP optional download helpers, source/secrets leakage, and package-bloat ceilings for the compressed VSIX, uncompressed package, frozen backend, Instant Client, SQL*Plus fallback, and total packaged file count.

### MCP Server

The MCP server is the Python FastMCP application in `src/oraflow/server.py`. It is the tool boundary. Copilot does not directly access Oracle or Jira; it calls OraFlow tools.

The server loads:

- Project metadata from `oraflow.__version__`, currently aligned with `0.1.2` packaging.
- Instructions from `ORAFLOW_INSTRUCTIONS.md` using bundled resource lookup.
- TNS catalog and customer catalog for target discovery.
- Credential profiles from TOML.
- Schema catalog from bundled DDL.
- Jira credentials and Jira client wrappers.

The server organizes tools by risk:

- Metadata and help are safe to call freely.
- TNS and customer discovery are safe metadata operations.
- Target binding is a deliberate step and persists the active target.
- Schema lookup uses bundled DDL, not live DB sessions.
- Script authoring validates SQL before writing an artifact.
- Script execution writes text, JSON, and audit artifacts.
- Jira tools fetch evidence only.

### Workspace Evidence Layer

The evidence layer is implemented in `src/oraflow/workspace.py` and `src/oraflow/jira/evidence.py`.

Database evidence layout:

```text
OraFlow/db/scripts/<ticket-or-ad_hoc>/<script>.sql
OraFlow/db/outputs/<ticket-or-ad_hoc>/<script>_output.txt
OraFlow/db/outputs/<ticket-or-ad_hoc>/<script>_output.json
OraFlow/db/_audit/runs.jsonl
OraFlow/db/logs/sqlplus/sqlplus_*.log
```

Jira evidence layout:

```text
OraFlow/jira/<KEY>/issue.json
OraFlow/jira/<KEY>/comments.json
OraFlow/jira/<KEY>/summary.md
OraFlow/jira/<KEY>/attachments/
OraFlow/jira/<KEY>/fetches.jsonl
OraFlow/jira/<KEY>/related_index.json
OraFlow/jira/<KEY>/related_summary.md
OraFlow/jira/<KEY>/related/<OTHER-KEY>/
OraFlow/jira/<KEY>/similar_tickets.json
OraFlow/jira/_audit/fetches.jsonl
```

This is why OraFlow reports can be audited after the fact. The artifacts are not just chat text; they are files with exact SQL, exact JSON rows, and append-only run metadata.

### Target Resolution and Active Target

Target resolution lives in `src/oraflow/target.py` and uses both the customer catalog and TNS catalog.

The user can say something like `cloud dev 46`, `kinney prod onprem tx`, or an exact alias. OraFlow parses customer, environment, layer, and deployment words. It then filters candidates and either resolves exactly or reports ambiguity.

When a target is set, OraFlow writes `OraFlow/session.json`. That session contains the pinned alias, profile, customer, environment, schema/layer, deployment, and timestamp. The important idea is that later script execution does not need to re-infer the database. It uses the active target unless an explicit alias/profile fallback is intentionally supplied.

### Oracle Execution

The normal Oracle path is python-oracledb in bundled thick mode. The packaged extension does not hunt for a machine-level Oracle client; it points the MCP server at the Instant Client and Oracle network files shipped inside the VSIX.

For older on-prem PROD targets where modern authentication can fail, OraFlow has a SQL*Plus 12.2 fallback. That fallback still runs through the same safety and evidence path:

1. SQL is validated as read-only.
2. The script artifact already exists.
3. SQL*Plus runs with generated sentinels and CSV output.
4. Passwords are redacted from debug logs.
5. Rows are parsed into the same `QueryResult` structure.
6. Text output, JSON output, and audit rows are written.

### Schema Catalog

The schema catalog is local DDL under `schemas/`. It is loaded by `src/oraflow/schema_catalog.py`. OraFlow parses table definitions, columns, primary keys, and foreign key names. It supports:

- Catalog summary.
- Table listing by layer/schema/pattern.
- Exact table description.
- Fuzzy schema search with RapidFuzz.
- Column substring search.

This avoids live database schema probing during investigation setup.

### SQL Safety

SQL safety is implemented in `src/oraflow/safety.py`. The validator:

- Allows only `SELECT` and `WITH` read-only queries.
- Rejects common write/admin first tokens like `UPDATE`, `DELETE`, `INSERT`, `MERGE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `COMMIT`, and `ROLLBACK`.
- Uses `sqlglot` to parse Oracle SQL.
- Blocks write/admin expression types.
- Blocks multi-statement input.
- Blocks `FOR UPDATE`, `FOR SHARE`, and `SELECT INTO`.
- Blocks dangerous package/schema patterns such as `DBMS_`, `UTL_`, `SYS.`, `SYSTEM.`, `EXECUTE IMMEDIATE`, and `DBMS_SQL`.

The safety model is enforced before execution, not just documented.

### JiraFlow

JiraFlow is OraFlow's read-only Jira evidence layer. It fetches:

- Issue JSON.
- Comments JSON.
- Attachment metadata and selected attachment files within size caps.
- A summary markdown file.
- Fetch audit rows.
- Related-ticket indexes.
- Selected related tickets.
- Similar-ticket search results.

JiraFlow does not edit tickets. It does not comment, transition, upload, or change fields.

## Primary Runtime Flows

### First-Time Setup Flow

```text
1. User installs VSIX.
2. User opens a workspace.
3. User runs OraFlow: Setup Credentials.
4. User optionally runs OraFlow: Setup Jira Credentials.
5. User runs OraFlow: Configure MCP for Workspace.
6. Extension writes .vscode/mcp.json and managed agent instructions.
7. User starts/trusts the oraflow MCP server in VS Code.
8. Copilot can now call OraFlow tools.
```

### Non-PROD Smoke Test Flow

```text
1. Ask Copilot to show OraFlow config info.
2. Ask Copilot to search schema for RX_BASE.
3. Ask Copilot to set a known non-PROD active target and ping it.
4. Ask Copilot to author a read-only script artifact.
5. Run it with run_active_target_script.
6. Read the JSON sidecar with read_script_results.
7. Confirm an audit row exists in OraFlow/db/_audit/runs.jsonl.
```

Example query:

```sql
SELECT *
FROM TREXONE_DATA.RX_BASE
ORDER BY RX_RECORD_NUM
FETCH FIRST 10 ROWS ONLY;
```

### ERXD/L3 Flow

```text
1. User provides ERXD key.
2. Agent calls jira_get_ticket first.
3. Jira evidence is written under OraFlow/jira/<KEY>/.
4. Agent reads summary, issue JSON, comments, attachment metadata, and related tickets.
5. Agent classifies the ticket and decides evidence lanes.
6. If DB evidence is needed, agent resolves and pins customer PROD target.
7. Agent pings active target and verifies identity.
8. Agent uses schema catalog to validate tables/columns.
9. Agent authors small focused SQL script artifacts.
10. Agent runs scripts through run_active_target_script.
11. Agent reads JSON results and audit rows.
12. Agent writes the analysis with evidence provenance.
```

### Jira Retrieval Flow

```text
1. Agent calls jira_get_ticket(KEY).
2. OraFlow loads Jira credentials from ~/.oraflow/jira.toml.
3. Jira REST JSON is fetched.
4. Comments are fetched separately and paginated as needed.
5. Attachment metadata is captured; attachment files are downloaded only when explicitly requested.
6. issue.json, comments.json, summary.md, optional attachments, and audit rows are written.
7. Related-ticket tools can build related_index.json and related_summary.md.
8. Similar-ticket search can write similar_tickets.json.
```

## What Makes OraFlow Different

OraFlow is not just a wrapper around Oracle queries. The differentiators are:

- Read-only SQL enforcement in code.
- Active target pinning to prevent accidental wrong-environment reads.
- PROD discipline with explicit ping and sibling handling.
- Script artifacts instead of one-off inline query output.
- JSON sidecars as source of truth.
- Append-only audit rows for successful and failed SQL runs.
- Bundled DDL schema catalog for DB-free schema discovery.
- Read-only Jira evidence capture with local durable files.
- VS Code extension packaging that makes the same backend and rules reproducible.
- Managed Copilot instructions so the agent follows the same safety workflow.

## Demo Talk Track

Use this as a short live demo script.

1. "First I install the VSIX and open my EnterpriseRx workspace."
2. "Then I run `OraFlow: Setup Credentials`. That opens a TOML file under my user profile, not inside the repo."
3. "If I need Jira, I run `OraFlow: Setup Jira Credentials`, which creates a separate Jira TOML file."
4. "Then I run `OraFlow: Configure MCP for Workspace`. This writes `.vscode/mcp.json` and points VS Code at the bundled local MCP server."
5. "The backend is local and stdio-based. It is not a web service and it does not open a listening port."
6. "Now in Copilot I can ask for OraFlow config info, search the schema catalog, or fetch a Jira ticket."
7. "For a database investigation, I first set an active target and ping it."
8. "For evidence, I do not ask the agent to run an inline query. I ask it to author a script artifact, run that script against the active target, and read the JSON result."
9. "That gives me a SQL file, a text output file, a JSON output file, and an audit row."
10. "For an ERXD ticket, the flow starts with Jira. The agent fetches the ticket, comments, attachment metadata, and related context before deciding whether DB evidence is needed. Attachment files are explicit when they matter."
11. "The important architecture point is that every sensitive action goes through a constrained tool path: target resolution, ping, SELECT-only validation, script artifact execution, JSON evidence, and audit."

## Common Questions and Answers

### Is OraFlow a database write tool?

No. OraFlow is read-only. The SQL validator rejects DML, DDL, PL/SQL, transaction control, and dangerous package/schema references before execution. Execution also runs under read-only transaction behavior.

### Does OraFlow store credentials in the repo?

No. Database credentials are in `~/.oraflow/credentials.toml`. Jira credentials are in `~/.oraflow/jira.toml`. Workspace MCP config contains paths and environment variables, not passwords.

### Does OraFlow send data to a server?

The MCP backend runs locally over stdio. It connects to Oracle when database tools are used and to Atlassian when Jira tools are used. Evidence files are written locally under the workspace `OraFlow/` folder.

### Why not let Copilot run SQL directly?

Direct SQL in chat is not auditable enough for L3 work. OraFlow forces evidence-worthy work through script artifacts so we keep exact SQL, exact output, structured JSON rows, target identity, timing, row counts, and audit rows.

### Why do schema tools use local DDL instead of live `describe_table`?

Because most schema lookup does not require a database session. Local DDL lookup is faster, safer, and avoids accidental live connections. Live/session schema tools are treated as advanced non-PROD helpers, not the L3 evidence path.

### What happens if a PROD endpoint times out?

OraFlow reports the timeout and includes sibling endpoint information when available. It does not auto-fail over. The agent must show the sibling list and ask the user which endpoint to try.

### What is the source of truth for query results?

The structured JSON sidecar, `*_output.json`, is the source of truth. The text output is human-readable and useful, but it can be lossy.

### What is the source of truth for Jira evidence?

The files under `OraFlow/jira/<KEY>/` are the source evidence: `issue.json`, `comments.json`, `summary.md`, `attachments/`, related-ticket indexes, and similar-ticket results.

## Closing Statement

OraFlow is designed around controlled evidence capture. The extension handles installation and workspace wiring. The MCP server enforces the tool boundary. The schema catalog prevents guessing. Active targets prevent wrong-database reads. Script artifacts preserve SQL and results. Audit logs preserve provenance. JiraFlow preserves ticket evidence. Together, those pieces turn Copilot into a safer, repeatable L3 investigation workflow for EnterpriseRx.
