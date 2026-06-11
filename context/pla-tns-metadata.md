# OraFlow — TNS Names & Environment Metadata Plan

**Status:** Historical planning note. Current implementation loads explicit and bundled TNS files together; it no longer searches machine-level `TNS_ADMIN`, `ORACLE_HOME`, or `PATH`.
**Scope:** How to organize TNS aliases and the richer environment metadata implied by the OpsDashboard exports, so OraFlow can answer "where is QA01?" / "what's the OLAP for NDC PROD ahdp01?" / "give me the prod CarelonRx app servers" without humans hand-mapping things.
**Do not modify yet** — this complements (does not replace) [`pla.md`](pla.md).

---

## 1. Current State

### 1.1 TNS files on disk
| File | Size | Style | Purpose (apparent) |
|---|---|---|---|
| [`tnsnames.ora`](tnsnames.ora) | ~10.6k lines | `CUSTOMER-ENV.SID_TOKEN=` aliases, FQDN hosts (`anaconda-admin…`, `bushmaster-prod…`), `SID=` form | On-prem catalog from Toad / Instant Client |
| [`cloud-tnsnames.ora`](cloud-tnsnames.ora) | ~2.3k lines | Lower-case aliases (`txndcq16`, `txpdpl01`), IPs + OCI hostnames, `SERVICE_NAME=PXxxx…oraclevcn.com`, multi-address load-balanced | OCI cloud OLTP catalog |
| [`oracle-network/admin/tnsnames.ora`](oracle-network/admin/tnsnames.ora) + `cloud-tnsnames.ora` | copies | Same | Repo-shipped `TNS_ADMIN` so the MCP server is portable |
| [`oracle-network/admin/sqlnet.ora`](oracle-network/admin/sqlnet.ora) | small | Oracle client config | Pinned alongside the TNS files |
| `*.bak` siblings | — | — | Manual snapshots; should be ignored |

The two main files **overlap** (e.g. `19CDB` is defined in both, with different descriptors). Today only **one** file is loaded — see §1.2.

### 1.2 How OraFlow consumes TNS today
- [`config.resolve_tnsnames_paths`](src/oraflow/config.py) loads explicit `ORAFLOW_TNSNAMES_PATHS` first, then explicit/bundled repo TNS files. The VS Code extension sets `ORAFLOW_TNSNAMES_PATHS` to the bundled `tnsnames.ora` and `cloud-tnsnames.ora`.
- Discovery order is explicit/bundled only: `ORAFLOW_TNSNAMES_PATHS` → `ORAFLOW_TNSNAMES_PATH` → `ORAFLOW_TNS_ADMIN/tnsnames.ora` → repo/bundled `oracle-network/admin` → workspace-root TNS files.
- [`tns.parse_tnsnames`](src/oraflow/tns.py) parses one file into [`TnsEntry`](src/oraflow/models.py) with: `alias`, `descriptor`, `hosts[]`, `port`, `sid`, `service_name`, `customer`, `environment`, `sid_token`, `host_group`, `duplicate_alias`, `source_path`.
- `customer` / `environment` are inferred only from the alias text (`CUSTOMER-ENV.SID` shape); aliases like `txndcq16` or `19CDB` get **no** classification.
- [`TnsCatalog.search`](src/oraflow/tns.py) supports filtering by `environment`, `customer`, `host_group` plus `rapidfuzz` ranking. Filters are exposed via `search_tns` in [`server.py`](src/oraflow/server.py).
- Credentials are entirely separate, in [`credentials.py`](src/oraflow/credentials.py) / `~/.oraflow/credentials.toml`, keyed by TOML profile sections such as `ONPREM.PROD` and `CLOUD.QA`.

### 1.3 Implication
OraFlow currently has **no awareness** that:
- `tnsnames.ora` and `cloud-tnsnames.ora` represent two **deployment targets** of the same logical environments.
- A TNS alias like `txndcq16` is the **OLTP** for the same logical env as the OLAP alias `dwndcq16`.
- "QA01" (NDC) is the **same thing** as `ndcq01` / `PXNDCQ01` / `dwndcq01`.

---

## 2. What the OpsDashboard Adds (vs. tnsnames.ora)

