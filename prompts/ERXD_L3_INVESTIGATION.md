# In-Depth L3 Investigation (OraFlow-integrated)
> **Provide only the ERXD key when you use this prompt.** If the current user message includes an ERXD key, use that key. Otherwise set the ticket key once on the next line, then leave the rest of the prompt alone. Wherever you see `{{TICKET}}` below, substitute the selected ticket key (e.g. `{{TICKET}}_diagnostic` becomes `ERXD-73403_diagnostic`). Ask for a ticket key only if neither the user message nor the `TICKET:` line contains a real ERXD key.
```
TICKET: ERXD-XXXX
```
> **Step 0 - pull the ticket via OraFlow before anything else.** Call `jira_get_ticket("{{TICKET}}")`. OraFlow writes `OraFlow/jira/{{TICKET}}/issue.json`, `comments.json`, `summary.md`, and `attachments/` to disk. Read **all** of those files - never skim. Do not ask the user for the ticket body, the customer name, or attachments; OraFlow already has them. If `jira_get_ticket` fails, run `jira_credentials_doctor` and stop until creds are in place.
> **All SQL execution and evidence capture is performed by the OraFlow MCP server - never paste raw passwords into chat, never hand-edit files under `OraFlow/db/scripts/` or `OraFlow/db/outputs/`.**

## Natural-language trigger
If the user says something like **"ERXD-12345 assigned to me"**, **"investigate ERXD-12345"**, or **"run the L3 flow for ERXD-12345"**, treat the ERXD key as the only required input. Do not ask the user to pre-supply database alias, schema, customer, app server, Splunk query, batch name, or app-option values. First retrieve Jira evidence and classify the ticket: L3/customer incident, Bug, Story/enhancement, Task, Spike/research, QA follow-up, incomplete-information request, or process-only work. Then decide which evidence lanes are actually needed: Jira-only, code/docs, DB, app options/config, Splunk/app logs, server logs, batch/job logs, integration/vendor logs, or customer clarification.

## Context
I am investigating Jira ticket **{{TICKET}}**. Database access is provided exclusively through the **OraFlow MCP server** (Oracle, schema: `trexone_data`). For customer-data L3 work, the customer's PROD database is usually the evidence target because non-PROD environments do not contain the customer's real data. Do not assume DB evidence is always required, and do not ask the user for DB details up front. Infer customer, environment, component, identifiers, timestamps, app options, and target candidates from Jira, attachments, docs, source, and OraFlow discovery first. Ask the user only when a required target or evidence source remains ambiguous.

## Evidence lane decision gate
After Jira fetch and ticket classification, choose the lightest complete evidence plan:

- **Jira-only/process lane:** use when the ticket is incomplete, duplicate/process-only, assignment/status clarification, or lacks enough customer facts to investigate. Do not bind DB.
- **Code/docs lane:** use when expected behavior, workflow rules, validation, UI messaging, or a likely code gate can be proven without customer data. Add DB only if current/historical customer state is needed.
- **Customer PROD DB lane:** use when the ticket needs current customer data, historical/audit reconstruction, config rows, record identity, Rx/order/patient/product/workflow state, or DB-backed root-cause proof.
- **App options/config lane:** use when behavior depends on app options, facility/data-group hierarchy, feature flags, customer setup, product rules, workflow flags, integration setup, or enablement dates. First derive from Jira/attachments/docs/source/DB; ask the user only if config cannot be inferred or queried safely.
- **Splunk/app-server log lane:** use when symptoms involve generic UI errors, HTTP failures, stack traces, timeouts, `ORA-01013`, intermittent failures, request IDs, timestamps, user/session-specific failures, service exceptions, or anything where DB state alone cannot prove the runtime mechanism. If this evidence is needed and not available through tools/files, ask the user for the exact Splunk/app log extract needed: customer/store, timestamp window with timezone, user or workstation if known, server/environment, request/correlation ID if available, and error text.
- **Batch/job/server log lane:** use when the issue involves scheduled jobs, queues, imports/exports, EDI/NCPDP/PPI/vendor feeds, inventory/background processing, nightly loads, failures after a batch window, or data changes not attributable to user action. Ask for batch/job name, run window, server, scheduler status, and log excerpt only after Jira/source/DB cannot identify it.
- **External/vendor/customer lane:** use when the likely proof is outside EnterpriseRx: payer/vendor responses, device logs, customer workflow screenshots, network events, or third-party payloads. State exactly what is needed and why.

