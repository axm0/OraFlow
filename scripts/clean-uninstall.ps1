# OraFlow clean-uninstall: wipes every trace of the extension so you can reinstall fresh.
# Use -Upgrade for normal extension replacement; it preserves user-owned repo state.
# Safe to run with VS Code closed. Re-run until "CLEAN SLATE ESTABLISHED" reports nothing left.
[CmdletBinding()]
param(
    [switch]$Upgrade,           # upgrade-safe cleanup: preserve credentials, workspace evidence, MCP config, instructions, and workspace storage
    [switch]$KeepCredentials,   # pass to preserve ~/.oraflow, including credentials.toml and jira.toml
    [switch]$KeepWorkspaceData, # pass to preserve OraFlow/ and mpserx-erx/ workspace artifact folders
    [switch]$KeepMcpConfig,     # pass to preserve .vscode/mcp.json so a newer extension can refresh it on activation
    [switch]$KeepCopilotInstructions, # pass to preserve .github/copilot-instructions.md managed OraFlow block
    [switch]$KeepWorkspaceStorage, # pass to preserve VS Code workspaceStorage for the selected workspaces
    [switch]$KeepDevArtifacts,  # pass to preserve repo build/dist and extension node_modules/dist folders
    [string[]]$Workspace        # optional explicit workspace paths to clean; defaults to current dir
)

$ErrorActionPreference = 'Continue'

function Write-Section($t) { Write-Output ""; Write-Output ("=== {0} ===" -f $t) }

$legacyNamePattern = '(?i)oraflow|enterpriserx\.oraflow|mpserx[-.]erx'
$looseCacheNamePattern = '(?i)oraflow|mpserx[-.]erx'
$workspaceArtifactFolders = @('OraFlow', 'mpserx-erx')
$mcpServerNames = @('oraflow', 'mpserx-erx', 'mpserx.erx')
$copilotBeginMarker = '<!-- BEGIN ORAFLOW AGENT INSTRUCTIONS'
$copilotEndMarker = '<!-- END ORAFLOW AGENT INSTRUCTIONS -->'
$repoGeneratedRelativePaths = @(
    'build',
    'dist',
    'extensions\vscode\dist',
    'extensions\vscode\node_modules'
)
$repoGeneratedFileGlobs = @(
    'extensions\vscode\oraflow-*.zip'
)

function Remove-PathForce($Path, $FailedMessage = $null, $RemovedMessage = $null) {
    if (-not (Test-Path -LiteralPath $Path)) { return }

    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
    } catch {
        # Some old installs leave read-only files behind. Normalize attributes and
        # retry so non-empty legacy folders are removed as completely as possible.
        try {
            Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue | ForEach-Object { $_.Attributes = 'Normal' }
            Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue |
                ForEach-Object { $_.Attributes = 'Normal' }
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        } catch {
            if (-not $FailedMessage) { $FailedMessage = "  FAILED   {0}" }
            Write-Output ($FailedMessage -f $Path)
            return
        }
    }

    if (Test-Path -LiteralPath $Path) {
        if (-not $FailedMessage) { $FailedMessage = "  FAILED   {0}" }
        Write-Output ($FailedMessage -f $Path)
        return
    }

    if ($RemovedMessage) { Write-Output ($RemovedMessage -f $Path) }
}

function Get-WorkspaceList {
    $list = @()
    if ($Workspace -and $Workspace.Count -gt 0) {
        # Defensively expand: when invoked via `pwsh -File ... -Workspace 'A','B'`
        # PowerShell sometimes binds the whole literal as a single string. Split
        # on commas / semicolons and trim quotes so multi-workspace cleanup
        # actually iterates every entry.
        foreach ($entry in $Workspace) {
            if ($null -eq $entry) { continue }
            foreach ($piece in ([string]$entry -split '[,;]')) {
                $trimmed = $piece.Trim().Trim('"').Trim("'")
                if ($trimmed) { $list += $trimmed }
            }
        }
        return @($list | Select-Object -Unique)
    }
    return @((Get-Location).Path)
}

function Get-WorkspaceFolderFromStorage($StorageDir) {
    $workspaceJson = Join-Path $StorageDir 'workspace.json'
    if (-not (Test-Path -LiteralPath $workspaceJson)) { return $null }
    try {
        $payload = Get-Content -LiteralPath $workspaceJson -Raw | ConvertFrom-Json
        $folder = [string]$payload.folder
        if (-not $folder) { return $null }
        if ($folder -match '^file:') { return ([System.Uri]$folder).LocalPath }
        return $folder
    } catch {
        return $null
    }
}

