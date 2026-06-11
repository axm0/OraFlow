# ERXD L3 Triage (OraFlow-integrated)
> **Use this when you want a quick first pass before the full L3 investigation.** Provide only the ERXD key. If the current user message includes an ERXD key, use it. Otherwise set it once below. Ask for a ticket key only if neither place has a real ERXD key.
```
TICKET: ERXD-XXXX
```

## Goal
Triage Jira ticket **{{TICKET}}** and decide the next best action: close/process response, request missing info, code/docs review, DB evidence, app-option/config check, Splunk/app-server logs, server logs, batch/job logs, integration/vendor evidence, or full L3 investigation.

## First Steps
1. Call `jira_get_ticket("{{TICKET}}")` first. Read `OraFlow/jira/{{TICKET}}/summary.md`, `issue.json`, `comments.json`, and attachment metadata. Download attachment files only when they are clearly needed.
2. Call `jira_list_related_tickets("{{TICKET}}")`. Fetch only related tickets that look directly relevant.
3. Do not ask the user for customer, DB alias, schema, Splunk query, batch name, app option, or attachments up front. Infer what you can from Jira first.

## Triage Decision
Classify the ticket as one of these:
- **Incomplete info / customer clarification needed**
- **Process / duplicate / assignment / status-only**
- **Likely As Designed / documentation question**
- **Code/docs review needed**
- **Customer PROD DB evidence needed**
- **App options/config evidence needed**
- **Splunk/app-server logs needed**
- **Server logs needed**
- **Batch/job/integration logs needed**
- **Full L3 investigation needed**

Use the lightest evidence path that can answer the ticket safely.

## Evidence Rules
- Use OraFlow Jira evidence first. Do not treat the customer summary as proven until comments, attachment metadata or explicitly requested attachment files, related tickets, and code/docs/DB/log evidence support it.
- Do not bind a database unless customer-data proof is actually needed.
- If DB evidence is needed, resolve and bind the customer PROD target with `list_customers` / `resolve_target` / `set_active_target`, then confirm with `ping_active_target` before reads.
- For DB work, use only script artifacts: `author_sql_script` -> `run_active_target_script` -> `read_script_results`. Never use inline `run_query`, `run_query_once`, live `describe_table`, live `list_tables`, or live `list_views` for L3 evidence.
- Use `describe_schema_table` / `search_schema` for schema. If bundled schema tools are missing, use repo DDL/source fallback or stop and report the missing tool group. Do not fake schema discovery with placeholder session IDs.
- If app options/config matter, identify the option name, hierarchy level, actual value, expected value, and source of truth. Ask the user only for values/screenshots that cannot be found safely.
- If logs are needed, ask for the smallest useful package: timestamp window with timezone, customer/store/facility, user/workstation, server/environment, request/correlation ID if known, and exact error text.
- If batch/job/integration logs are needed, ask for job/interface name, run window, server, scheduler/run ID, status, and error/reject excerpt.

## Output
Respond with a short triage note containing:
- **Ticket Summary:** one or two sentences.
- **Classification:** one label from the triage list.
- **Evidence Checked:** Jira files, related tickets, attachments, code/docs, DB, logs, or config reviewed so far.
- **Recommended Next Action:** exact next step, such as run full L3 prompt, request Splunk logs, bind PROD DB, inspect code path, request customer timestamp, or close/process response.
- **Missing Info, If Any:** only the fields truly needed to proceed.
- **Risk / Impact:** brief customer-impact note.

## Stop Conditions
Stop after triage unless the user explicitly asks to continue into the full investigation. If full L3 is needed, say so and name the reason, required evidence lanes, and the next prompt to run: `ERXD_L3_INVESTIGATION.md`.

## Substitution Rule
Every `{{TICKET}}` resolves first to an ERXD key in the current user message, otherwise to the `TICKET:` line. If neither contains a real ERXD key, ask for the ERXD key before doing anything else.