In the final report, include which lanes were used, which were not needed, and any external evidence that is still required.
## OraFlow Operating Contract (read first, every time)
1. **Pull the Jira ticket first.** `jira_get_ticket("{{TICKET}}")` writes the full evidence trail (JSON issue body, all comments, all attachments, human-readable `summary.md`) under `OraFlow/jira/{{TICKET}}/`. Read every file in that folder before authoring SQL. The ticket already tells you the customer, NPI, Rx number, dates, screenshots, BSA notes, and prior diagnostics.
2. **Inspect related Jira context.** Call `jira_list_related_tickets("{{TICKET}}")` after the primary fetch. Review formal issue links, parent/subtask links, and ticket-key mentions in comments/text. Fetch only relevant related tickets with `jira_fetch_related_tickets(parent_key="{{TICKET}}", related_keys=[...])`; they land under `OraFlow/jira/{{TICKET}}/related/<KEY>/`. If direct links are not enough, call `jira_find_similar_tickets("{{TICKET}}")` using customer, NPI, Rx, error text, labels, and component terms. If writing custom JQL by hand, call `jira_jql_help("l3")` or `jira_jql_help("escaping")` first, include `project = ERXD`, use `ORDER BY updated DESC`, start with `max_results=20`, and fetch only selected relevant tickets. If interpreting Epic/Initiative/parent-child hierarchy, Story/Task/Bug/status workflow, or whether a related ticket has enough evidence to trust, call `jira_jql_help("hierarchy")`, `jira_jql_help("process")`, or `jira_jql_help("ticket_quality")`. Do not recursively fetch unrelated tickets or attachment trees without a reason.
3. **Bind the customer's PROD target only when DB evidence is needed.** Use Jira/custom fields/attachments/customer names to infer customer and environment. Use `list_customers` + `resolve_target(customer, env="prod", layer=...)` (or `search_tns`) to identify the alias, then `set_active_target` with `{customer, env="prod", layer, deployment}` so `ping_active_target` and `run_active_target_script` use the exact pinned DB/profile. If multiple safe candidates remain, list them and ask the user to choose. Never default to DEV/QA for customer-data L3 evidence - they do not have the customer's data.
4. **Confirm PROD identity before any reads.** Call `ping_active_target`. **All four** of `database_name`, `instance_name`, `service_name`, and `version` must come back as real values matching the customer's documented identity. If any field is missing, if any equals a column-name literal (e.g. `DATABASE_NAME`, `INSTANCE_NAME`, `SERVICE_NAME`, `VERSION`), or if the response includes `header_leak_suspected` in `error` - **STOP. Do not run any reads.** That signals a SQL*Plus parser regression or a bad alias; re-resolve the target before continuing.
5. **If `ping_active_target` times out, do not retry blindly.** The response includes a `siblings` list of alternate endpoints under the same customer + environment + host_group (e.g., Kinney PROD has `TXKINP01-55` and `TXKINP01-67`). Surface those siblings to the user; ask which to try; never auto-fail over. You can also call `oraflow_search_siblings(alias_or_key)` explicitly to enumerate them.
6. **All SQL is delivered as an OraFlow script artifact, not inline.** Author with `author_sql_script(name='{{TICKET}}_diagnostic', sql_body=..., description=...)` then execute with `run_active_target_script(script_path=...)` (or explicit `run_sql_script` only when alias/profile are intentionally supplied). Read evidence via `read_script_results(...)` (structured JSON sidecar, **source of truth**) - fall back to `read_script_output(...)` only for the human-readable text view. The text file is intentionally lossy; the JSON sidecar is the audit record. Never reconstruct rows from chat.
7. **Probe-and-narrow, not omnibus.** Author small focused scripts (3-5 statements: identity -> one example -> counts -> correlation) instead of broad omnibus diagnostics. The default `query_timeout_s` is **240s** - if a probe finishes near that ceiling, the text output now emits an explicit `!! WARNING: elapsed = N% of timeout` line. Narrow the query rather than blindly raising the timeout.
8. **Evidence layout is fixed.** Each script run produces:
   - `OraFlow/db/scripts/{{TICKET}}/{{TICKET}}_diagnostic.sql` - the executed script
   - `OraFlow/db/outputs/{{TICKET}}/{{TICKET}}_diagnostic_output.txt` - human-readable; includes a loud `!! WARNING` if `row_count > 0` but rows are missing, or if elapsed is >80% of the timeout
   - `OraFlow/db/outputs/{{TICKET}}/{{TICKET}}_diagnostic_output.json` - structured per-statement payload (columns, rows, row_count, truncated, elapsed_ms, timeout_ms) - **source of truth**
   - `OraFlow/db/_audit/runs.jsonl` - append-only audit row. **Both** successes (`status="ok"`) and failures (`status="failed"`) are recorded; failed rows include `error_class`, `error_message` (pre-redacted), `debug_log_path`, and `sibling_aliases`.
   - `OraFlow/db/logs/sqlplus/sqlplus_*.log` - only if the SQL*Plus 12.2 fallback path hit a sentinel/parse anomaly or a timeout; raw partial sqlplus output with the password redacted.
   - `OraFlow/jira/{{TICKET}}/` - the Jira evidence written by `jira_get_ticket`, plus `related_index.json`, `related_summary.md`, optional `similar_tickets.json`, and optional nested `related/<KEY>/` folders.