function Same-Path($Left, $Right) {
    try {
        $l = [System.IO.Path]::GetFullPath($Left).TrimEnd('\', '/').ToLowerInvariant()
        $r = [System.IO.Path]::GetFullPath($Right).TrimEnd('\', '/').ToLowerInvariant()
        return $l -eq $r
    } catch {
        return $false
    }
}

function Write-Utf8NoBom($Path, $Text) {
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function Remove-EmptyDirectory($Path, $RemovedMessage = $null) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $children = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)
    if ($children.Count -ne 0) { return }
    Remove-PathForce $Path $null $RemovedMessage
}

function Remove-OraFlowCopilotInstructions($WorkspaceRoot) {
    $instructionsPath = Join-Path $WorkspaceRoot '.github\copilot-instructions.md'
    if (-not (Test-Path -LiteralPath $instructionsPath)) { return }

    $raw = Get-Content -LiteralPath $instructionsPath -Raw
    $begin = $raw.IndexOf($copilotBeginMarker, [System.StringComparison]::OrdinalIgnoreCase)
    $end = $raw.IndexOf($copilotEndMarker, [System.StringComparison]::OrdinalIgnoreCase)
    if ($begin -lt 0 -or $end -lt 0 -or $end -lt $begin) { return }

    $end += $copilotEndMarker.Length
    $remaining = ($raw.Substring(0, $begin).TrimEnd() + "`r`n" + $raw.Substring($end).TrimStart()).Trim()
    $backupPath = "$instructionsPath.bak"
    Copy-Item -LiteralPath $instructionsPath -Destination $backupPath -Force
    if ([string]::IsNullOrWhiteSpace($remaining)) {
        Remove-PathForce $instructionsPath "    FAILED   {0}" "    REMOVED generated OraFlow Copilot instructions: {0}"
        Remove-EmptyDirectory (Split-Path $instructionsPath -Parent) "    REMOVED empty directory: {0}"
    } else {
        Write-Utf8NoBom $instructionsPath ($remaining + "`r`n")
        Write-Output ("    Removed OraFlow block from {0}" -f $instructionsPath)
    }
    Remove-PathForce $backupPath $null "    REMOVED stale OraFlow backup: {0}"
}

function Test-OraFlowRepo($WorkspaceRoot) {
    return (Test-Path -LiteralPath (Join-Path $WorkspaceRoot 'oraflow-mcp.spec')) -and
        (Test-Path -LiteralPath (Join-Path $WorkspaceRoot 'extensions\vscode\package.json')) -and
        (Test-Path -LiteralPath (Join-Path $WorkspaceRoot 'src\oraflow'))
}

$wsList = Get-WorkspaceList

if ($Upgrade) {
    $KeepCredentials = $true
    $KeepWorkspaceData = $true
    $KeepMcpConfig = $true
    $KeepCopilotInstructions = $true
    $KeepWorkspaceStorage = $true
}

if ($Upgrade) {
    Write-Section "UPGRADE MODE"
    Write-Output "  Preserving ~/.oraflow credentials, workspace OraFlow/ evidence folders, .vscode/mcp.json, managed Copilot instructions, and VS Code workspaceStorage."
    Write-Output "  Installed extension folders, extension index entries, logs, caches, temp files, and OraFlow repo build outputs are still cleaned."
}

# ---------------------------------------------------------------------------
Write-Section "0. CHECK VS CODE PROCESSES"
$running = Get-Process -Name 'Code','Code - Insiders','code' -ErrorAction SilentlyContinue
if ($running) {
    Write-Output "  WARNING: VS Code is running. Some files will be locked. Close VS Code and re-run."
    $running | Select-Object Id, ProcessName | Format-Table | Out-String | Write-Output
} else {
    Write-Output "  VS Code is not running. Good."
}

# ---------------------------------------------------------------------------
Write-Section "1. SCAN extension folders"
$extRoots = @(
    "$env:USERPROFILE\.vscode\extensions",
    "$env:USERPROFILE\.vscode-insiders\extensions",
    "$env:USERPROFILE\.cursor\extensions",
    "$env:USERPROFILE\.windsurf\extensions"
) | Where-Object { Test-Path $_ }

$found = @()
foreach ($p in $extRoots) {
    Get-ChildItem -Path $p -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match $legacyNamePattern } |
        ForEach-Object {
            $sz = [math]::Round((Get-ChildItem -Recurse $_.FullName -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum/1MB, 2)
            Write-Output ("  FOUND  {0,8} MB   {1}" -f $sz, $_.FullName)
            $found += $_.FullName
        }
}
if ($found.Count -eq 0) { Write-Output "  (none found)" }

# ---------------------------------------------------------------------------
Write-Section "2. REMOVE extension folders"
foreach ($f in $found) {
    Remove-PathForce $f "  FAILED   {0}  (close VS Code completely first)" "  REMOVED  {0}"
}

# ---------------------------------------------------------------------------
Write-Section "3. CLEAN VS Code extension index files (.obsolete + extensions.json)"
foreach ($p in $extRoots) {
    $obsolete = Join-Path $p '.obsolete'
    if (Test-Path $obsolete) {
        try {
            $j = Get-Content -Raw $obsolete | ConvertFrom-Json
            $h = @{}
            $j.PSObject.Properties | Where-Object { $_.Name -notmatch $legacyNamePattern } | ForEach-Object { $h[$_.Name] = $_.Value }
            $newJson = if ($h.Count -eq 0) { '{}' } else { ($h | ConvertTo-Json -Compress) }
            Copy-Item $obsolete "$obsolete.bak" -Force
            Set-Content -Path $obsolete -Value $newJson -Encoding utf8 -NoNewline
            Write-Output ("  Cleaned .obsolete: {0}" -f $obsolete)
        } catch {
            Write-Output ("  Could not parse .obsolete ({0}); leaving alone." -f $obsolete)
        }
    }

    $extJson = Join-Path $p 'extensions.json'
    if (Test-Path $extJson) {
        try {
            $arr = Get-Content -Raw $extJson | ConvertFrom-Json
            $kept = @($arr | Where-Object {
                ($_.identifier.id -notmatch $legacyNamePattern) -and ($_.location.path -notmatch $legacyNamePattern)
            })
            if ($kept.Count -ne $arr.Count) {
                Copy-Item $extJson "$extJson.bak" -Force
                $newJson = if ($kept.Count -eq 0) { '[]' } else { ConvertTo-Json -InputObject @($kept) -Depth 50 -Compress }
                Set-Content -Path $extJson -Value $newJson -Encoding utf8 -NoNewline
                Write-Output ("  Pruned OraFlow/mpserx-erx entries from {0}" -f $extJson)
            } else {
                Write-Output ("  No OraFlow/mpserx-erx entries in {0}" -f $extJson)
            }
        } catch {
            Write-Output ("  Could not parse extensions.json ({0}); leaving alone." -f $extJson)
        }
    }
}

# ---------------------------------------------------------------------------
Write-Section "4. CLEAN VS Code per-user storage (globalStorage / workspaceStorage / logs / caches)"
$userRoots = @(
    "$env:APPDATA\Code\User",
    "$env:APPDATA\Code - Insiders\User",
    "$env:APPDATA\Cursor\User",
    "$env:APPDATA\Windsurf\User"
) | Where-Object { Test-Path $_ }

$userParents = $userRoots | ForEach-Object { Split-Path $_ -Parent }

foreach ($u in $userRoots) {
    foreach ($sub in @('globalStorage','workspaceStorage')) {
        $d = Join-Path $u $sub
        if (-not (Test-Path $d)) { continue }
        Get-ChildItem -Path $d -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match $legacyNamePattern } |
            ForEach-Object {
                Remove-PathForce $_.FullName $null "  REMOVED  {0}"
            }
    }
}