Inspecting [`OpsDashboard/QaCloud`](OpsDashboard/QaCloud), [`OpsDashboard/ProdOnprem`](OpsDashboard/ProdOnprem), [`OpsDashboard/DevCloud`](OpsDashboard/DevCloud), each environment block carries:

| Field | Example | In tnsnames.ora? |
|---|---|---|
| Friendly name | `QA01`, `CARELONRX-PROD`, `CCS-DEV` | partially (encoded in onprem alias prefix only) |
| **Domain code** | `ndcq01`, `crlp01`, `ccsd01` | **No** — but it's the natural join key to TNS |
| **Tier** (file = source of truth) | QA / UAT / Stage / Dev / Prod | inferred from letter only (`q`/`u`/`s`/`d`/`p`/`t`) |
| **Deployment** (file = source of truth) | Cloud vs Onprem | **No** |
| Customer / product | NDC, ARA, CCS, CQS, CRL, AHD, BJC… | partial (full name in onprem alias prefix; missing in cloud aliases) |
| Build / health | `15.2.0.7-…` / `ALERT` / `HTTP_503` | **No** (and user says: stale anyway) |
| Web server(s) | `vmqaerxweb1`, `abrams`, `bradley`, `chaffee`, `challenger` | **No** |
| App server hosts | `vmqaerxapp1..4`, `cyclops-admin…`, `joseph-admin…` | **No** |
| WebLogic port block | `mgmt/http/ajp/https/iiop/tx-rec/tx-stat` (e.g. `7546/8546/…/13546`) | **No** |
| **OLTP DB** (SID + hosts + port) | `PXNDCQ01.…oraclevcn.com` @ `10.169.154.219/.220` | **Yes** (the connection details — and per user, **TNS is the truth here**) |
| **OLAP DW** (SID + host + port) | `dwndcq01` @ `asp-prod.enterpriserx.ndchealth.com:1539` | **Yes** (in TNS) |
| **OLTP↔OLAP pairing** | dashboard pairs `PXNDCQ01` with `dwndcq01` for env `ndcq01` | **No** — not derivable from TNS alone |

### 2.1 Naming-convention decode (validated against the dashboards)
Domain code = **3 letters customer/product** + **1 letter tier** + **2 digits instance**:
- Customer codes seen: `ndc` (NDC, the default product), `ara` (Ara), `ccs`, `cqs`, `adm` (admin/SupportTool), `afs` (AssociatedFood), `ahd` (Ahold), `ahf`, `ahi` (AtriusHealth), `arh` (Appalachian), `avr` (Avera), `avt` (Adventist), `bah` (Banner), `bap` (Baptist), `bbs` (BrookshireBros), `bgy` (BigY), `bjc`, `bmt` (Beaumont), `cch` (ChristianaCare), `ccy` (CookCounty), `chb` (ChaseBrexton), `chp` (CHPHealthSpan), `chs` (ChildrensHospital), `cnh` (Cherokee), `cob` (Coborns), `cov`, `crl` (CarelonRx), `crx` (CerebralRx), `csh` (ChristusSpohn), `csv` (ClinicaSV), `dfc` (DanaFarber), `dhm` (ISMC – Dignity HMO?), `dmz` (PCI), `drt` (Dartmouth), `emh` (EasternMaine), `ezs` (EasyScripts), `fdc` (FoodCity), `fhc` (FloridaHealthCare), `fla` (FletcherAllen), `frv` (Fairview)… (~70+ customer codes total in prod alone).
- Tier letter:
  - `p` = Prod
  - `u` = UAT
  - `s` = Stage
  - `q` = QA
  - `d` = Dev
  - `t` = "PreQA / training" (seen in `ndct01`, `ndct03`, `ndct04` — labelled `PREQA1`/`PREQA3` in dashboard, but file is QaCloud → effectively a sub-tier of QA)