9. **Read-only is enforced backend-side.** The validator rejects DML/DDL before execution and `SET TRANSACTION READ ONLY` is wrapped around every statement. Any `UPDATE` / `INSERT` / `DELETE` / `MERGE` / `TRUNCATE` / `ALTER` / `DROP` will fail at `author_sql_script` time - design the diagnostic accordingly.
10. **Schema/DDL lookups go through OraFlow first.** Use `describe_schema_table(schema, table)` and `search_schema(query)` against the bundled catalog (`trexone_data`, `trexone_aud_data`, `trexone_dw_data`, `trexone_ods_data`). Use `Context/erx_tables/` or source DDL only as a fallback when something appears missing from the catalog. If bundled schema tools are not visible, do not substitute live `describe_table`, live `list_tables`, or live `list_views`; stop and report the missing schema tool group or use repo DDL/source files as the fallback.
## Inputs (read ALL of these fully - do not skim)
1. **OraFlow Jira evidence** at `OraFlow/jira/{{TICKET}}/` (written by `jira_get_ticket` in Step 0).
   - `summary.md` - start here; quick orientation
   - `issue.json` - structured fields, custom fields, changelog (status history), labels, components, NPI/customer/Rx in custom fields
   - `comments.json` - every comment chronologically, with `created`, `author.displayName`, body flattened from ADF
   - `attachments/` - every attachment Jira had; read CSVs/docx/txt/data dumps; for screenshots and binary blobs, note that they exist and rely on text content where present
   - `related_index.json` / `related_summary.md` - formal issue links, parent/subtasks, text references, and suggested JQL
   - `related/<KEY>/` - fetched related ticket evidence when relevant
   - `similar_tickets.json` - JQL-similar candidates when direct links are not enough
   - Extract: description, every comment chronologically with dates/authors, affected versions, customer(s), frequency, impact, attachments, linked issues, labels, assignee/reporter, status history.
2. **Workflow / domain table DDLs** via OraFlow schema catalog (`describe_schema_table`, `search_schema`); fall back to `Context/erx_tables/` only if a table is missing from the catalog. Read the DDL for every table relevant to the affected area (workflow, verification, dispensing, billing, ERP, Contact Manager, etc.). Understand columns, FKs, partitioning, history/audit table availability, nullable fields.
3. **EnterpriseRx documentation PDFs** in `Context/` (Admin Guide, User Guide, Data and Reporting Center Guide) - find sections relevant to the ticket's component and compare documented/expected behavior to code behavior and observed data. Required before concluding `As Designed`, `Bug`, `Application Configuration`, `User Training / Error`, or any other closure category.
4. **Source code** - trace every code path the ticket touches end-to-end:
   - Start from the UI panel / screen mentioned
   - Follow the service / boundary layer
   - Follow into PostConditions / workflow engine if applicable
   - Follow PL/SQL packages if the path crosses into the DB
   - Read the actual implementation, never guess at behavior
   - Identify every decision gate, default value, persisted flag, audit write, and downstream batch/contact/event selection step.