# Remove loose cache files inside VS Code storage that carry old OraFlow/mpserx names
# even when their parent directories are shared with other extensions.
foreach ($u in $userRoots) {
    foreach ($sub in @('globalStorage','workspaceStorage')) {
        $d = Join-Path $u $sub
        if (-not (Test-Path $d)) { continue }
        Get-ChildItem -Path $d -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match $looseCacheNamePattern } |
            ForEach-Object { Remove-PathForce $_.FullName $null "  REMOVED  {0}" }
    }
}

if ($KeepWorkspaceStorage) {
    Write-Output "  -KeepWorkspaceStorage/Upgrade specified; leaving VS Code workspaceStorage for selected workspaces."
} else {
    # Remove workspaceStorage shards for the exact workspace paths being cleaned.
    # This avoids deleting unrelated historical workspaces that happen to contain
    # names like mpserx-erx in a different checkout path.
    foreach ($u in $userRoots) {
        $wsStorage = Join-Path $u 'workspaceStorage'
        if (-not (Test-Path $wsStorage)) { continue }
        foreach ($storageDir in Get-ChildItem -Path $wsStorage -Directory -ErrorAction SilentlyContinue) {
            $storedWorkspace = Get-WorkspaceFolderFromStorage $storageDir.FullName
            if (-not $storedWorkspace) { continue }
            foreach ($wsRoot in $wsList) {
                if ((Test-Path $wsRoot) -and (Same-Path $storedWorkspace $wsRoot)) {
                    Remove-PathForce $storageDir.FullName "  FAILED   {0}  (close VS Code completely first)" "  REMOVED workspaceStorage for {0}"
                    break
                }
            }
        }
    }
}

