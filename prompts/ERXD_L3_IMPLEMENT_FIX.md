# Implement Fix - L3 Remediation (OraFlow-integrated)
> **Provide only the ERXD key when you use this prompt.** If the current user message includes an ERXD key, use that key. Otherwise set the ticket key once on the next line, then leave the rest of the prompt alone. Wherever you see `{{TICKET}}` below, substitute the selected ticket key (e.g. `{{TICKET}}_fix_verification` becomes `ERXD-73403_fix_verification`). Ask for a ticket key only if neither the user message nor the `TICKET:` line contains a real ERXD key.
```
TICKET: ERXD-XXXX
```
> **Step 0 - load the investigation analysis first.** Before writing any code, read `Context/{{TICKET}}/{{TICKET}}_analysis.md` if it exists (the output of `ERXD_L3_INVESTIGATION.md`). It already contains the confirmed root cause, decision-gate matrix, code-flow trace, evidence matrix, and diagnostic SQL. Do not re-derive what the analysis already proved. If the analysis file does **not** exist, stop and tell the user to run `ERXD_L3_INVESTIGATION.md` first - do not implement a fix from an unproven root cause.
> **All Jira evidence, SQL execution, and DB verification go through the OraFlow MCP server - never paste raw passwords into chat, never hand-edit files under `OraFlow/db/scripts/` or `OraFlow/db/outputs/`.**

## Natural-language trigger
If the user says something like **"implement the fix for ERXD-12345"**, **"fix ERXD-12345"**, **"build the fix from the analysis"**, or **"remediate ERXD-12345"**, treat the ERXD key as the only required input. First load the prior investigation analysis and Jira evidence, confirm the root cause is actually proven, then implement the code/config/data fix that the analysis points to. Do not re-run the full investigation unless the analysis is missing, stale, or contradicted by new evidence.

## Context
I am implementing the remediation for Jira ticket **{{TICKET}}**. The technical root cause should already be established in `Context/{{TICKET}}/{{TICKET}}_analysis.md`. My job here is to translate that confirmed root cause into a concrete, reviewable, low-risk fix: source-code change, application configuration change, data correction script, or a documented decision that no code change is warranted. Database access is provided exclusively through the **OraFlow MCP server** (Oracle, schema: `trexone_data`). Use the analysis, Jira evidence, source code, schema catalog, and EnterpriseRx documentation as the source of truth.

## Inputs (read ALL of these fully - do not skim)
1. **Investigation analysis** at `Context/{{TICKET}}/{{TICKET}}_analysis.md` - the primary input. Extract the confirmed root cause (or root-cause hypothesis), the exact code gate/line that is wrong, the decision-gate matrix, the evidence matrix, the record-identity chain, and the diagnostic SQL that proves the bad state.
2. **OraFlow Jira evidence** at `OraFlow/jira/{{TICKET}}/` (`summary.md`, `issue.json`, `comments.json`, `attachments/`, `related/`). Re-read to confirm the fix matches what the customer actually reported, the affected versions, and any constraints (e.g., requested behavior, deadlines, regression context).
3. **Source code** - the exact files/lines named in the analysis. Read the current implementation end-to-end before changing it: UI panel, service/boundary layer, PostConditions/workflow engine, and PL/SQL packages as applicable. Confirm the analysis still matches the current code (it may have moved).
4. **Schema/DDL** via OraFlow schema catalog (`describe_schema_table`, `search_schema`) for any table the fix reads or (for a data-correction script) needs to reason about. Fall back to `Context/erx_tables/` or source DDL only if a table is missing from the catalog.
5. **EnterpriseRx documentation** in `Context/` - confirm the fixed behavior matches documented/expected behavior. If the fix changes user-visible behavior, the documented behavior must support it.

## Pre-Implementation Gate (do this before writing code)
1. **Confirm the root cause is proven, not hypothetical.** If the analysis only has a `Root-Cause Hypothesis`, do not implement a speculative fix. State what proof is still missing and either gather it (via OraFlow per the investigation prompt) or stop and ask the user.
2. **Confirm the analysis still matches current source.** Re-open the exact files/lines. If the code has changed since the analysis, note the drift and re-validate the gate before editing.
3. **Classify the fix type** and confirm it with the evidence:
   - **Code fix** - a defect in a specific code path/query/condition/transaction boundary/persistence step.
   - **Application configuration fix** - a missing/incorrect effective config row at a specific facility/customer hierarchy level (usually no code change; deliver the exact config change + where it applies).
   - **Data correction** - a one-time corrective script for damaged/inconsistent rows (delivered as a reviewed, parameterized DML script for a DBA/approved path - NOT executed through the read-only L3 evidence tools).
   - **No-change / As Designed** - the correct outcome is a documented explanation, not a code change.
4. **Decide the blast radius and regression surface** before editing: every caller of the changed method, every other customer/config that hits the same path, every batch/postcondition/event that depends on the persisted value, and any historical data already written in the bad state.
5. Review `ORAFLOW_INSTALL_UPGRADE_IMPACT.md` if (and only if) the change touches OraFlow runtime/build/packaging/cleanup surfaces. A pure EnterpriseRx product code fix typically does not, but confirm rather than assume.