5. **External runtime evidence when needed** - if Jira/source/DB cannot prove the runtime mechanism, identify exactly what must be checked outside OraFlow:
   - Splunk or app-server logs: timestamp window, timezone, customer/store/facility, user/workstation, request/correlation ID, server/environment, and error text.
   - Server logs: application server, service/component, deployment/env, thread/request ID, exception stack, timeout/cancel evidence.
   - Batch/job logs: job name, scheduler/run ID, run window, server, status, input/output files, reject/error counts.
   - Integration/vendor logs: interface name, partner/vendor, message/control IDs, payload timestamps, response/error codes.
   - App options/config: option names, hierarchy level, effective facility/data group/customer, expected value, actual value, and source of truth.
## Investigation Approach
1. Build a **timeline** of when the issue was reported, by whom, and what changed in each comment (from `OraFlow/jira/{{TICKET}}/comments.json`).
2. Separate **customer/Jira assertions**, **current PROD data** (via OraFlow against the bound customer PROD target), **historical/audit data** (via OraFlow against the same PROD target), and **code-proven behavior**. Do not collapse these into one conclusion until each is independently proven. Non-PROD environments cannot answer "what did this customer's data look like" - do not try to substitute.
3. Identify the **affected customer(s)** and decide whether app option/config evidence is relevant. Pull app option configuration from attachments, docs, source defaults, or DB evidence when needed (run via `run_active_target_script` / `run_sql_script`, never inline). If the exact option/source cannot be found, ask for the missing config details explicitly.
4. Identify **the configuration combination** that exposes the behavior when applicable (which app options, facility hierarchy rows, feature toggles, product rules, patient/Rx/order state, workflow flags). If config is not relevant, say so briefly.
5. Map the **record identity chain** before interpreting results:
   - For Rx issues, distinguish display Rx number, `RX_RECORD_NUM`, `RX_FILL_SEQ`, reassigned/linked Rx rows, related renewal rows, follow-on/new Rx rows, patient, product, GCN/GPI, order, item, workflow process, and contact-event identities.
   - For workflow/order issues, distinguish current item, sibling items, saved/locked items, process instance rows, and `WF_USER_ITEM` rows.
   - Prove whether two identifiers refer to the same DB entity or only related entities.
6. Trace the **code flow** step-by-step with specific file paths and line numbers.
7. Build a **decision-gate matrix** from the code:
   - Gate name, source file/line, required input columns/fields, pass/fail value in the example, persisted output, and the OraFlow script + Q-index that proves it.
   - Include negative gates/blockers, not just the happy path.
8. Drive to a **concrete root cause** whenever technically possible. As the development/L3 owner, do not stop at symptoms, missing current-state fields, or "needs further review" if source code, DB state, history, or docs can answer it. The root cause should name the exact causal chain: triggering event/input -> code gate/calculation/query -> persisted state/output -> customer-visible behavior.
9. If a concrete root cause cannot be fully proven with available evidence, form a **root-cause hypothesis** that explains:
   - Why it happens
   - Why it only happens for these customers / this data state
   - Why it cannot be reproduced in QA (if applicable)
   - What current DB signature would prove it (write the exact OraFlow query)
   - What historical/sell-time/audit signature would prove it
   - The exact remaining proof needed and where it should come from