- DB SID prefixes:
  - `PX` = OLTP primary (e.g. `PXNDCQ01`)
  - `PW` = OLTP standby/secondary (seen on QA14, QA37, QA47, DEV16, DEV40 — a few envs report `PWxxx` instead of `dwxxx` in the OLAP slot, which is suspicious; might be data-quality noise the user warned about)
  - `dw` = OLAP/data warehouse
  - `tx` = cloud-tnsnames TNS-alias prefix that *connects* to a `PX*` OLTP service (e.g. `txndcq16` → `SERVICE_NAME=PXNDCQ16…`)
  - `Z*` = onprem TNS-alias suffix in `CUSTOMER-PROD.ZDWxxxP01` — appears to be a "z-prefixed dw" alias for the OLAP DB
  - `txafsp01`, `txahdp01` etc. — onprem prod OLTP aliases follow same `tx<domain>` convention in the cloud file

So the **domain code is the universal join key** between (a) Ops Dashboard rows, (b) cloud TNS aliases (`tx<domain>`, `dw<domain>`), (c) onprem TNS aliases (`CUSTOMER-PROD.ZDW<domain>` for OLAP, plus per-env OLTP aliases).

---

## 3. Options Analysis

### Option A — Single combined `tnsnames.ora` (everything in one file)
**Pros**
- One source for Oracle client and OraFlow.
- Trivial to load (no merge logic).

**Cons**
- Conflicts: aliases like `19CDB`, `txndct04`, etc. exist in both; resolving requires picking a winner per alias.
- Loses the natural deployment grouping; the *only* signal is alias style, which is fragile.
- One huge ~13k-line file is hard to diff/review.
- Doesn't address the missing metadata (tier, deployment, OLTP↔OLAP pairing, app servers).

### Option B — Two files split by deployment (current state)
**Pros**
- Mirrors how Oracle clients elsewhere (Toad, scripts) actually consume them — minimal disruption.
- `cloud-tnsnames.ora` already exists and the cloud aliases use a clearly different convention (`tx*` lower-case), so collisions are rare.
- Each file is independently maintainable by its respective team.

**Cons**
- Oracle client only auto-loads `tnsnames.ora` (one file). OraFlow must learn to merge — but this is a small change.
- Still no tier / deployment / customer / OLTP↔OLAP / app-server overlay.

### Option C — Keep TNS as truth for connections; add a separate metadata overlay
Layer a small, hand- or script-maintained metadata file (YAML preferred for readability; TOML acceptable) over the TNS files. The overlay is keyed by **domain code** (e.g. `ndcq01`) and references TNS aliases by name.

**Pros**
- TNS files stay strictly Oracle-client-compatible; no risk of breaking Toad / sqlplus.
- Clean separation of "how to connect" (TNS) vs. "what is this thing" (metadata).
- Easy to seed automatically by parsing the OpsDashboard dumps once, then trim what's stale.
- Naturally encodes things TNS can't (tier, deployment, app servers, port blocks, OLTP↔OLAP pairing).
- LLM-friendly: small structured doc the model can browse.