## Implementation Standard
- Make the **smallest correct change** that fixes the proven root cause. Do not refactor unrelated code, rename symbols, reformat untouched lines, or add speculative features.
- The fix must address the **mechanism** named in the analysis (the exact gate/calculation/query/persistence/transaction boundary), not just suppress the visible symptom.
- Preserve existing behavior for all paths the analysis did **not** identify as defective. Guard the change so only the proven-bad condition is affected.
- Match the surrounding code's conventions (style, error handling, logging, transaction handling). Do not introduce new patterns where existing ones suffice.
- If the fix changes a persisted value, decide and state whether **existing bad rows** also need a one-time correction, and whether downstream recompute/batch reload/cache refresh is required.
- For workflow/postcondition fixes, prefer skipping/logging the unsafe item while letting valid items continue, over throwing an exception that surfaces as a generic client error - unless the analysis proves a hard stop is correct.
- For configuration fixes, deliver the exact option name, effective hierarchy level, current value, target value, source of truth, and whether a restart/cache refresh/batch reload is required - do not change product code.
- For data-correction scripts, deliver a **reviewed, reversible-where-possible, fully-qualified (`trexone_data.`) DML script** with a matching pre/post verification SELECT, an explicit row-scope (WHERE clause keyed to the proven-bad identity), and a clear note that it must be run by the approved DBA/change path - **never** through the read-only OraFlow L3 evidence tools.

## Verification Standard
- Add or update **automated tests** that fail before the fix and pass after, covering the proven-bad condition and at least one adjacent good condition that must remain unchanged. Follow the repo's existing test conventions.
- Run the relevant test suite and report results. For this repo's OraFlow tooling changes, run the validation commands from `AGENTS.md` (pytest, ruff, and the rebuild/verify scripts) when applicable.
- If a DB state must be verified after a code/config fix (e.g., confirming the persisted value is now correct for a re-run), author a **read-only** OraFlow verification script `author_sql_script(name='{{TICKET}}_fix_verification', ...)`, bind the correct target, `ping_active_target` to confirm identity, run via `run_active_target_script`, and read `read_script_results` (JSON sidecar = source of truth). Verification reads stay read-only; corrective DML does not go through these tools.
- Re-check the original Jira-reported symptom against the fixed behavior and state explicitly whether it is resolved.

## Output
1. **Implement the change directly in the workspace** (code edits, config artifact, or data-correction script file). Do not just describe it.
2. Create or update a remediation summary at `Context/{{TICKET}}/{{TICKET}}_fix.md` containing:
   - **Root Cause (from analysis)** - one paragraph, citing `Context/{{TICKET}}/{{TICKET}}_analysis.md` and the exact gate/line.
   - **Fix Type** - Code fix / Application configuration / Data correction / No-change (As Designed), with justification.
   - **Change Summary** - what was changed and why, in plain language.
   - **Files Changed** - each file with a one-line description of the edit and the line range.
   - **Why This Is the Minimal Correct Fix** - what was deliberately left untouched and why.
   - **Blast Radius / Regression Analysis** - other callers, customers, configs, batches, and historical rows considered; what is and isn't affected.
   - **Existing Bad Data** - whether previously-written bad rows need a one-time correction; if so, the data-correction script path and its scope.
   - **Tests** - new/updated tests, what condition each proves, and the pass/fail result before vs after.
   - **DB Verification (if any)** - the read-only `{{TICKET}}_fix_verification` script, target binding, and what the JSON sidecar proved; cite `OraFlow/db/_audit/runs.jsonl`.
   - **Documentation / Expected Behavior** - confirmation the fixed behavior matches EnterpriseRx docs, with the relevant section.
   - **Deployment / Rollout Notes** - migration, config push, cache/batch reload, restart, or data-script execution steps and order; any feature-flag or version gating.
   - **Rollback Plan** - how to revert safely if the fix regresses.
   - **Residual Risk / Open Items** - anything still unproven, plus follow-ups (e.g., monitoring, broader cleanup, related tickets).
   - **Jira Update Draft** - concise wording for the ticket describing the fix, distinguishing confirmed facts from assumptions.

## Rules
- Do NOT implement a fix on top of an unproven root cause. If `Context/{{TICKET}}/{{TICKET}}_analysis.md` is missing or only hypothetical, stop and route the user back to `ERXD_L3_INVESTIGATION.md` (or gather the missing proof first).
- Do NOT make changes beyond what the proven root cause requires. No opportunistic refactors, renames, reformatting, or new abstractions.
- Do NOT read source behavior from memory - re-read the actual current implementation before editing; it may have moved since the analysis.
- ALL OraFlow SQL (verification) must use the `trexone_data.` schema prefix on every table reference and go through script artifacts, read-only.
- **Never execute corrective DML through OraFlow L3 evidence tools.** Data-correction scripts are delivered as reviewed artifacts for the approved DBA/change path; the L3 tools are read-only by design.
- **Customer-data verification = PROD target when DB confirmation is needed.** Never default to DEV/QA for customer-data confirmation; bind the customer's PROD target, and never auto-fail over between siblings - surface them and ask.
- Every code change must ship with a test that fails before and passes after, unless the fix is config-only or no-change (in which case state why a code test does not apply).
- Confirm the fixed behavior against EnterpriseRx documentation before claiming the fix is correct; if docs are silent, rely on code/data evidence and say so.
- If the change touches OraFlow runtime/build/packaging/cleanup surfaces, follow `AGENTS.md` and update `ORAFLOW_INSTALL_UPGRADE_IMPACT.md`, docs, and the verifier scripts in the same change.
- This is a customer-impacting fix. Accuracy and safety matter more than speed.
- **Substitution rule (apply globally):** every occurrence of `{{TICKET}}` resolves first to an ERXD key in the current user message, otherwise to the value on the `TICKET:` line at the top. If neither contains a real ticket key, stop and ask the user for the ERXD key before doing anything else.