10. Write **diagnostic SQL** as a single OraFlow script artifact (see SQL Rules below) and execute it against the bound target.
11. If current data conflicts with the Jira claim, author a follow-up script (`{{TICKET}}_audit_history.sql`) against audit/history/version tables to reconstruct the state at the time the code made the decision. The bound target stays on the customer's PROD; never silently swap to DEV/QA mid-investigation.
12. Check **EnterpriseRx documentation and documented business behavior** for the affected feature, and explicitly state whether observed behavior matches or contradicts docs.
13. List **related tickets** and check if any prior fix introduced this regression.
14. List **open questions** requiring data, BSA, tech-lead, customer input, Splunk/app logs, server logs, batch/job logs, integration/vendor logs, or app-option/config confirmation. Open questions should not replace root-cause work; they should be limited to items that truly cannot be proven from Jira, code, DB, history, docs, attachments, or available logs.
## Root Cause Standard
- Treat L3/dev investigation as the final technical escalation. Continue until the concrete cause is identified if the evidence exists in code, DB (via OraFlow), history/audit, docs, or attachments.
- A valid root cause is not just the visible symptom. It must explain the mechanism that produced the symptom.
- Every root-cause statement must reference the exact OraFlow evidence row (script name + Q-index + row index) that proves each link in the chain.
- If the issue is **As Designed**, prove the design from EnterpriseRx documentation and/or explicit code/business rules, then explain why the customer expectation differed.
- If the issue is a **Bug**, identify the exact incorrect code path, query, condition, transaction boundary, or persistence behavior and the expected correction.
- If the issue is **Application Configuration**, identify the exact missing/incorrect effective config row and the facility/customer hierarchy where it applies.
- If the issue is **Data Error / Conversion** or **Operational**, identify the exact data state, historical transition, workflow action, or operational sequence that caused the behavior.
- If only a hypothesis is possible, label it clearly as `Root-Cause Hypothesis`, include supporting and contradicting evidence, and list the exact proof needed (and the exact OraFlow query that would produce it) to promote it to confirmed root cause.
## Documentation / Expected Behavior Check
- Before selecting Resolution or Problem Category labels, verify expected behavior against the relevant EnterpriseRx documentation in `Context/` and any applicable source-code comments/business constants.
- Quote or summarize the relevant documentation section in the analysis, with enough detail to support whether behavior is expected/as-designed or contradictory.
- If documentation and code disagree, call that out explicitly as part of the root-cause analysis.
- If documentation is silent, say so and rely on code/data evidence, but do not claim `As Designed` solely because the current code behaves that way.
## Domain-Specific Checklists
Use these only when the ticket touches the relevant area; keep the final analysis generic and evidence-driven.
### Runtime Errors / Splunk / App Server Logs
- If the symptom is a generic UI error, HTTP 4xx/5xx, timeout, `ORA-01013`, service exception, intermittent failure, or stack trace, determine whether DB state alone can prove the mechanism.
- If logs are needed, ask for the smallest useful log package: customer/store/facility, timestamp window with timezone, user/workstation, server/environment, request/correlation ID if known, and exact error text.
- Use logs to prove request path, exception class, timeout/cancel source, thread/service, payload identifiers, and whether the DB query, app code, vendor call, or batch step was the failing boundary.
- If logs are unavailable, label the runtime mechanism as a hypothesis and state the exact Splunk/server-log query or fields needed to confirm it.

### App Options / Configuration
- Prove effective app options at the correct hierarchy level: enterprise/customer, facility, data group, store, user/role, workflow, product, payer, vendor, or integration setup.
- Read source defaults/constants and documentation before concluding the customer configuration is wrong.
- If the option table/name is unknown, find it from source/schema/docs first; ask the user only for values or screenshots that cannot be safely queried.
- Include option name, effective level, actual value, expected value, source, and whether a restart/cache refresh/batch reload is required.

### Batch Jobs / Queues / Integrations
- Use this for nightly loads, scheduled jobs, queues, vendor imports/exports, EDI/NCPDP/PPI feeds, reporting refreshes, and data changes outside direct user save flows.
- Identify job/interface name, scheduler/run ID, run window, server, input/output files, status, reject/error counts, and downstream tables/events.
- Use DB evidence for persisted results and ask for scheduler/server/vendor logs only when the transition cannot be reconstructed from DB/audit tables.