# Logs and CachedExtensionVSIXs
foreach ($parent in $userParents) {
    foreach ($subdir in @('logs','CachedExtensionVSIXs','CachedExtensions')) {
        $d = Join-Path $parent $subdir
        if (-not (Test-Path $d)) { continue }
        Get-ChildItem -Path $d -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match $looseCacheNamePattern } |
            ForEach-Object {
                Remove-PathForce $_.FullName $null "  REMOVED  {0}"
            }
    }
}

# Copilot and test runners maintain temp-side project indexes outside normal
# VS Code storage. These are safe to remove and can otherwise make an uninstall
# look dirty even though the extension is gone.
Write-Section "4b. CLEAN temp caches and verifier scratch"
$tempRoot = if ($env:TEMP) { $env:TEMP } else { [System.IO.Path]::GetTempPath() }
$tempTargets = @(
    (Join-Path $tempRoot 'oraflow*'),
    (Join-Path $tempRoot 'github-copilot\project-context\OraFlow*'),
    (Join-Path $tempRoot 'github-copilot\project-index\OraFlow*'),
    (Join-Path $tempRoot 'v_inspect'),
    (Join-Path $tempRoot 'v_lfinal')
)
foreach ($pattern in $tempTargets) {
    Get-Item -Path $pattern -Force -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-PathForce $_.FullName $null "  REMOVED  {0}" }
}
Get-ChildItem -Path (Join-Path $tempRoot 'pytest-*') -Directory -ErrorAction SilentlyContinue |
    ForEach-Object {
        Get-ChildItem -Path $_.FullName -Recurse -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match $looseCacheNamePattern -or $_.FullName -match '(?i)\\OraFlow(\\|$)' } |
            Sort-Object FullName -Descending |
            ForEach-Object { Remove-PathForce $_.FullName $null "  REMOVED  {0}" }
        Remove-EmptyDirectory $_.FullName "  REMOVED empty pytest temp directory: {0}"
    }

# ---------------------------------------------------------------------------
Write-Section "5. CREDENTIALS (~/.oraflow)"
$credsDir = "$env:USERPROFILE\.oraflow"
if ($KeepCredentials) {
    Write-Output "  -KeepCredentials specified; leaving $credsDir alone."
} elseif (Test-Path $credsDir) {
    Remove-PathForce $credsDir $null "  REMOVED  {0}"
} else {
    Write-Output "  (no $credsDir)"
}

