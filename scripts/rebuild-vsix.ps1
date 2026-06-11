# Cleanly rebuild the OraFlow VS Code VSIX. By default this bumps the patch
# version so every rebuild produces a NEW version number, which prevents VS Code
# from reusing a version-stamped extension folder on reinstall (the same-version
# .obsolete trap). Use -Bump none to rebuild the current version, or -SetVersion
# x.y.z to pin an explicit version.
[CmdletBinding()]
param(
    [switch]$SkipNpmInstall,
    [switch]$KeepBuildArtifacts,
    [switch]$KeepNodeModules,
    [ValidateSet('none','patch','minor','major')]
    [string]$Bump = 'patch',
    [string]$SetVersion = ''
)

$ErrorActionPreference = 'Stop'

function Write-Section($Title) {
    Write-Output ""
    Write-Output ("=== {0} ===" -f $Title)
}

# Run a native command tolerating stderr output. Under $ErrorActionPreference =
# 'Stop', PowerShell 5.1 turns ANY native-command stderr line into a terminating
# error -- and `uv run` legitimately writes progress (e.g. "Building oraflow @
# ...") and deprecation notices to stderr, especially right after a version bump
# when it rebuilds the local package. We drop to 'Continue' for the call and rely
# on the real exit code instead.
function Invoke-Native {
    param([Parameter(Mandatory)][scriptblock]$Action, [Parameter(Mandatory)][string]$What)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Action } finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}
function Get-NextVersion([string]$Current, [string]$Kind) {
    $parts = $Current.Split('.')
    if ($parts.Count -ne 3) { throw "Version '$Current' is not in x.y.z form." }
    [int]$maj = $parts[0]; [int]$min = $parts[1]; [int]$pat = $parts[2]
    switch ($Kind) {
        'major' { $maj++; $min = 0; $pat = 0 }
        'minor' { $min++; $pat = 0 }
        'patch' { $pat++ }
    }
    return "$maj.$min.$pat"
}

function Set-FileVersion([string]$Path, [string]$Pattern, [string]$NewVersion) {
    if (-not (Test-Path -LiteralPath $Path)) { Write-Output "  (skip, not found) $Path"; return }
    $raw = Get-Content -LiteralPath $Path -Raw
    $new = [regex]::Replace($raw, $Pattern, { param($m) $m.Groups[1].Value + $NewVersion + $m.Groups[2].Value })
    if ($new -ne $raw) {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($Path, $new, $utf8NoBom)
        Write-Output "  updated $Path"
    } else {
        Write-Output "  WARNING: no version pattern matched in $Path"
    }
}

function Remove-SqlplusBundleBloat($SqlplusRoot) {
    if (-not (Test-Path -LiteralPath $SqlplusRoot)) { return }
    $bin = Join-Path $SqlplusRoot 'bin'
    $remove = @()
    if (Test-Path -LiteralPath $bin) {
        # NOTE: Get-ChildItem -Include is silently ignored when used with
        # -LiteralPath and no -Recurse/wildcard, so the old call matched EVERY
        # file and wiped the entire bin (sqlplus.exe and all its DLLs) from the
        # source tree on every build. Filter by extension explicitly instead.
        $remove += Get-ChildItem -LiteralPath $bin -File -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Extension -in '.bat', '.cmd', '.com' -or
                ($_.Extension -eq '.exe' -and $_.Name -ne 'sqlplus.exe')
            }
    }
    $lbuilder = Join-Path $SqlplusRoot 'nls\lbuilder'
    if (Test-Path -LiteralPath $lbuilder) { $remove += Get-Item -LiteralPath $lbuilder }

    $items = @($remove | Where-Object { $_ })
    if ($items.Count -eq 0) {
        Write-Output "SQL*Plus bundle already trimmed."
        return
    }
    $bytes = ($items | ForEach-Object {
        if ($_.PSIsContainer) {
            (Get-ChildItem -LiteralPath $_.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
        } else {
            $_.Length
        }
    } | Measure-Object -Sum).Sum
    $items | Sort-Object FullName -Descending | Remove-Item -Recurse -Force
    Write-Output ("Removed {0} unused SQL*Plus tool item(s), freeing {1:N2} MB." -f $items.Count, ($bytes / 1MB))
}

function Update-FastMcpBundle($BackendRoot) {
    $fastmcpRoot = Join-Path $BackendRoot '_internal\fastmcp'
    if (-not (Test-Path -LiteralPath $fastmcpRoot)) { return }

    $remove = @(
        (Join-Path $fastmcpRoot 'cli'),
        (Join-Path $fastmcpRoot 'utilities\skills.py')
    )
    $removed = 0
    foreach ($path in $remove) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
            $removed++
        }
    }

    $versionCheck = Join-Path $fastmcpRoot 'utilities\version_check.py'
    if (Test-Path -LiteralPath $versionCheck) {
        @'
from __future__ import annotations


def get_latest_version(include_prereleases: bool = False) -> str | None:
    return None


def check_for_newer_version(
    current_version: str | None = None,
    include_prereleases: bool = False,
) -> str | None:
    return None
'@ | Set-Content -LiteralPath $versionCheck -Encoding UTF8
    }

    Write-Output ("Trimmed FastMCP optional CLI/download helpers ({0} item(s) removed; version check stubbed)." -f $removed)
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$extensionRoot = Join-Path $repoRoot 'extensions\vscode'
$packageJsonPath = Join-Path $extensionRoot 'package.json'
$pyprojectPath = Join-Path $repoRoot 'pyproject.toml'
$initPath = Join-Path $repoRoot 'src\oraflow\__init__.py'