### ERP / Proactive RRR / RxSmartFill
- Prove effective app options at the relevant facility/data-group level, including configured values and defaults read by code.
- Calculate and compare ordinary target date, proactive target date, and batch/lookahead pickup date.
- Verify patient ERP enrollment, Rx ERP enrollment, Rx status, product inclusion/exclusion, exclusion reason, refills/quantity remaining, linked/reassigned Rx, same-GCN/GPI bioequivalent/profile blockers, and Contact Manager/PPI creation.
- Check persisted state fields such as `ERP_TARGET_DATE`, `ERP_ORIGINAL_TARGET_DATE`, `ERP_ENROLLMENT_CODE_NUM`, `IS_PROACTIVE_RRR`, `REASSIGNED_RX_NUM`, `PROHIBIT_RENEWAL_REQUEST`, and related audit rows.
- Reconstruct sell-time state, not just current state. Changing config or Rx state after sell/release may not recompute persisted ERP target/proactive flags.
- If package functions drive eligibility (for example quantity remaining), either call the same function if available or reproduce its formula from code/DDL and document that it is package-equivalent/approximate.
- For related RRR/new-Rx chains, prove whether the customer-cited renewal/request row is the original Rx row, a separate denied renewal row, or a follow-on active Rx.
### Workflow / PostCondition / Batch Advancement
- Identify whether the code runs before the main service call, inside the service transaction, or as a postcondition after the main transaction commits.
- For batch advancement, prove the full item list and classify current item vs saved/locked sibling items.
- Validate workflow completion against `WF_USER_ITEM` when advancement depends on current-step completion.
- If one item is unsafe/incomplete, consider whether valid items should continue while unsafe items are skipped/logged, rather than throwing a postcondition exception that surfaces as a general client error.
## SQL Query Rules (CRITICAL - OraFlow workflow)
- **NEVER deliver SQL as ad-hoc inline queries.** Always deliver SQL as a **single combined OraFlow script artifact** authored via `author_sql_script(name='{{TICKET}}_diagnostic', sql_body=..., description='{{TICKET}} in-depth diagnostic')`. The text and JSON evidence files are produced automatically by `run_active_target_script` / `run_sql_script` - do not write or edit them by hand.
- **Probe-and-narrow.** Author 3-5 focused statements per script (single example -> counts -> correlation). If you need a broader sweep, split it across multiple `_diagnostic`, `_followup`, `_audit_history` scripts. Live PROD evidence shows omnibus scripts time out where focused probes succeed.
- **ALL tables MUST be prefixed with `trexone_data.`** on every reference. No unqualified table names anywhere. The OraFlow validator does not enforce this - discipline is on you.
- **Never inline a SELECT through `connect` / `run_query` / `run_query_once` / live `list_tables` / live `describe_table` / live `list_views`** for an L3 investigation. Those tools are not the L3 evidence path. Investigations and PROD SQL go through script artifacts so the JSON sidecar + `OraFlow/db/_audit/runs.jsonl` audit row exist. Never call live/session schema tools with placeholder session IDs such as `dummy`, `schema`, or `schema_catalog`; that is a tool-routing error, not schema discovery.
- Use `-- ============` banner comments to separate logical sections, with a description of what each query proves; the script body is preserved verbatim in `OraFlow/db/scripts/`.
- Use CTEs (`WITH ... AS`) instead of repeating subqueries.
- Always include the smallest possible "single example" query first (one Rx / one order) so the data shape is obvious before the aggregate queries.
- Aggregate queries should `GROUP BY` to de-duplicate where the schema causes row inflation (e.g., 1-to-many joins).
- Use date filters like `state_date > ADD_MONTHS(SYSDATE, -8)` to keep result sets bounded.
- Round time deltas to seconds: `ROUND((d2 - d1) * 24 * 3600, 1) AS delta_sec`.
- Use `ABS(d1 - d2) < N/86400` for "within N seconds" timing correlations.
- Reconstruct code gates in execution order. A good diagnostic script should mirror the actual if/return/blocker sequence from the source code.
- Include both **current-state queries** and **historical/audit/sell-time queries** when the decision could have been made earlier than the current data state.
- Always include identity-chain queries that show whether the cited record and related records share the same primary key or are separate but related rows.
- Include blocker/proof columns with explicit labels such as `GATE_STATUS`, `BLOCKER_TYPE`, `PROOF_POINT`, or `EVIDENCE_SUMMARY` so output can be interpreted without rereading every join.
- When reproducing Java/PLSQL calculations in SQL, show component columns and the final formula side by side; note whether the script is exact, package-equivalent, or approximate.
- Add targeted follow-up scripts via additional `author_sql_script` calls when initial output narrows the hypothesis. Name them clearly: `{{TICKET}}_followup`, `{{TICKET}}_audit_history`, `{{TICKET}}_<short_topic>`.
- Respect row caps: default `max_rows` truncates large result sets. If `truncated == True` in the JSON sidecar, narrow the filter rather than blindly raising the cap.
- **Read the JSON sidecar as the source of truth.** Use `read_script_results(...)` to get the structured payload. The text file is human-friendly but lossy - it intentionally renders rows tab-joined and can drop nuances. If the text output shows `!! WARNING` (missing row bodies, or elapsed >80% of timeout), read the JSON sidecar AND the matching `OraFlow/db/logs/sqlplus/sqlplus_*.log` before drawing any conclusion.
- **Workflow:** (1) `jira_get_ticket` -> (2) `jira_list_related_tickets` / fetch relevant related tickets / optionally `jira_find_similar_tickets` -> (3) decide evidence lanes and bind PROD active target only if DB evidence is needed -> (4) `ping_active_target` and verify identity before DB reads -> (5) `author_sql_script` (probe-and-narrow) -> (6) `run_active_target_script` -> (7) `read_script_results` (JSON, source of truth) -> (8) iterate with `_followup` scripts. If active-target tools are not visible, stop and report the missing tool group unless the prompt or user explicitly approves an alias/profile `run_sql_script` fallback.
## Output
Create a single comprehensive markdown file at `Context/{{TICKET}}/{{TICKET}}_analysis.md` containing the following sections:
- **Issue Summary** - one paragraph from `OraFlow/jira/{{TICKET}}/summary.md`
- **Timeline of Reports** - every comment chronologically: `YYYY-MM-DD - Author - summary` (source: `OraFlow/jira/{{TICKET}}/comments.json`)
- **Affected Customer(s) & Configuration** - which customer(s), which app options drive the bug, the OraFlow target binding used (alias, env=PROD, profile, host, service)
- **Evidence Lane Decision** - which lanes were used: Jira-only, code/docs, DB, app options/config, Splunk/app logs, server logs, batch/job logs, integration/vendor logs, customer clarification; state why any external evidence was or was not needed
- **Database Schema Understanding** - the tables involved (sourced via `describe_schema_table`), what each column means in the context of this bug
- **Documentation / Expected Behavior** - relevant EnterpriseRx documentation findings and whether the observed behavior matches documented behavior
- **Code Flow Trace** - numbered step-by-step from UI click to DB write, with file paths and line numbers
- **Decision Gate Matrix** - each relevant code gate/blocker, expected value, actual value, and proof source (file/line + OraFlow script name + Q-index)
- **Record Identity / Chain Mapping** - primary keys and related rows needed to avoid mixing original/current/follow-on records
- **Diagnostic Output Findings** - what each Q-index in the JSON sidecar proves or disproves; cite by `<script>_output.json#statements[N]`
- **Audit / History Findings** - historical state at the time of the code decision, especially if current data differs from the Jira/customer claim; cite the follow-up script and Q-index
- **Evidence Matrix** - every important conclusion mapped to source file/line, DB table/column, OraFlow script + Q-index, Jira comment (with date/author), or attachment filename
- **Confirmed Root Cause or Root-Cause Hypothesis / Final Interpretation** - clearly stated. Prefer confirmed root cause. If there is a code defect, name the exact line/gate that goes wrong; if there is no code defect, name the exact data/config/business/doc-supported gate that explains the behavior. If still hypothetical, state what proof is missing and the exact OraFlow query that would produce it.
- **Why Only These Customers** - config combination analysis
- **Why It Cannot Be Reproduced** - race condition / timing / data-state explanation if applicable
- **Diagnostic SQL Script(s)** - list each authored OraFlow script with absolute paths to its `_output.txt` and `_output.json`, plus a one-line summary of each Q. Required content of the primary script:
  - Q1: a single concrete example showing the bad data shape on one Rx / order
  - Q2: a de-duplicated count of all occurrences in a date range
  - Q3: correlation query that links the "victim" record to the "trigger" event (when applicable)
