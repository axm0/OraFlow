# OraFlow — Planning Document

## 🎯 Goal
Build an **MCP server** (with optional agent wrapper) that lets an LLM / IDE assistant
connect to our Oracle databases using credentials + TNS aliases (the same ones Toad uses)
and run **safe, read-only queries** against them — replacing the manual Toad workflow
for "ask the DB a question" tasks.

In one sentence:
> *Give an AI agent the same DB reach a developer has in Toad, but with guardrails,
> auditing, and natural-language ergonomics.*

---

## 🧭 Why MCP (vs. a custom agent)
- **Reusable**: One server works with Claude Desktop, VS Code Copilot Chat, Cline, Cursor, etc.
- **Standard protocol**: Tools/resources/prompts surface — no bespoke chat UI to build.
- **Local-first**: Runs on the dev's machine, talks to internal DBs over the existing network.
- **Composable**: Agent layer (LangGraph / custom) can sit *on top* later.

We will build the **MCP server** first. An optional agent wrapper is a Phase 3 stretch.

---

## 🌐 Historical Environment Snapshot

This section records the original development workstation context only. OraFlow's current VS Code extension ships its own Oracle runtime, TNS files, SQL*Plus fallback, schema catalog, and MCP backend; future users do not need this machine-level setup.

- Windows dev box, **uv 0.11.9**, Python **3.13** available.
- Local Oracle Instant Client and TNS paths existed on the original dev box, but they are no longer runtime requirements.
- The bundled `tnsnames.ora` contains **~700+ aliases** across PROD / UAT / STAGE / TRNG / QA.
- Aliases follow a clear pattern: `CUSTOMER-ENV.SID` (e.g. `MAYOCLINIC-PROD.ZDWMYOP01`).
- Hosts grouped by codename (`anaconda`, `juno`, `pluto`, `bushmaster`, `cayenne`, `marbles`,
  `neptune`, `diana`, `copperhead`, `cascabel`, `bonnet`, `carolina`, …).
- Many alias names repeat across hosts (`19CDB`, `EM_AGENT`, `-MGMTDB`) → must be disambiguated.
- Domain: **healthcare / pharmacy** data (Mayo, Hopkins, Vanderbilt, etc.) → **HIPAA / PHI sensitivity**.

---

## 🧱 High-Level Architecture

```
MCP client (VS Code Copilot Chat / Claude Desktop / Cline)
        │  stdio JSON-RPC
        ▼
┌──────────────────────────────────────────┐
│ OraFlow MCP server                       │
│  • TNS catalog (parsed + indexed)        │
│  • Connection manager (oracledb pool)    │
│  • Safety layer (sqlglot, timeouts)      │
│  • Credential vault (keyring)            │
│  • Audit log (JSONL)                     │
└──────────────────────────────────────────┘
        │ python-oracledb (thin or thick)
        ▼
   Oracle DBs (via TNS aliases)
```

---

## 🛠️ Tool Surface (planned)

| Tool | Purpose | Phase |
|---|---|---|
| `tns_info` | Summary of loaded `tnsnames.ora` (counts, envs, host groups) | 1 |
| `search_tns(query, env?, customer?, host_group?, limit)` | Fuzzy search over aliases | 1 |
| `describe_tns(alias_or_key)` | Resolve alias → host/port/SID/service | 1 |
| `set_active_target` / `get_active_target` | Pin exact alias/profile/deployment/layer | 1 |
| `ping_active_target` | Verify the pinned target before reads | 1 |
| `search_schema` / `describe_schema_table` / `find_schema_columns` | Browse bundled DDL without DB reads | 1 |
| `author_sql_script` | Create SELECT-only script artifacts | 1 |
| `run_active_target_script` / `run_sql_script` | Run script artifacts and write audit/JSON evidence | 1 |
| `read_script_results` / `read_script_output` | Read JSON source-of-truth / human text output | 1 |
| `run_query_once` | Simple one-statement non-PROD checks only | 2 |
| `connect` / `run_query` / live schema tools | Advanced non-PROD session helpers, not investigation path | 3 |

---

## 🔐 Safety & Compliance

- **Default read-only**: parse SQL with `sqlglot`, reject `INSERT/UPDATE/DELETE/MERGE/DDL`.
- **Auto-cap rows**: wrap unbounded SELECTs with `FETCH FIRST N ROWS ONLY`.
- **Statement timeout**: per-query (default 30s).
- **Audit log**: every connect/query/error → JSONL at `%APPDATA%\OraFlow\audit-YYYY-MM-DD.jsonl`.
  Logs SQL hash + truncated SQL — **never row data**, **never passwords**.
- **Credential handling**:
  - Default: prompt-on-connect, kept in process memory only.
  - Opt-in: `keyring` → Windows Credential Manager.
  - No plaintext secrets on disk, no secrets in audit log.
- **PHI redaction (Phase 2)**: configurable column allow/deny list (e.g., mask `PATIENT_NAME`, `SSN`, `DOB`).
- **Multi-tenant safety**: host_group + env tags surfaced in every tool response so the LLM
  always knows which DB it's looking at.

---

## 🧩 TNS Handling Strategy

Because `tnsnames.ora` has duplicates and 700+ entries:

1. **Custom parser** (regex + paren-balanced scanner) → list of `TnsEntry` records.
2. **Pattern extraction** from alias: `CUSTOMER-ENV.SID_TOKEN` → structured fields.
3. **Host group** from FQDN first label (`juno-admin.…` → `juno`).
4. **Composite key** `ALIAS@host_group` to disambiguate duplicates.
5. **Searchable index** via `rapidfuzz` so the LLM never has to see the full list —
   it calls `search_tns("mayo prod warehouse")` and gets a tiny ranked subset.

---

## 📁 Proposed Project Layout

```
OraFlow/
├── pyproject.toml
├── plan.md                ← this file
├── README.md              (later)
├── .env.example
├── .vscode/mcp.json       (later — wires server into Copilot Chat)
├── src/oraflow/
│   ├── __init__.py
│   ├── __main__.py        (MCP entrypoint)
│   ├── config.py
│   ├── tns.py             (parser + catalog + search)
│   ├── connections.py     (oracledb pool manager)
│   ├── safety.py          (sqlglot guards, row-cap injection)
│   ├── audit.py           (JSONL logger)
│   ├── creds.py           (keyring wrapper — Phase 2)
│   ├── formatting.py      (rows → JSON / markdown preview)
│   └── server.py          (FastMCP tool registrations)
└── tests/
    ├── test_tns_parser.py (uses real tnsnames.ora fixture)
    └── test_safety.py
```

---

## 📦 Dependency Plan (not installed yet)

| Package | Why |
|---|---|
| `oracledb` (≥2.4) | Oracle driver, thin mode default, thick optional |
| `mcp[cli]` (≥1.2) | Official MCP Python SDK (FastMCP) |
| `sqlglot` (≥25) | Parse SQL → detect DML/DDL, transform queries |
| `rapidfuzz` (≥3.9) | Fast fuzzy search over alias catalog |
| `keyring` (≥25) | Windows Credential Manager integration |
| `structlog` (≥24) | Clean structured logging |
| `pydantic` + `pydantic-settings` | Config + env loading |
| `pytest`, `pytest-asyncio` (dev) | Tests |

---

## 🚀 Phased Roadmap

### Phase 1 — MVP (historical roadmap; implementation has moved to bundled extension runtime)
- [ ] Project scaffold (uv init, pyproject, src layout)
- [ ] `config.py` (settings; current implementation uses explicit/bundled TNS instead of machine-level TNS_ADMIN auto-detect)
- [ ] `tns.py` — parser + catalog + fuzzy search
- [ ] `safety.py` — read-only enforcement + row cap
- [ ] `audit.py` — JSONL audit
- [ ] `connections.py` — oracledb execution and optional advanced session registry
- [ ] `server.py` — FastMCP with: `tns_info`, `search_tns`, `describe_tns`,
  `set_active_target`, `ping_active_target`, `author_sql_script`,
  `run_active_target_script`, `run_sql_script`, `read_script_results`
- [ ] Tests for parser + safety
- [ ] VS Code `mcp.json` + Claude Desktop config snippets

### Phase 2 — Productionize
- [ ] Keyring-backed saved credentials + profiles
- [ ] `explain_plan`, `get_ddl`, `list_constraints`, schema cache
- [ ] PHI redaction config
- [ ] Thick-mode toggle (Instant Client / wallet)
- [ ] CLI: `oraflow tns search ...`, `oraflow tns info`

### Phase 3 — Smart layer
- [ ] Optional FastAPI web UI (Toad-lite: connection picker, query editor, results grid)
- [ ] NL→SQL helper tool that grounds on cached schema
- [ ] Toad connection-list importer (if a `.tcs`/XML export exists)
- [ ] Additional read-only evidence helpers only; no DML/admin execution surface
- [ ] Optional LangGraph agent wrapper around the MCP tools

---

## 🔍 Reference Repos To Review Before Coding

- **Oracle's official MCP repo** (cloned locally) — review for:
  - License & whether we can build on it / fork vs. start fresh
  - How they handle TNS / wallets / Instant Client thick mode
  - Their tool surface (we may align names for portability)
  - Auth patterns (wallets, Kerberos, OS auth)
  - Any HIPAA/PHI-relevant patterns (likely none — we add ours)
- **Anthropic MCP Python SDK examples** — confirm FastMCP idioms.

> Action: note the cloned repo path here and diff its design against this plan
> **before** writing any OraFlow code.
> Cloned at: `<paste path>`

---

## ❓ Open Questions (decide before Phase 1 coding)

1. **Client target** — VS Code Copilot Chat? Claude Desktop? Both?
2. **Auth modes** — username/password only, or also wallet / Kerberos / OS auth?
3. **Default row cap** — 100 OK? Hard ceiling 10,000?
4. **Audit location** — `%APPDATA%\OraFlow\` OK, or a network share?
5. **PHI redaction default** — on with starter list, or off until we configure?
6. **Build on top of Oracle's MCP repo** or write our own thin server? (Decide after review.)
7. **Multi-DB simultaneous** sessions, or one active at a time?

---

## ✅ Next Step
1. Review Oracle's MCP repo against this plan (paste its README / tool list here).
2. Answer the open questions above.
3. Lock the dependency list.
4. Then proceed to Phase 1 implementation.