**Cons**
- New file to maintain; needs an owner and update process (or a regenerator script).
- Dual sources can drift if the metadata file is treated as authoritative for connection details (we'll explicitly forbid that — TNS wins for host/port/service).

### Option D — Hybrid: split TNS by deployment **and** add the overlay (B + C)
**Pros**
- Best of both: faithful to the existing Oracle workflow *and* gives OraFlow the rich tier/customer/app-server view.
- The overlay's `tns_oltp` / `tns_olap` fields can disambiguate which file an alias lives in (or OraFlow can just merge with deterministic precedence).

**Cons**
- Two artefacts to keep in sync.
- Slightly more code in OraFlow (multi-file loader + metadata loader + join).

### Recommendation: **Option D (hybrid)**
Reasoning: TNS files are the operational reality (Toad, sqlplus, Oracle client all need them) and the user explicitly says TNS is authoritative for connection details. The OpsDashboard data is rich but stale on volatile fields (build/health) and authoritative on stable fields (tier, deployment, customer). A separate overlay lets us capture the stable fields without polluting `tnsnames.ora`, and the split-by-deployment keeps each file mentally simple. Option C alone (keeping a single combined TNS) is acceptable as a fallback if maintaining two TNS files is operationally painful.

---

## 4. Proposed Metadata Schema

**Location:** `oracle-network/environments.yaml` (sits next to the TNS files so `TNS_ADMIN` discovery already finds the directory).

**Top-level shape:**
```yaml
version: 1
defaults:
  oltp_sid_prefix: PX
  olap_sid_prefix: dw
  cloud_oltp_alias_prefix: tx     # cloud-tnsnames.ora aliases for OLTP

customers:                         # 3-letter code → friendly metadata
  ndc: { name: "NDC (default product)" }
  ara: { name: "Ara" }
  crl: { name: "CarelonRx" }
  ahd: { name: "Ahold" }
  bjc: { name: "BJC" }
  # … one entry per code

environments:                      # keyed by domain code (lower-case)
  ndcq01:
    name: QA01                     # the dashboard "Name:" field
    customer: ndc
    tier: qa                       # prod | uat | stage | qa | dev | preqa
    deployment: cloud              # cloud | onprem
    weblogic:
      web_servers: [vmqaerxweb1]
      app_servers: [vmqaerxapp1, vmqaerxapp2]
      ports: { mgmt: 7546, http: 8546, ajp: 9546,
               https: 10546, iiop: 11546, tx_rec: 12546, tx_stat: 13546 }
    oltp:
      tns_alias: txndcq01          # alias to find in cloud-tnsnames.ora
      service_name: PXNDCQ01.ocisubnetoraex.ocivneteastusm.oraclevcn.com
    olap:
      tns_alias: dwndcq01          # alias to find (likely tnsnames.ora)
      sid: dwndcq01
    notes: "Seeded from OpsDashboard 2025-… ; OLTP host/port should be read from TNS."
```

**Concrete worked example (ndcq01 / NDC QA01):**
```yaml
environments:
  ndcq01:
    name: QA01
    customer: ndc
    tier: qa
    deployment: cloud
    weblogic:
      web_servers: [vmqaerxweb1]
      app_servers: [vmqaerxapp1, vmqaerxapp2]
      ports:
        mgmt: 7546
        http: 8546
        ajp: 9546
        https: 10546
        iiop: 11546
        tx_rec: 12546
        tx_stat: 13546
    oltp:
      tns_alias: txndcq01
      service_name: PXNDCQ01.ocisubnetoraex.ocivneteastusm.oraclevcn.com
      # host/port intentionally omitted — resolve via cloud-tnsnames.ora
    olap:
      tns_alias: dwndcq01
      sid: dwndcq01
      # host (asp-prod.enterpriserx.ndchealth.com) + port (1539) come from tnsnames.ora
```

**Key design rules:**
1. **TNS is authoritative for host/port/service.** The overlay only references aliases; it never re-states connection details (except optional `service_name` / `sid` for cross-checking).
2. **Domain code is the join key** everywhere.
3. **Customer codes** live in their own table so we don't repeat full names per env.
4. **Tier and deployment are required** and validated against an enum.
5. **`weblogic.*` and `notes` are optional** — leaving room to fill in only what's accurate.
6. **No build/version field** — too volatile and per-user-warning, stale on the dashboard. Look that up live elsewhere if needed.

---

## 5. Implementation Steps (for the future implementer — not now)

1. **TNS loader: done.**
  [`config.py`](src/oraflow/config.py) now exposes `resolve_tnsnames_paths()` and prioritizes `ORAFLOW_TNSNAMES_PATHS` for extension-managed bundled files. [`tns.py`](src/oraflow/tns.py) loads and merges multiple paths, tagging each [`TnsEntry`](src/oraflow/models.py) with its source.

2. **Add an environments module.** New file `src/oraflow/environments.py` with:
   - Pydantic models: `CustomerInfo`, `WebLogicInfo`, `DbRef`, `EnvironmentInfo`, `EnvironmentCatalog`.
   - Loader: `EnvironmentCatalog.load(path)` parsing the YAML (add `pyyaml` to deps).
   - Resolver helpers: `find_by_domain(code)`, `find_by_alias(alias)` (reverse lookup OLTP/OLAP → env), `filter(tier=…, deployment=…, customer=…)`.
   - Cross-link helper: `resolve_tns(env, role="oltp")` returns the `TnsEntry` from the catalog, raising if the alias isn't present.

3. **Settings & discovery.** Add `environments_path` to [`Settings`](src/oraflow/config.py); default to `<TNS_ADMIN>/environments.yaml`. Surface it in [`config_info`](src/oraflow/config.py) with warnings if missing/parse-failed.

4. **Wire into existing tooling.** In [`tns.py`](src/oraflow/tns.py)'s [`TnsCatalog.search`](src/oraflow/tns.py), allow joining against the env catalog so `tier`/`deployment`/`customer` filters become exact (currently they're string-substring on alias-derived fields).