- **OraFlow Run Provenance** - before writing this section, explicitly check `OraFlow/db/_audit/runs.jsonl`. For each script run, cite the matching audit row by `sql_sha256`, `timestamp`, `status`, target alias, script path, and row count/error. Include both `status="ok"` and `status="failed"` rows; failed rows are evidence too. Do not claim the audit file is missing unless the exact path was checked.
- **Related Issues** - every linked ticket from `issue.json`, every fetched related ticket under `OraFlow/jira/{{TICKET}}/related/`, and any high-confidence `similar_tickets.json` candidates, with a one-line description and why it matters
- **Open Questions** - what we still need to confirm, grouped by source when applicable: DB/data, BSA/tech lead, customer, Splunk/app logs, server logs, batch/job logs, integration/vendor logs, or app-option/config owner
- **Customer-Facing / Jira Resolution Draft** - concise wording suitable for Jira. It must distinguish confirmed facts from assumptions and avoid blaming configuration/code unless proven.
- **Jira Closure Labels** - select exactly one **Resolution** label and exactly one **Problem Category** label, with a one-sentence evidence-based justification for each:
  - Resolution options: `As Designed`, `Cannot Reproduce`, `Duplicate`, `Resolved`, `Won't Do`
  - Problem Category options: `None`, `Application Configuration`, `Audit Request`, `Bug`, `Conversion`, `Custom SQL Request`, `Data Error / Conversion`, `Enhancement`, `Incomplete Information`, `Operational`, `Other Vendor Issue`, `Performance`, `User Training / Error`
