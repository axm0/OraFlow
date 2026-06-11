# OraFlow Extension Upgrade / Clean Rebuild Prompt

Use this prompt when preparing a new OraFlow VSIX or replacing an installed OraFlow extension.

Goal: make the upgrade clean and repeatable without deleting user-owned workspace state. Old installed extension files, stale generated assets, VS Code/Copilot caches, temp extraction folders, and repo build artifacts must not cause the new install to run against yesterday's backend or assets. Routine upgrades must preserve `~/.oraflow`, workspace `OraFlow/` evidence folders, managed `.vscode/mcp.json` entries, managed OraFlow Copilot instructions, and VS Code workspaceStorage so the extension can refresh itself after install without forcing the user to reconfigure.

Before any code change is accepted, review `ORAFLOW_INSTALL_UPGRADE_IMPACT.md` and explicitly check whether the change adds or moves downloads, caches, user-profile files, temp files, workspace files, MCP config entries, extension activation behavior, cleanup targets, or verifier expectations. If it does, update that contract, `scripts/clean-uninstall.ps1`, rebuild/verify scripts, and docs in the same change.

Required flow:

1. Close VS Code if possible. If VS Code remains open, call out any locked zero-byte logs that cannot be deleted until VS Code exits.
2. Run the upgrade-safe cleanup against both common workspaces:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\clean-uninstall.ps1 `
  -Upgrade `
  -Workspace 'C:\Developer\Workspace\EnterpriseRx\OraFlow','C:\Developer\Workspace\EnterpriseRx\Development\mpserx-erx'
```

3. Confirm generated/stale state is gone before reinstall. In upgrade mode, credentials, workspace `OraFlow/`, managed `.vscode/mcp.json`, managed Copilot instructions, and VS Code workspaceStorage are intentionally preserved.

```text
%USERPROFILE%\.vscode\extensions\enterpriserx.oraflow-*
OraFlow repo build/
OraFlow repo dist/
OraFlow repo extensions/vscode/dist/
OraFlow repo extensions/vscode/node_modules/
OraFlow repo extensions/vscode/oraflow-*.zip
%TEMP%\oraflow*
%TEMP%\github-copilot\project-context\OraFlow*
%TEMP%\github-copilot\project-index\OraFlow*
%TEMP%\v_inspect
%TEMP%\v_lfinal
```

4. Rebuild with the clean rebuild script. It must delete the previous bundled backend folder before copying the new frozen backend.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\rebuild-vsix.ps1
```

5. Verify the VSIX before installing:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-vsix.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-vsix-internals.ps1
```

Also confirm the install/download/upgrade impact contract still matches the code:

```text
ORAFLOW_INSTALL_UPGRADE_IMPACT.md reviewed
No new runtime downloads unless explicitly documented and approved
No new user/workspace/temp/cache locations without cleanup and upgrade rules
Managed MCP refresh still points at bundled backend/assets/runtime
Upgrade mode still preserves credentials, evidence, MCP config, instructions, and workspaceStorage
Full clean uninstall still removes OraFlow-owned state when explicitly requested
VSIX package-bloat guards still pass; any larger legitimate runtime payload is documented
```

6. After verification, remove verifier temp folders if they exist:

```powershell
Remove-Item -LiteralPath "$env:TEMP\v_inspect", "$env:TEMP\v_lfinal" -Recurse -Force -ErrorAction SilentlyContinue
```

7. Do not reinstall unless explicitly asked. Leave the rebuilt VSIX on disk and report its path.

Expected final state before manual install:

```text
installedExtensionFolder=False
credentialsDir=Preserved
workspaceMcpJson=Preserved for extension self-refresh
workspaceOraFlowDir=Preserved
workspaceCopilotInstructions=Preserved/refreshed by extension activation
workspaceStorage=Preserved
repoBuildDir=False
repoDistDir=False
extensionDistDir=False
extensionNodeModules=False
runningOraFlowProcess=False
codeListsOraFlow=False
rebuiltVsix=True
```

Upgrade behavior note: the OraFlow extension activates after VS Code startup and should refresh managed `.vscode/mcp.json` entries to the currently installed bundled backend, bundled Instant Client, bundled TNS files, bundled schema catalog, and bundled SQL*Plus fallback. It should also refresh the managed OraFlow block in `.github/copilot-instructions.md` even when MCP JSON is already current. Use the clean uninstall script without `-Upgrade` only when the explicit goal is to discard local credentials, workspace evidence, MCP configuration, managed instructions, and workspace storage.