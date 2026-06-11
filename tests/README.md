# OraFlow test guide

This directory contains the regression suite for OraFlow's read-only Oracle execution and JiraFlow evidence pipelines.

## How to run

```powershell
cd C:\Developer\Workspace\EnterpriseRx\OraFlow
uv run pytest
uv run ruff check src/oraflow tests
```

The tests are local and deterministic. They do **not** require live Oracle credentials, VPN, or database access.

## What is covered

| Test file | Coverage |
| --- | --- |
| `test_credentials.py` | Credential profile parsing and profile lookup behavior without exposing passwords. |
| `test_customer_target.py` | Friendly customer catalog parsing, active-target state, environment/layer/deployment resolution. |
| `test_db_unit.py` | DB helper behavior and the python-oracledb cloud path: `_json_value`, `_redact_secret`, `_use_sqlplus12_first`, `_needs_sqlplus_fallback`, `_dsn_with_timeout`, and `ConnectionManager.run_query`. |
| `test_help.py` | Help-topic lookup and packaged help metadata. |
| `test_jira.py` | Jira credentials, REST client, ADF flattening, JSON-only evidence writer, attachment caps, related-ticket discovery/fetch, similar-ticket JQL, and JQL help topics. |
| `test_pipeline.py` | Mocked end-to-end SQL\*Plus path: `_run_sqlplus_csv`, sentinel framing, password redaction, script authoring, validation, and markdown output formatting. |
| `test_safety.py` | Core SELECT-only safety validator allow/block behavior. |
| `test_safety_extended.py` | Broader Oracle SELECT grammar and write/admin rejection matrix: joins, CTEs, hierarchy, pivot, set operators, JSON functions, DML/DDL/PLSQL, lock/transaction control, blocked packages/schemas. |
| `test_sqlfile.py` | SQL script splitter: normal strings, Oracle q-quoted strings, inline comments after semicolons, block comments, SQL\*Plus directives, trailing statements. |
| `test_sqlplus_csv.py` | Pure SQL\*Plus CSV parser: NUMBER-first rows, multiline quoted fields, CLOB-sized values, UTF-8, NULL fields, timestamps with time zone, missing sentinels, truncation. |
| `test_tns.py` | TNS parsing, duplicate handling, deployment source tagging, alias lookup. |

## Execution paths under test

OraFlow has two database execution paths:

1. **python-oracledb path** — used for cloud DEV/QA and most modern aliases.
   - Covered by `test_db_unit.py`.
   - Verifies `SET TRANSACTION READ ONLY`, call timeout, row-cap truncation detection, type normalization, and validation-before-execute.
2. **SQL\*Plus 12.2 fallback path** — used first for on-prem PROD and as a fallback for selected legacy verifier errors.
   - Covered by `test_sqlplus_csv.py` and `test_pipeline.py`.
   - Verifies sentinel-framed CSV parsing, large NUMBER display, CLOB/long text, UTF-8, NULLs, timestamp formatting, password redaction, and loud failures for partial output.

JiraFlow is a separate read-only evidence path covered by `test_jira.py`. It uses `httpx.MockTransport`, so tests never connect to Atlassian.

## Live smoke tests are separate

The automated tests mock Oracle connectivity. They prove the code paths but not a specific network/database/profile combination.

After rebuilding and reinstalling the VSIX, run live smoke checks from Copilot/OraFlow:

1. Ping a known cloud target such as `cloud dev 46`.
2. Run `SELECT 1 AS one FROM dual`.
3. Run a tiny multi-statement SELECT-only script with inline comments and string semicolons.
4. Confirm a write attempt such as `UPDATE ...` is rejected before execution.
5. If DW access matters, ping a non-PROD DW alias such as `QA11.ZDWNDCQ11` with `ONPREM.QA`, then run `SELECT 1 AS one FROM dual` if ping succeeds.

PROD live smoke checks require explicit PROD confirmation and should start with ping only.

## When adding tests

Add tests near the layer they protect:

- Safety grammar or blocklist change -> `test_safety.py` / `test_safety_extended.py`.
- Script parsing/splitting change -> `test_sqlfile.py`.
- SQL\*Plus output parsing change -> `test_sqlplus_csv.py`.
- End-to-end SQL\*Plus behavior -> `test_pipeline.py`.
- python-oracledb/cloud path -> `test_db_unit.py`.
- Jira client/evidence/related-ticket behavior -> `test_jira.py`.
- Target/TNS/customer behavior -> `test_tns.py` / `test_customer_target.py`.