## Rules
- Be THOROUGH. Do not cut corners. If something takes longer, do it anyway.
- Do NOT skip files because they are long. Read them fully.
- Do NOT make assumptions about code behavior - read the actual implementation.
- Do NOT assume a column exists - confirm it via `describe_schema_table` (or fall back to `Context/erx_tables/`).
- Do NOT substitute live `describe_table`, live `list_tables`, or live `list_views` when bundled schema tools are missing; stop and report the missing tools or use repository DDL/source files as fallback.
- **Customer-data L3 = PROD target when DB evidence is needed.** Never default to DEV/QA for customer-data proof; non-PROD does not contain the customer's data. Do not bind DB at all for Jira-only/process tickets.
- **Never auto-fail over between siblings.** When a PROD endpoint times out, surface the `siblings` list to the user and ask which to try.
- ALL SQL must use `trexone_data.` schema prefix on every table reference.
- ALL SQL execution goes through `run_active_target_script` (or explicit `run_sql_script`) against the explicitly bound target. Never claim a result without an `OraFlow/db/_audit/runs.jsonl` audit row to back it up (success or failure).
- Findings must be defensible to the tech lead: every claim should map to a specific file/line, OraFlow script + Q-index, or DB table/column.
- Never treat Jira/customer wording as final truth. Verify whether it refers to current state, historical state, a related row, or a UI interpretation.
- Never infer a persisted flag or target date from configuration alone. Prove the row actually saved the expected state via OraFlow output.
- Do not stop at "config is correct" or "current row is wrong." Find the code gate or historical data transition that explains why.
- Do not stop at a vague "unable to determine" unless code, DB (via OraFlow), history/audit, docs, and attachments have all been exhausted. Dev/L3 owns the concrete root-cause analysis whenever the evidence is available.
- Prefer precise conclusions over vague ones when the blocker can be proven.
- If a result depends on a package function or hidden cursor, trace it and reproduce enough of its inputs to prove the gate via OraFlow.
- Every final Jira draft must recommend exactly one Resolution label and exactly one Problem Category label from the allowed dropdown values, and the chosen labels must be justified by the evidence matrix, root-cause conclusion, and documentation/expected-behavior check.
- **PROD discipline:** confirm the bound target with `ping_active_target` before authoring. If the ping returns `header_leak_suspected` or any identity field equals a column-name literal, STOP and re-resolve the alias - do not run any reads.
- This is a customer-impacting issue. Accuracy matters more than speed.
- **Substitution rule (apply globally):** every occurrence of `{{TICKET}}` in this prompt resolves first to an ERXD key in the current user message, otherwise to the value on the `TICKET:` line at the top. If neither contains a real ticket key, stop and ask the user for the ERXD key before doing anything else.
