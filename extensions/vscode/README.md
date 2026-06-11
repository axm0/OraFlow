# OraFlow VS Code Extension

OraFlow configures a local, read-only Oracle and Jira MCP server for Copilot workflows against EnterpriseRx databases and EnterpriseRx Jira.

Use this README for install, setup, and basic smoke testing. Build and engineering details live in the OraFlow repo docs, not in this extension README.

## First-time setup

1. **Install the VSIX**
   - VS Code -> Extensions -> `...` -> **Install from VSIX...**
   - Pick the latest `oraflow-<version>.vsix`.
   - Reload VS Code when prompted.

2. **Open your working repository**
   - OraFlow writes local scripts, outputs, and audit files under that workspace's `OraFlow/` folder.

3. **Create credentials**
   - Run **`OraFlow: Setup Credentials`** from the Command Palette.
   - Fill only the database profiles you need in `~/.oraflow/credentials.toml`.
   - Run **`OraFlow: Setup Jira Credentials`** if you need Jira tools.
   - Do not commit or share credential files.

4. **Configure MCP for the workspace**
   - Run **`OraFlow: Configure MCP for Workspace`**.
   - This creates or updates `.vscode/mcp.json` with the local `oraflow` server entry.
   - Passwords are not written to `.vscode/mcp.json`.

5. **Start the MCP server**
   - Use **`MCP: List Servers` -> `oraflow` -> Start**.
   - When VS Code asks for trust, confirm the command path points to the OraFlow extension folder before approving.

## Recommended smoke test

After VPN and credentials are ready, use Copilot Agent mode:

1. Ask: `Show OraFlow config info.`
2. Ask: `Use OraFlow to search the schema for rx_base.`
3. Set a known non-PROD active target and ping it.
4. Run this read-only test query through an OraFlow script artifact:

```sql
SELECT *
FROM TREXONE_DATA.RX_BASE
ORDER BY RX_RECORD_NUM
FETCH FIRST 10 ROWS ONLY;
```

5. Confirm the result is read through `read_script_results` and that a run row was written under `OraFlow/db/_audit/runs.jsonl`.

If Jira credentials are configured, also test Jira evidence fetch with a ticket you can access:

```text
Use OraFlow to fetch ERXD-12345 and summarize the ticket evidence.
```

OraFlow saves Jira issue details, comments, attachment metadata, related-ticket indexes, and similar-ticket search results under the workspace `OraFlow/jira/` folder. Attachment files download only when explicitly requested.

## Jira tools

OraFlow can read ERXD ticket evidence for investigations:

- Fetch ticket details, comments, and attachment metadata.
- Find linked or related tickets.
- Search for similar ERXD tickets.
- Save local evidence files for Copilot analysis.

Jira tools are read-only. They do not edit tickets, add comments, transition status, or upload attachments.

## Command palette commands

| Command | Purpose |
|---|---|
| `OraFlow: Setup Credentials` | Create/open database credentials. |
| `OraFlow: Setup Jira Credentials` | Create/open Jira credentials. |
| `OraFlow: Configure MCP for Workspace` | Register OraFlow in the current workspace. |
| `OraFlow: Show Bundled Backend Path` | Show the local backend executable path. |

## Local files OraFlow creates

OraFlow may create a workspace `OraFlow/` folder containing read-only SQL scripts, query outputs, JSON result files, audit logs, and Jira evidence. Treat that folder as sensitive when it contains customer or PROD data. Do not commit it.

The VSIX does **not** include your credentials, prompts, query outputs, Jira attachments, or customer data.

The installed extension does not download backend code, Oracle clients, Python packages, npm packages, schema files, or FastMCP skills at runtime. It uses the bundled files inside the VSIX. Network activity happens only when you call database tools, Jira tools, or explicitly request Jira attachment file downloads. Engineering details and the full location/upgrade contract live in `ORAFLOW_INSTALL_UPGRADE_IMPACT.md` at the repo root.

## Safety summary

- SQL tools are read-only: only `SELECT` / `WITH` statements are accepted.
- Jira tools are read-only: they fetch/search evidence but do not edit Jira.
- Credentials stay in `~/.oraflow/`, not in workspace MCP config.
- The MCP backend uses stdio and does not open a web server.
- PROD reads should use a pinned active target, `ping_active_target`, script artifacts, and `read_script_results`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| OraFlow tools do not appear | Run `MCP: List Servers` -> `oraflow` -> Start/Restart. |
| Missing credentials | Run `OraFlow: Setup Credentials` or `OraFlow: Setup Jira Credentials`. |
| `.vscode/mcp.json` is invalid JSON | Delete `.vscode/mcp.json`, then rerun `OraFlow: Configure MCP for Workspace`. |
| Jira attachments fail with `CERTIFICATE_VERIFY_FAILED` | Install a current OraFlow VSIX so Jira HTTPS uses the OS trust store. |
| Text output looks empty but rows were reported | Read the JSON sidecar with `read_script_results`; it is the source of truth. |

## Support

Internal-only build by Abdul Aziz Mohammed.