# ---------------------------------------------------------------------------
Write-Section "6. WORKSPACE artifacts (.vscode/mcp.json legacy entries, OraFlow/mpserx-erx folders)"
foreach ($wsRoot in $wsList) {
    if (-not (Test-Path $wsRoot)) { continue }
    Write-Output ("  Workspace: {0}" -f $wsRoot)

    # Strip OraFlow/mpserx-erx from .vscode/mcp.json (preserve other servers)
    $mcp = Join-Path $wsRoot '.vscode\mcp.json'
    if ($KeepMcpConfig -and (Test-Path $mcp)) {
        Write-Output ("    -KeepMcpConfig/Upgrade specified; leaving {0} for extension self-refresh." -f $mcp)
    } elseif (Test-Path $mcp) {
        try {
            $cfg = Get-Content -Raw $mcp | ConvertFrom-Json
            $removedServers = @()
            foreach ($serverName in $mcpServerNames) {
                if ($cfg.servers -and $cfg.servers.PSObject.Properties.Name -contains $serverName) {
                    $cfg.servers.PSObject.Properties.Remove($serverName)
                    $removedServers += $serverName
                }
            }
            if ($removedServers.Count -gt 0) {
                $mcpBackup = "$mcp.bak"
                Copy-Item $mcp $mcpBackup -Force
                # Write UTF-8 WITHOUT BOM. Set-Content -Encoding utf8 on Windows
                # PowerShell 5.x emits a BOM (EF BB BF), which Node's JSON.parse
                # rejects, surfacing as "Existing MCP config is not valid JSON"
                # in the OraFlow extension. Use .NET's UTF8Encoding(false).
                $remainingServers = @()
                if ($cfg.servers) { $remainingServers = @($cfg.servers.PSObject.Properties.Name) }
                if ($remainingServers.Count -eq 0) {
                    Remove-PathForce $mcp "    FAILED   {0}" "    REMOVED empty MCP config after deleting OraFlow server: {0}"
                    Remove-EmptyDirectory (Split-Path $mcp -Parent) "    REMOVED empty directory: {0}"
                } else {
                    $json = $cfg | ConvertTo-Json -Depth 50
                    Write-Utf8NoBom $mcp $json
                    Write-Output ("    Removed MCP server(s) {0} from {1}" -f ($removedServers -join ', '), $mcp)
                }
                Remove-PathForce $mcpBackup $null "    REMOVED stale MCP backup: {0}"
            } else {
                Write-Output ("    No OraFlow/mpserx-erx server in {0}" -f $mcp)
            }
        } catch {
            Write-Output ("    Could not parse {0}; leaving alone." -f $mcp)
        }
    }

    if (-not $KeepWorkspaceData) {
        foreach ($folderName in $workspaceArtifactFolders) {
            $artifactDir = Join-Path $wsRoot $folderName
            if (Test-Path -LiteralPath $artifactDir) {
                Remove-PathForce $artifactDir "    FAILED   {0}" "    REMOVED  {0}"
            }
        }
    } else {
        Write-Output "    -KeepWorkspaceData specified; leaving OraFlow/ and mpserx-erx/ folders."
    }

    if ($KeepCopilotInstructions) {
        Write-Output "    -KeepCopilotInstructions/Upgrade specified; leaving managed OraFlow Copilot instructions for extension self-refresh."
    } else {
        Remove-OraFlowCopilotInstructions $wsRoot
    }
}

# ---------------------------------------------------------------------------
Write-Section "6b. DEV BUILD ARTIFACTS (repo-local generated outputs)"
if ($KeepDevArtifacts) {
    Write-Output "  -KeepDevArtifacts specified; leaving repo build/dist/node_modules outputs."
} else {
    foreach ($wsRoot in $wsList) {
        if (-not (Test-Path $wsRoot)) { continue }
        if (-not (Test-OraFlowRepo $wsRoot)) { continue }
        foreach ($relative in $repoGeneratedRelativePaths) {
            $path = Join-Path $wsRoot $relative
            if (Test-Path -LiteralPath $path) {
                Remove-PathForce $path "  FAILED   {0}" "  REMOVED  {0}"
            }
        }
        foreach ($relativeGlob in $repoGeneratedFileGlobs) {
            Get-ChildItem -Path (Join-Path $wsRoot $relativeGlob) -File -ErrorAction SilentlyContinue |
                ForEach-Object { Remove-PathForce $_.FullName "  FAILED   {0}" "  REMOVED  {0}" }
        }
    }
}

# ---------------------------------------------------------------------------
Write-Section "7. VERIFY GitHub Copilot Chat is installed (recommended)"
$copilotChat = @()
foreach ($p in $extRoots) {
    Get-ChildItem -Path $p -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^github\.copilot-chat-' } |
        ForEach-Object { $copilotChat += $_.FullName }
}
if ($copilotChat.Count -eq 0) {
    Write-Output "  WARNING: GitHub Copilot Chat extension not detected."
    Write-Output "           OraFlow tools are surfaced through MCP, which Copilot Chat (agent mode) consumes."
    Write-Output "           Without it, the OraFlow MCP server still runs, but you have no Copilot UI to call its tools."
    Write-Output "           Install: code --install-extension GitHub.copilot-chat"
    Write-Output "           Note: this OraFlow build does not ship a separate OraFlow chat participant."
    Write-Output "                 Just talk to Copilot agent mode in plain English (e.g. 'use OraFlow to set the active target to vanderbilt qa')."
} else {
    $copilotChat | ForEach-Object { Write-Output ("  OK  {0}" -f $_) }
}