Write-Section "Version"
$currentVersion = (Get-Content -LiteralPath $packageJsonPath -Raw | ConvertFrom-Json).version
if ($SetVersion) {
    if ($SetVersion -notmatch '^\d+\.\d+\.\d+$') { throw "-SetVersion must be x.y.z (got '$SetVersion')." }
    $newVersion = $SetVersion
} elseif ($Bump -eq 'none') {
    $newVersion = $currentVersion
} else {
    $newVersion = Get-NextVersion $currentVersion $Bump
}
if ($newVersion -ne $currentVersion) {
    Write-Output ("OraFlow extension version: {0} -> {1} (keeps every build on a fresh VS Code extension folder)" -f $currentVersion, $newVersion)
} else {
    Write-Output ("OraFlow extension version: {0} (no bump)" -f $currentVersion)
}
# Sync all three version sources (package.json drives the VSIX name; pyproject
# and __init__ drive the frozen backend's oraflow_version). Always write so a
# pre-existing drift between them is corrected.
Set-FileVersion $packageJsonPath '("version"\s*:\s*")\d+\.\d+\.\d+(")' $newVersion
Set-FileVersion $pyprojectPath '(?m)^(version\s*=\s*")\d+\.\d+\.\d+(")' $newVersion
Set-FileVersion $initPath '(__version__\s*=\s*")\d+\.\d+\.\d+(")' $newVersion
$version = $newVersion

Write-Section "Clean generated outputs"
$pathsToRemove = @(
    (Join-Path $repoRoot 'build'),
    (Join-Path $repoRoot 'dist'),
    (Join-Path $extensionRoot 'dist')
)
foreach ($path in $pathsToRemove) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
        Write-Output ("Removed {0}" -f $path)
    }
}
Get-ChildItem -LiteralPath $extensionRoot -Filter '*.vsix' -File -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force
        Write-Output ("Removed {0}" -f $_.FullName)
    }
Get-ChildItem -LiteralPath $extensionRoot -Filter 'oraflow-*.zip' -File -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force
        Write-Output ("Removed {0}" -f $_.FullName)
    }

try {
    Write-Section "Build frozen MCP backend"
    Push-Location $repoRoot
    try {
        Invoke-Native { uv run pyinstaller .\oraflow-mcp.spec --clean --noconfirm } 'PyInstaller'
    } finally {
        Pop-Location
    }

    Write-Section "Refresh bundled backend"
    $sourceBackend = Join-Path $repoRoot 'dist\oraflow-mcp'
    $targetBackend = Join-Path $extensionRoot 'bin\win32-x64\oraflow-mcp'
    if (-not (Test-Path -LiteralPath $sourceBackend)) {
        throw "Expected PyInstaller output not found: $sourceBackend"
    }
    if (Test-Path -LiteralPath $targetBackend) {
        Remove-Item -LiteralPath $targetBackend -Recurse -Force
        Write-Output ("Removed stale bundled backend {0}" -f $targetBackend)
    }
    New-Item -ItemType Directory -Path $targetBackend -Force | Out-Null
    Copy-Item -Path (Join-Path $sourceBackend '*') -Destination $targetBackend -Recurse -Force
    Update-FastMcpBundle $targetBackend
    Get-Item -LiteralPath (Join-Path $targetBackend 'oraflow-mcp.exe') |
        Select-Object FullName, Length, LastWriteTime |
        Format-List |
        Out-String |
        Write-Output

    Write-Section "Build and package VSIX"
    Write-Section "Trim bundled SQL*Plus runtime"
    Remove-SqlplusBundleBloat (Join-Path $extensionRoot 'bin\win32-x64\sqlplus12')

    Push-Location $extensionRoot
    try {
        if (-not $SkipNpmInstall) {
            if (Test-Path -LiteralPath (Join-Path $extensionRoot 'package-lock.json')) {
                Invoke-Native { npm ci --no-audit --no-fund } 'npm ci'
            } else {
                Invoke-Native { npm install --no-audit --no-fund } 'npm install'
            }
        }
        Invoke-Native { npm run build } 'npm run build'
        Invoke-Native { npm run package } 'vsce package'
    } finally {
        Pop-Location
    }

    Write-Section "Result"
    $vsix = Get-ChildItem -LiteralPath $extensionRoot -Filter ("oraflow-{0}.vsix" -f $version) -File -ErrorAction Stop |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $vsix) {
        throw "Expected VSIX was not created for version $version."
    }
    [pscustomobject]@{
        Version = $version
        Vsix = $vsix.FullName
        Length = $vsix.Length
        LastWriteTime = $vsix.LastWriteTime
    } | ConvertTo-Json -Depth 4
} finally {
    Write-Section "Post-build cleanup"
    if (-not $KeepBuildArtifacts) {
        foreach ($path in @((Join-Path $repoRoot 'build'), (Join-Path $repoRoot 'dist'), (Join-Path $extensionRoot 'dist'))) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Recurse -Force
                Write-Output ("Removed transient build output {0}" -f $path)
            }
        }
    } else {
        Write-Output "-KeepBuildArtifacts specified; leaving build/, dist/, and extension dist/."
    }

    if (-not $KeepNodeModules) {
        $nodeModules = Join-Path $extensionRoot 'node_modules'
        if (Test-Path -LiteralPath $nodeModules) {
            Remove-Item -LiteralPath $nodeModules -Recurse -Force
            Write-Output ("Removed transient npm install folder {0}" -f $nodeModules)
        }
    } else {
        Write-Output "-KeepNodeModules specified; leaving extension node_modules/."
    }
}