5. **New MCP tools** in [`server.py`](src/oraflow/server.py):
   - `list_environments(tier?, deployment?, customer?, limit)` → list of `EnvironmentInfo`.
   - `get_environment(domain_or_name)` → single `EnvironmentInfo` with embedded resolved OLTP / OLAP `TnsEntry`s.
   - `find_environment_for_alias(alias_or_key)` → reverse lookup: "what env owns `txndcq16`?".
  - Optional later: environment-aware target selection that resolves domain -> role -> TNS alias -> active target metadata.

6. **Seed script.** A one-shot `scripts/seed_environments_from_opsdashboard.py` that reads each `OpsDashboard/*` dump, parses the repeating record blocks (`Name:` … `Domain:` … blank-line delimited), classifies tier/deployment from the source filename, and writes (or merges into) `oracle-network/environments.yaml`. After seeding, the file becomes hand-curated; the script is keep-around-but-rarely-run.

7. **Tests.**
   - Parser test for one of the OpsDashboard files (verify ndcq01 → QA01 / cloud / qa / NDC).
   - Round-trip test: load env catalog + TNS catalog, assert every env's `oltp.tns_alias` / `olap.tns_alias` resolves (warn on missing).
   - Filter tests for the new MCP tools.

8. **Docs.** Update [`README.md`](README.md) with the env-overlay concept, sample queries (`list_environments(tier="prod", customer="crl")`), and the rule that TNS files remain the source of truth for connection details.

---

## 6. Open Questions (please decide)

1. **Two TNS files or one?** Option D (two) recommended. Confirm or pick Option C (merge cloud into `tnsnames.ora`).
2. **YAML vs. TOML vs. JSON** for the overlay? Recommend YAML for readability; TOML if you'd rather avoid `pyyaml`.
3. **Where does the overlay live?** `oracle-network/environments.yaml` (recommended — discovered via `TNS_ADMIN`) vs. workspace-root vs. `src/oraflow/data/`.
4. **How should we treat the stale OpsDashboard fields** (build version, ALERT/ONLINE, weblogic ports)? Recommend: import once, keep tier/deployment/customer/app-servers/ports, **drop build/health** (re-fetch live if ever needed).
5. **Cross-file alias collisions** (e.g. `19CDB` in both TNS files) — which wins? Recommend: explicit precedence by load order, plus surface both via the disambiguating `@source` key suffix.
6. **Customer codes ↔ full names mapping** — do you have an authoritative list, or should we infer from the dashboard `Name:` field (`ASSOCIATEDFOOD-PROD` → `afs` / "Associated Food")?
7. **PreQA tier** (`ndct01`, `ndct03` show up under QA dashboards) — model as `tier: preqa` or fold into `qa` with a `subtier: preqa`?
8. **OLTP standby `PWxxx` SIDs** (seen on QA14, QA37, QA47, DEV16, DEV27, DEV40, DEV45, DEV46) — represent as a third `oltp_standby` slot, or ignore?
9. **Credential profile linkage** — `EnvironmentInfo` should resolve to TOML profiles such as `ONPREM.QA` or `CLOUD.DEV`.
10. **Ownership** — who maintains `environments.yaml` going forward? If nobody, keep the seed script and rerun on demand instead of hand-editing.

---

## 7. TL;DR Recommendation

Adopt **Option D**: keep `tnsnames.ora` (onprem) and `cloud-tnsnames.ora` (cloud) as-is, teach OraFlow to load both, and add `oracle-network/environments.yaml` keyed by **domain code** that overlays tier / deployment / customer / weblogic / OLTP-alias / OLAP-alias. Seed the YAML once from the `OpsDashboard/` dumps, then maintain by hand. TNS files remain the only source of truth for host/port/service.