# ---------------------------------------------------------------------------
Write-Section "8. REMAINING STATE"
$any = $false
foreach ($p in $extRoots) {
    $still = Get-ChildItem $p -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match $legacyNamePattern }
    foreach ($s in $still) { Write-Output ("  STILL THERE: {0}" -f $s.FullName); $any = $true }
}
if (-not $KeepCredentials -and (Test-Path $credsDir)) { Write-Output ("  STILL THERE: {0}" -f $credsDir); $any = $true }
if (-not $KeepWorkspaceData) {
    foreach ($wsRoot in $wsList) {
        foreach ($folderName in $workspaceArtifactFolders) {
            $artifactDir = Join-Path $wsRoot $folderName
            if (Test-Path -LiteralPath $artifactDir) { Write-Output ("  STILL THERE: {0}" -f $artifactDir); $any = $true }
        }
    }
}
if (-not $KeepDevArtifacts) {
    foreach ($wsRoot in $wsList) {
        if (-not (Test-OraFlowRepo $wsRoot)) { continue }
        foreach ($relative in $repoGeneratedRelativePaths) {
            $path = Join-Path $wsRoot $relative
            if (Test-Path -LiteralPath $path) { Write-Output ("  STILL THERE: {0}" -f $path); $any = $true }
        }
        foreach ($relativeGlob in $repoGeneratedFileGlobs) {
            foreach ($path in Get-ChildItem -Path (Join-Path $wsRoot $relativeGlob) -File -ErrorAction SilentlyContinue) {
                Write-Output ("  STILL THERE: {0}" -f $path.FullName)
                $any = $true
            }
        }
    }
}
foreach ($wsRoot in $wsList) {
    $mcp = Join-Path $wsRoot '.vscode\mcp.json'
    $instructionsPath = Join-Path $wsRoot '.github\copilot-instructions.md'
    if (Test-Path -LiteralPath $mcp) {
        try {
            $mcpRaw = Get-Content -LiteralPath $mcp -Raw
            if ((-not $KeepMcpConfig) -and $mcpRaw -match $legacyNamePattern) { Write-Output ("  STILL THERE: {0}" -f $mcp); $any = $true }
        } catch {}
    }
    if (Test-Path -LiteralPath $instructionsPath) {
        try {
            $instructionsRaw = Get-Content -LiteralPath $instructionsPath -Raw
            if ((-not $KeepCopilotInstructions) -and $instructionsRaw -match '(?i)oraflow|jira_get_ticket|oraflow-mcp') {
                Write-Output ("  STILL THERE: {0}" -f $instructionsPath)
                $any = $true
            }
        } catch {}
    }
}
if (-not $any) { Write-Output "  No undesired OraFlow state left." }

Write-Output ""
if ($Upgrade) {
    Write-Output "=== UPGRADE CLEANUP COMPLETE ==="
} else {
    Write-Output "=== CLEAN SLATE ESTABLISHED ==="
}
$latestVsix = Get-ChildItem (Join-Path $PSScriptRoot '..\extensions\vscode') -Filter 'oraflow-*.vsix' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($Upgrade) {
    Write-Output "Upgrade/install with:"
} else {
    Write-Output "Reinstall with:"
}
if ($latestVsix) {
    Write-Output ("  code --install-extension `"{0}`" --force" -f $latestVsix.FullName)
} else {
    Write-Output ("  code --install-extension `"{0}\..\extensions\vscode\oraflow-<version>.vsix`" --force" -f $PSScriptRoot)
}
if ($Upgrade) {
    Write-Output "Then: reopen the workspace. OraFlow activates after startup and refreshes managed MCP/Copilot instruction paths automatically."
    Write-Output "Only rerun credential or MCP setup commands if credentials are missing, mcp.json is invalid, or you intentionally want to reconfigure."
} else {
    Write-Output "Then: 1) Open the workspace  2) OraFlow: Setup Credentials  3) OraFlow: Configure MCP for Workspace  4) MCP: List Servers -> oraflow -> start."
}

