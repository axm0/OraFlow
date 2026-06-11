# OraFlow context/

This folder is the parking lot for **historical, planning, and one-off scratch
artifacts** that don't belong in the runtime tree but are still useful to
preserve as project context. Treat these files as background notes, not current
source of truth. Nothing in here is loaded by the MCP server, the CLI, or the
VS Code extension at runtime.

If a file becomes load-bearing again (e.g. a planning doc gets promoted to a
real spec), move it back to a top-level design document, `src/`, `scripts/`, or
`extensions/vscode/assets/`, then update the README at the repo root.

## Contents

### Planning / design notes
| File | What it is |
| --- | --- |
| `pla.md` | Original OraFlow planning doc (goals, scope, MCP-vs-agent decision, milestones). |
| `pla-tns-metadata.md` | Notes on the TNS metadata model and the customer/env/layer mapping. |
| `pla-creds-and-distribution.md` | Notes on the credential profile shape and how the bundle is distributed. |

### Environment / discovery snapshots
| File | What it is |
| --- | --- |
| `system_user_variables.txt` | Historical snapshot of a developer's `User`/`System` env vars (`TNS_ADMIN`, `ORACLE_HOME`, …). Current OraFlow does not use machine-level Oracle discovery. |
| `cloudconnectionimg.png` | Screenshot referenced from the planning notes. |

### LeMed verification artifacts (ERXD-69638)
| File | What it is |
| --- | --- |
| `lemedtest.sql` | Read-only verification queries (LeMed prod, `trexone_data` schema). |

Some planning notes still mention older scratch files, older implementation
ideas, connectivity reports, raw LeMed result captures, or TNS backups. Those
references are historical. They are not part of current runtime behavior unless
the same fact is also documented in `README.md`, `ORAFLOW_DOCS.md`,
`ORAFLOW_INSTALL_UPGRADE_IMPACT.md`, or code.

## Rules

- **Add only.** If you're producing new exploratory notes, drop them here
  rather than at the repo root.
- **Watch for secrets.** Some artifacts here originated from connectivity
  testing. Skim a file before pasting it into PRs / chat / external tools.
- **Don't import from here in code.** Anything the MCP server or CLI needs at
  runtime lives at the repo root, under `src/`, or under
  `extensions/vscode/assets/` — never in `context/`.

