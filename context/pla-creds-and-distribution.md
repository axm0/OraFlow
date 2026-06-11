# OraFlow — Credential Mapping, Read-Only Safety & Distribution Plan

**Status:** Brainstorming / decision-pending
**Companion to:** [`pla-tns-metadata.md`](pla-tns-metadata.md) (env overlay) and [`pla.md`](pla.md) (overall direction).
**Do not modify code yet.** This doc decides *how* the env-overlay turns into a shippable thing other engineers can drop their own creds into and ask Copilot/Claude/Cursor "run this SELECT on QA13".

---

## 1. The end-to-end story (one paragraph)

A teammate installs the OraFlow MCP server (or the VS Code / IntelliJ extension that wraps it). On first run, OraFlow opens a tiny credential UI / file and asks them to paste **their** Oracle username + password for each *credential profile* they have access to (`PROD`, `QA`, `DEV`, `DEV-CLOUD`). Those creds are stored on **their** machine only — never in the repo. From then on, when Copilot says *"run `SELECT ... FROM rx_order WHERE ...` on QA13"*, OraFlow:

1. Resolves `QA13` → env `ndcq13` (cloud, qa, NDC) via the env overlay.
2. Picks the right TNS alias for the role (OLTP `txndcq13` / OLAP `dwndcq13`) from the merged TNS catalog.
3. Picks the right credential profile via deterministic rules (cloud + qa → `QA-CLOUD` → that user's `txstage`-equivalent creds).
4. Validates the SQL through a multi-layer SELECT-only guard (parser → AST walk → DB-side enforcement).
5. Connects, runs the query with a hard timeout + row cap, returns rows.

Nobody hand-edits TNS strings. Nobody types passwords into chat. Nothing destructive can ever execute, even if Copilot hallucinates a `DELETE`.

---

## 2. Credential mapping (the core question)

### 2.1 Today
- `~/.oraflow/credentials.toml` holds TOML sections keyed by deployment/tier, such as `[onprem.prod]` and `[cloud.qa]`.
- [`credentials.py`](src/oraflow/credentials.py) loads TOML only; legacy `.env` credential formats are intentionally unsupported.
- The user can still pick a profile via `--profile` / `ORAFLOW_DB_PROFILE`, but normal workflows resolve the active target to an exact profile.

### 2.2 What we add: deterministic profile resolution from `(tier, deployment)`

Add a small **mapping table** inside the env overlay (`environments.yaml`) — *not* in code — so each org can override it:

```yaml
credential_rules:
  # exact (tier, deployment) → profile
  - { tier: prod,  deployment: onprem, profile: PROD }
  - { tier: prod,  deployment: cloud,  profile: PROD-CLOUD }   # if/when it exists
  - { tier: uat,   deployment: onprem, profile: QA }           # txstage works per txtagecreds.txt
  - { tier: stage, deployment: onprem, profile: QA }
  - { tier: qa,    deployment: onprem, profile: QA }
  - { tier: qa,    deployment: cloud,  profile: CLOUD.QA }
  - { tier: preqa, deployment: cloud,  profile: CLOUD.QA }
  - { tier: dev,   deployment: onprem, profile: DEV }
  - { tier: dev,   deployment: cloud,  profile: CLOUD.DEV }
  # fallback: any unmatched env requires explicit per-env override or refuses to connect
```

**Per-environment override** (escape hatch for the weird ones):

```yaml
environments:
  ndcp01:
    name: PROD01
    tier: prod
    deployment: onprem
    credential_profile: PROD              # explicit; bypasses the rule table
```

**Resolution algorithm** (in code):

```
resolve_profile(env) =
   env.credential_profile                                              # 1. explicit
   ?? credential_rules.match(env.tier, env.deployment)                 # 2. rule table
   ?? raise NoCredentialMappingError(env, "add credential_rules entry or per-env override")
```

Current OraFlow avoids alias indirection by using direct TOML sections such as `[cloud.qa]` and `[onprem.qa]`.

### 2.3 Pre-flight reachability check

New CLI: `oraflow creds doctor`. For each TOML credential profile, pick **one representative env** per `(tier, deployment)` bucket that maps to it, ping with a 5-second timeout, and print a green/red matrix. It catches expired passwords, blocked SSO, `SYSTEM.TXSTAGE_SECURE_LOGIN` triggers, etc., **before** Copilot tries to use them.

### 2.4 Credential storage: flat file, fully self-contained

**Decision (locked in):** Keep credentials in a plain file the user owns. **No** OS keychain, **no** vault, **no** external services, **no** network calls. OraFlow is an internal tool — everything it needs lives inside the install directory or the user's profile dir. Even Oracle Instant Client binaries get bundled (see §4.x).

**File:** `~/.oraflow/credentials.toml` (TOML — Python stdlib `tomllib` since 3.11, no new dependency).

**Layout — one file, sections keyed by `<deployment>.<tier>`:**

```toml
# ~/.oraflow/credentials.toml — local to each user, never committed
schema_version = 1

# On-prem environments
[onprem.prod]
username = "<oracle_username>"
password = "<oracle_password>"

[onprem.uat]
username = "<oracle_username>"
password = "<oracle_password>"

[onprem.qa]
username = "<oracle_username>"
password = "<oracle_password>"

[onprem.dev]
username = "<oracle_username>"
password = "<oracle_password>"

# Cloud (OCI) environments — only QA and DEV exist today (no cloud.prod, no cloud.uat).
[cloud.qa]
username = "<oracle_username>"
password = "<oracle_password>"

[cloud.dev]
username = "<oracle_username>"
password = "<oracle_password>"

# (No cloud.prod or cloud.uat sections — those tiers don't exist on cloud yet.)

# Optional per-customer or per-env overrides for outliers
[overrides.ahdp01]                     # AHOLD prod uses a different account
username = "<oracle_username>"
password = "<oracle_password>"
```

**Why one file with `[deployment.tier]` sections instead of many `onpremdev.env` / `onpremqa.env` files:**

| Concern | One TOML file | Many `.env` files |
|---|---|---|
| Atomic edit / backup | ✓ one file to copy | ✗ N files to keep in sync |
| `chmod 600` once | ✓ | ✗ per file |
| Schema validation | ✓ Pydantic over dict | clumsy across files |
| `oraflow creds doctor` lists everything | ✓ trivial | needs directory scan |
| Diff in code review (the day this gets shared) | ✓ readable | scattered |
| Adding a new env type later (e.g. `[gov.prod]`) | ✓ just add a section | new file convention |

**Resolution rule** (fits the §2.2 mapping cleanly):

```
resolve_credentials(env) =
   credentials.overrides[env.domain]                          # 1. per-env override
   ?? credentials[env.deployment][env.tier]                   # 2. (deployment, tier) match
   ?? raise NoCredentialsError(env, "add a [deployment.tier] section to credentials.toml")
```

Notice this **collapses §2.2's `credential_rules` table into the credentials file itself** — no separate rules block needed. The credentials file *is* the (deployment, tier) → creds mapping. Simpler. The env overlay (`environments.yaml`) just supplies `tier` and `deployment` per env; the credentials file decides what user/password to use for that pair.

Legacy credential-file migration is intentionally not supported; create `~/.oraflow/credentials.toml` through the VS Code setup command.

**File location resolution** (in priority order):

1. `--credentials <path>` CLI flag.
2. `ORAFLOW_CREDENTIALS_PATH` env var.
3. `<workspace>/credentials.toml` (project-local, useful for dev).
4. `~/.oraflow/credentials.toml` (user default).
5. `<oraflow install dir>/credentials.toml` (bundled fallback — empty template).

If none of (1)–(4) exist, OraFlow refuses to connect and prints the path it expected plus the `oraflow init` command.

**Permissions:** on first write, `oraflow init` does `chmod 600` on POSIX and applies an ACL on Windows so only the current user can read it. No encryption — that's what the OS file permissions are for, and we don't want to add a master-password UX or a crypto dependency.

**`credentials.py` refactor:** use TOML parsing only. Legacy regex-based `.env` parsing is removed.

---

## 3. SELECT-only enforcement (defence in depth)

The existing [`safety.py`](src/oraflow/safety.py) is a solid first layer. To be *trustworthy* when an LLM is the one writing the SQL, we need **all of these layers, every query, no exceptions**:

### Layer 1 — String hygiene (existing)
- Strip block + line comments.
- Reject multi-statement (`;` outside trailing position).
- Reject if first token isn't `SELECT` / `WITH`.
- ✅ Already in [`safety.py`](src/oraflow/safety.py).

### Layer 2 — AST validation (existing, tighten)
- `sqlglot.parse_one(..., read="oracle")` must produce `exp.Select`.
- AST walk rejects any `Alter / Create / Delete / Drop / Insert / Merge / TruncateTable / Update / Command`.
- Reject `FOR UPDATE` and explicit `LOCK TABLE`.
- ✅ Already in [`safety.py`](src/oraflow/safety.py). **Add:**
  - Reject `WITH ... AS ( INSERT ... )` (CTE write — sqlglot exposes nested write ops).
  - Reject `DBMS_*` / `UTL_*` / `SYS.*` package calls in SELECT projections (they can mutate/exfiltrate).
  - Reject `XMLTYPE.transform`, `DBMS_LOCK.sleep`, `DBMS_PIPE.*`, etc. via a denylist of function names.

### Layer 3 — Bind-mode + LIMIT injection
- Always send via positional binds; never string-format user values.
- Auto-inject `FETCH FIRST :max_rows ROWS ONLY` if the query has no `FETCH` / `ROWNUM` cap (configurable; default `1000`).
- This protects against runaway LLM queries dumping a 50M-row table.

### Layer 4 — Session settings on connect
For *every* connection OraFlow opens, immediately run:

```sql
ALTER SESSION SET STATEMENT_TIMEOUT = 30000;       -- 30s, configurable
ALTER SESSION SET ISOLATION_LEVEL = READ ONLY;     -- DB enforces no writes
ALTER SESSION SET RECYCLEBIN = OFF;
```

`READ ONLY` isolation is the **real** safety net: even if our parser is bypassed, the DB itself refuses any DML/DDL with `ORA-01456`. This is the single most important layer.

### Layer 5 — Least-privilege DB user (organizational, not code)
Recommend (don't enforce in code) that teammates use a **read-only Oracle user** (`SELECT ANY TABLE` or per-schema `SELECT` grants, no `INSERT/UPDATE/DELETE/EXECUTE` on app packages). Document this; provide a `sql/create_oraflow_readonly_user.sql` template.

### Layer 6 — Audit log
Every executed query gets logged to `~/.oraflow/audit.jsonl` with: timestamp, profile, env, alias, sha256(sql), rowcount, duration, error. No SQL text by default (PHI); opt in with `ORAFLOW_AUDIT_LOG_SQL=1` for debugging.

### Layer 7 — Confirmation gate for "interesting" queries (optional, MCP only)
Queries against `prod` envs prompt the MCP client with `"This will run on PROD-NDC01 (CarelonRx). Continue?"` before executing. The host (Copilot, Claude Desktop) decides how to render that confirmation. Opt-in via `ORAFLOW_REQUIRE_PROD_CONFIRM=1`.

---

## 4. Distribution model (MCP / VS Code / IntelliJ)

### 4.1 Architecture: one core, three faces

```
┌─────────────────────────────────────────────────────────┐
│                  oraflow (Python core)                  │
│  TNS catalog · env overlay · creds backend · safety     │
│  · oracledb thin · audit log · DSN resolver             │
└──────────────┬──────────────────────────┬───────────────┘
               │ MCP stdio                │ subprocess CLI
               ▼                          ▼
   ┌───────────────────────┐   ┌─────────────────────────┐
   │   MCP server          │   │  VS Code extension (TS) │
   │   (FastMCP, today)    │   │  - tree view            │
   │   For: Copilot,       │   │  - cred entry UI        │
   │        Claude Desktop,│   │  - results table        │
   │        Cursor, etc.   │   │  - shells out to oraflow│
   └───────────────────────┘   └─────────────────────────┘
                                ┌─────────────────────────┐
                                │ IntelliJ plugin (Kotlin)│
                                │ - same UX as VS Code    │
                                │ - shells out to oraflow │
                                └─────────────────────────┘
```

**Key principle:** All three faces are thin. They never duplicate TNS parsing, classification, safety logic, or DB code — they call the Python core via MCP (for AI clients) or CLI subprocess (for human IDE actions).

### 4.2 What ships in each artifact

**Guiding principle (locked in):** OraFlow is fully self-contained. Everything it needs to connect to Oracle ships *inside* the package. No `pip install oracledb` from PyPI at runtime, no system-installed Instant Client, no OS keychain, no network access for anything except the actual Oracle DB connection itself.

| Artifact | Ships (bundled inside) | User supplies |
|---|---|---|
| `oraflow` install bundle (zip / wheel / PyInstaller exe) | Python core code · vendored `oracledb` · vendored Instant Client binaries (Windows + macOS + Linux x64) · default `tnsnames.ora` + `cloud-tnsnames.ora` · default `environments.yaml` · empty `credentials.toml` template · vendored `sqlglot`, `pydantic`, `typer`, `rapidfuzz`, `tomllib`-shim if Py<3.11 | Their own `credentials.toml` (filled in via `oraflow init`) |
| MCP server | Same bundle, runs as `oraflow mcp` | — |
| VS Code extension | Same bundle wrapped + `extension.js` shim that spawns `oraflow.exe` | — |
| IntelliJ plugin | Same bundle wrapped + Kotlin shim | — |

**Vendoring strategy:**
- Use `oracledb` **thin mode** by default (pure Python, no Instant Client needed) — this is what you already have working.
- Bundle Instant Client only as a fallback for the `DPY-3015` cases (the older password verifiers that thin mode can't handle, like the `ZDWNDCQ11` issue from `txtagecreds.txt`). Auto-switch to thick mode when thin mode raises `DPY-3015`. Instant Client adds ~80 MB per platform — acceptable for an internal tool.
- Pin every dependency in `pyproject.toml`, build wheels into a `vendor/` directory, install from there at packaging time. No PyPI calls when a teammate runs the bundled exe.

**No-network guarantee at runtime:**
- OraFlow itself opens exactly one network socket: the TCP connection to whatever host the resolved TNS alias points at.
- No telemetry. No update checks. No auto-download of anything. Document this prominently — it's a selling point for a regulated environment.

### 4.3 First-run UX (the part that matters for adoption)

When a teammate runs `oraflow init`:

```
$ oraflow init
✓ Discovered TNS files: tnsnames.ora (818 entries), cloud-tnsnames.ora (85 entries)
✓ Discovered environments.yaml (164 environments)
✓ Discovered credential rules (9 rules covering 8 (tier,deployment) buckets)

I need credentials for the profiles you have access to. Skip any you don't.

  [1/4] PROD          (used by 92 envs: ahdp01, lemp01, wegp01, …)
        Username: amohammed
        Password: ********    [stored in: Windows Credential Manager]
  [2/4] QA            (used by 48 envs: ndcq11, ahdq01, …)
        Username: txstage
        Password: *****       [stored in: Windows Credential Manager]
  [3/4] DEV           (used by 18 envs)            [skipped]
  [4/4] DEV-CLOUD     (used by 30 envs)
        Username: amohammed_dev
        Password: ********    [stored in: Windows Credential Manager]

Running reachability check (oraflow creds doctor) …
  PROD          ✓ ahdp01 OK (1.2s)
  QA            ✓ ndcq11 OK (0.8s)   ✓ ndcq16@cloud OK (1.4s)
  DEV-CLOUD     ✗ ndcd16@cloud  DPY-6005: cannot connect (check VPN)

✓ Setup complete. Now point your MCP client at:
    oraflow mcp --transport stdio
```

That single command is the entire onboarding. No editing files, no copy-pasting connection strings, no asking the senior dev "what's the password format again."

### 4.4 What goes in source control vs. what doesn't

| In repo | Local-only |
|---|---|
| `tnsnames.ora`, `cloud-tnsnames.ora` (sanitized — IPs/hostnames are not secrets but verify with security) | `credentials.toml` |
| `environments.yaml` (no creds, no IPs that aren't in TNS already) | `~/.oraflow/audit.jsonl` |
| `credential_rules` block | OS keychain entries |
| `environments.local.yaml` overrides? — **no, force per-env override into the main file** so review catches them | `.oraflow/state.json` (last-used profile per alias, etc.) |

**Open security question:** are the on-prem hostnames in `tnsnames.ora` considered sensitive? If yes, the public PyPI package ships *empty* TNS files and the user supplies their own via `ORAFLOW_TNSNAMES_PATHS`. Mark this as **decision needed**.

---

## 5. New MCP tools (the surface Copilot actually calls)

Building on the existing `search_tns` / `connect` / `query` tools:

| Tool | Inputs | Output | What it unlocks |
|---|---|---|---|
| `list_environments` | `tier?`, `deployment?`, `customer?`, `limit` | array of env summaries | "show me all CarelonRx prod envs" |
| `get_environment` | `domain_or_name` | full env w/ resolved OLTP+OLAP TNS entries + credential profile | "what's QA13?" |
| `find_environment_for_alias` | `alias` | env that owns it, or null | reverse lookup |
| `resolve_credentials` | `domain_or_name`, `role=oltp\|olap` | `{ profile, username, has_password, reachability_status }` (never returns password) | LLM can ask "do I have access to this?" without seeing secrets |
| `run_select` | `domain_or_name`, `role`, `sql`, `max_rows?`, `timeout_s?` | rows + metadata + audit_id | the **one** tool Copilot uses to actually query |
| `explain_plan` | same as `run_select` | EXPLAIN PLAN output | safe diagnostic, never executes the real query |
| `creds_doctor` | none | reachability matrix | first-run + on-demand health check |

Notably **absent**: any tool that takes raw username/password as input. The host LLM should never see, log, or store credentials.

### 5.1 Schema-aware tools (powered by the bundled DDL — see §9)

| Tool | Inputs | Output | What it unlocks |
|---|---|---|---|
| `list_tables` | `schema?`, `pattern?`, `limit` | table names + 1-line description if available | LLM asks "what tables relate to prescriptions?" without hitting the DB |
| `describe_table` | `schema.table` | columns w/ types/nullability + PK/FK + comments (parsed from bundled DDL) | LLM grounds its `SELECT col_x` in real column names |
| `find_columns` | `pattern` | matching `schema.table.column` rows | "where is `pd_patient_key` used?" → all FK targets |
| `get_table_relationships` | `schema.table` | parent/child FK list | LLM builds correct JOINs without a round-trip |
| `search_schema` | free-text query, `top_k` | ranked `schema.table` matches via fuzzy + token overlap | "patient allergy history" → `patient_allergy`, `h_patient_allergy`, `imh_patient_allergy`… |

These are **DB-free** — they read the bundled DDL files only, never connect to Oracle. So they're instant and safe to call as often as the LLM wants. Copilot's typical loop becomes: `search_schema` → `describe_table` → `run_select` (one DB hit, well-formed).

---

## 6. Bundled schema catalog (`trexone_data/`) — AI grounding asset

### 6.1 Why this matters

The single highest-leverage thing we can do for "Copilot writes correct SQL on the first try" is **show the model the real column names before it writes the query**. Without that, an LLM guesses `customer_id` when the actual column is `pd_patient_key`. With it, hallucination drops dramatically. Bundling the DDL inside the package gives us:

- **Zero-DB-roundtrip schema lookup** — instant, no auth needed, no PHI exposure.
- **Offline grounding** — works on a plane, in a SCIF, anywhere.
- **Deterministic context** — every teammate's Copilot sees the exact same schema definition.
- **Auditable provenance** — the DDL files are the same ones the DBAs ship; no LLM-summarized lossy version.

### 6.2 What's there today

`trexone_data/` ships **1,475 `.sql` files**, one per table. Sample (`patient.sql`):

```sql
CREATE TABLE "TREXONE_DW_DATA"."PATIENT"
   (    "PD_PATIENT_KEY" NUMBER(18,0) NOT NULL ENABLE,
        "PD_PATIENT_NUM" NUMBER(18,0),
        "PD_FIRST_NAME" VARCHAR2(30),
        ...
        CONSTRAINT "PK_PATIENT" PRIMARY KEY ("PD_PATIENT_KEY") ...
        CONSTRAINT "FK_PATIENT_DEMOGRAPHIC_03" FOREIGN KEY ("PATIENT_DEMOGRAPHIC_KEY") ...
   ) TABLESPACE "DW_LARGE_DATA01"
```

**⚠️ Naming clarification needed:** the schema name inside the DDL is **`TREXONE_DW_DATA`**, the tablespace is `DW_LARGE_DATA01`, and the file set includes ~400 `h_*.sql` history-tracking tables — all signs that this folder is the **OLAP / data-warehouse schema**, *not* OLTP `trexone_data`. So today the AI has perfect grounding for the `dw*` (OLAP) connections but no DDL for the OLTP side. Two options:

1. **Add an OLTP DDL export alongside it** — drop a `trexone_data_oltp/` folder with the OLTP table set. Best long-term.
2. **Ship just OLAP grounding for now** and accept that OLTP queries lean on alias/column overlap with OLAP (high but not perfect).

Recommend (1). For now, the loader is built to handle multiple schema folders so adding OLTP later is a no-op.

### 6.3 Where it lives in the package

```
oraflow/
  data/
    schemas/
      trexone_dw_data/          # renamed from trexone_data/ to match real schema name
        patient.sql
        rx.sql
        ...
        _index.json             # generated: { table: file, columns: [...], pk, fks }
      trexone_data_oltp/        # future
      _meta.json                # { schemas: [...], generated_at, source_dir }
```

Renaming keeps the bundle honest — the folder name matches the actual Oracle schema, so an LLM that sees `trexone_dw_data.patient` and looks up the file finds it without confusion.

### 6.4 Loader: `src/oraflow/schema_catalog.py`

Pydantic models + a one-shot indexer:

```python
class ColumnDef(BaseModel):
    name: str
    data_type: str          # "VARCHAR2(30)", "NUMBER(18,0)", "DATE", ...
    nullable: bool
    default: str | None

class TableDef(BaseModel):
    schema: str             # "TREXONE_DW_DATA"
    name: str               # "PATIENT"
    columns: list[ColumnDef]
    primary_key: list[str]
    foreign_keys: list[ForeignKeyDef]
    tablespace: str | None
    source_path: Path

class SchemaCatalog:
    def get(self, fqn: str) -> TableDef: ...                   # "schema.table"
    def search(self, query: str, top_k: int = 10) -> list[TableDef]: ...
    def find_columns(self, pattern: str) -> list[tuple[TableDef, ColumnDef]]: ...
    def relationships(self, fqn: str) -> RelationshipMap: ...
```

**Parsing strategy:** lightweight regex over `CREATE TABLE` statements rather than a full PL/SQL parser — DDL format is consistent enough (it's `expdp` / Toad-style export). Generated `_index.json` lets warm starts skip parsing all 1,475 files.

**Fuzzy table search** uses the existing `rapidfuzz` dependency (already in OraFlow for TNS search) plus a simple token-overlap signal so `"patient allergy"` → `patient_allergy`, `imh_patient_allergy`, `h_patient_allergy`, etc., ranked sensibly.

### 6.5 What this does NOT include (intentionally)

- **No views** — DDL files are tables only.
- **No indexes / triggers / procedures** — out of scope for safe SELECT generation; the LLM doesn't need them.
- **No actual data** — DDL is structural metadata, not PHI.
- **No live schema sync** — the bundled DDL is a snapshot. If the DB schema drifts, we add a `oraflow schema refresh` command later that exports fresh DDL via `DBMS_METADATA.GET_DDL` (read-only, fits the safety model).

### 6.6 Size sanity

1,475 files × avg ~3 KB raw = ~4.5 MB raw. Indexed JSON probably ~1–2 MB. Trivial bundle overhead and pays for itself the first time Copilot writes a JOIN with the right column names.

---

## 7. Implementation order (foundation-first)

Each step is independently shippable and unblocks the next.

| # | Step | Touches | Why this order |
|---|---|---|---|
| 1 | **Multi-file TNS loader** | `config.py`, `tns.py` | Foundation — everything else assumes both files load. No new deps. |
| 2 | **Tag entries with `source_tag`** (`@onprem`/`@cloud`) | `models.py`, `tns.py` | Disambiguates `19CDB` etc. without breaking existing API. |
| 3 | **Tighten `safety.py`** (CTE writes, function denylist, FETCH injection) | `safety.py`, tests | Pure-code, no infra dep. Ship before any new connection paths. |
| 4 | **Session-settings on connect** (`READ ONLY`, `STATEMENT_TIMEOUT`) | `db.py` | The big DB-side safety net — DB itself refuses writes regardless of parser. |
| 5 | **TOML credentials file + loader** | `credentials.py` | TOML-only credential loading. See §2.4. |
| 6 | **Schema catalog loader** (parse `trexone_data/`, build `_index.json`) | new `schema_catalog.py`, `data/schemas/trexone_dw_data/` | DDL parsing is pure Python; unblocks AI-grounding tools. See §6. |
| 7 | **Audit log** | new `audit.py`, `db.py` | Required before we let LLMs fire queries. |
| 8 | **`environments.yaml` loader + Pydantic models** | new `environments.py`, `config.py` | Lets us write tests against schema before exposing MCP tools. |
| 9 | **Credential resolver** (`(deployment, tier)` → creds, with overrides) | `credentials.py`, `environments.py` | Plugs the env overlay into the credentials file. |
| 10 | **Seed script from OpsDashboard** | `scripts/seed_environments_from_opsdashboard.py` | One-time data work. Output hand-reviewed before commit. |
| 11 | **`oraflow creds doctor`** | `cli.py`, `credentials.py`, `db.py` | Validates everything end-to-end. Replaces `txtagecreds.txt`. |
| 12 | **MCP tools — connection** (`list/get_environment`, `find_environment_for_alias`, `resolve_credentials`, `run_select`, `explain_plan`, `creds_doctor`) | `server.py` | Copilot can now query DBs. |
| 13 | **MCP tools — schema** (`list_tables`, `describe_table`, `find_columns`, `get_table_relationships`, `search_schema`) | `server.py`, `schema_catalog.py` | Copilot grounds queries in real columns. See §5.1. |
| 14 | **`oraflow init` first-run UX** | `cli.py` | Onboarding polish. Bundle includes `chmod 600` / ACL on the creds file. |
| 15 | **Vendor / bundle build** (PyInstaller, vendored Instant Client per OS) | `build/`, CI | Ship-to-teammates blocker. See §4.2. |
| 16 | **VS Code extension shell** | new `extensions/vscode/` | Optional — Copilot+MCP works without it. |
| 17 | **IntelliJ plugin shell** | new `extensions/intellij/` | Optional. |

Steps 1–13 are **all backend Python**, no IDE work. They're the entire MVP for "Copilot, with full schema awareness, can safely run SELECTs against any env using the right creds." Steps 14–15 are the shipping polish. 16–17 are nice-to-haves once the MCP path is proven.

---

## 8. Open decisions

**Locked in (per latest user direction):**
- ✅ **Q1** Cred storage: **flat TOML file** (`~/.oraflow/credentials.toml`), no OS keychain, no vault. See §2.4.
- ✅ **Q2** Bundled `tnsnames.ora` + `cloud-tnsnames.ora` ship **filled in** with the real entries. Internal tool ⇒ not sensitive.
- ✅ **Q-bundle** Distribution: **fully self-contained**, all binaries (incl. Oracle Instant Client) and Python deps vendored inside the package. No PyPI/network at runtime. See §4.2.
- ✅ **Q-rules** `credential_rules` collapsed into `credentials.toml` itself — no separate rules block in `environments.yaml`. See §2.4.
- ✅ **Q8** Cloud has **only `qa` and `dev`** today — no `cloud.prod` or `cloud.uat`. Template ships with just those two cloud sections.
- ✅ **Q-schema** Bundle the schema DDL catalog (`trexone_data/`) **inside** the package as a first-class asset for AI grounding. See §9.
- ✅ **Q-readonly** Read-only SQL guard is mandatory on every query. See §3 — already covered, locked in.
- ⏸️ **Q10** Distribution channel — deferred, not needed yet.

**Still open:**
3. **Hard timeout default?** (Recommend: 30s for `run_select`, configurable per call up to 300s.)
4. **Default row cap?** (Recommend: 1000 rows, configurable per call up to 100k.)
5. **PROD confirmation gate?** Default-on or opt-in? (Recommend: opt-in via env var.)
6. **Audit log SQL text?** (Recommend: default-off, opt-in — PHI risk.)
9. **Read-only Oracle user template** — draft `sql/create_oraflow_readonly_user.sql`?

---

## 9. TL;DR

**Yes, all three pieces work and they compose cleanly:**

- **Mapping**: `(tier, deployment)` -> TOML section inside `~/.oraflow/credentials.toml`, with per-env overrides when needed.
- **SELECT-only**: 7 layers, but the *real* one is `ALTER SESSION SET ISOLATION_LEVEL = READ ONLY` on every connection — the DB itself refuses writes regardless of what our parser thinks. Plus existing AST guard, plus row caps, plus session timeout, plus audit log.
- **Distribution**: Python core (MCP server) is the product; VS Code & IntelliJ extensions are thin shells that call it. Teammates run `oraflow init`, type their passwords once into the OS keychain, and Copilot can immediately do `run_select(domain="ndcq13", role="oltp", sql="SELECT ...")` with full safety.

**Foundation-first build order: steps 1–9 in §6 are the MVP, all backend Python, no IDE work needed.** Say which open decisions in §7 you want to lock in and I'll start with step 1 (multi-file TNS loader).

