param(
    [string]$VsixPath
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $VsixPath) {
    $pkgVersion = (Get-Content -LiteralPath (Join-Path $repoRoot 'extensions\vscode\package.json') -Raw | ConvertFrom-Json).version
    $VsixPath = Join-Path $repoRoot ("extensions\vscode\oraflow-{0}.vsix" -f $pkgVersion)
}
$VsixPath = (Resolve-Path -LiteralPath $VsixPath).Path

Add-Type -AssemblyName System.IO.Compression.FileSystem
$tmp = Join-Path $env:TEMP ("v_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
try {
[System.IO.Compression.ZipFile]::ExtractToDirectory($VsixPath, $tmp)
$failures = 0

Write-Output ("=== VSIX: {0} ===" -f $VsixPath)

Write-Output "=== sqlnet.ora shipped inside VSIX ==="
Get-Content "$tmp\extension\oracle-network\admin\sqlnet.ora"
Write-Output ""
Write-Output "=== SQL*Plus 12.2 fallback sqlnet.ora shipped inside VSIX ==="
Get-Content "$tmp\extension\bin\win32-x64\sqlplus12\network\admin\sqlnet.ora"
Write-Output ""

Write-Output "=== Code strings present in shipped minified extension.js ==="
$js = Get-Content -Raw "$tmp\extension\dist\extension.js"
$needles = @(
    'TNS_ADMIN', 'ORACLE_HOME',
    'ORAFLOW_INSTRUCTIONS_PATH', 'ORAFLOW_CUSTOMERS_PATH', 'ORAFLOW_CREDENTIALS_PATH',
    'ORAFLOW_SQLPLUS12_HOME',
    'ORAFLOW_THICK_MODE', 'ORAFLOW_ORACLE_CLIENT_LIB_DIR',
    'instantclient', 'sqlplus12', 'oraflow-mcp.exe',
    'configureMcp', 'setupCredentials', 'oraflow', 'Abdul Aziz Mohammed'
)
foreach ($n in $needles) {
    if ($js.Contains($n)) {
        Write-Output ("  [OK]  {0}" -f $n)
    } else {
        Write-Output ("  [!!]  MISSING: {0}" -f $n)
        $failures++
    }
}

Write-Output ""
Write-Output "=== ABSENT from shipped JS (stale OraFlow env/config names) ==="
foreach ($n in 'ORAFLOW_DBCREDS_PATH','backendPath','oracleClientLibDir','workspaceDir','C:\Oracle') {
    if ($js.Contains($n)) {
        Write-Output ("  [!!]  STILL PRESENT: {0}" -f $n)
        $failures++
    } else {
        Write-Output ("  [OK]  not present:  {0}" -f $n)
    }
}

Write-Output ""
Write-Output "=== ABSENT from shipped JS (confirms RADIUS bug NOT bundled) ==="
foreach ($n in 'RADIUS','SQLNET.AUTHENTICATION_SERVICES') {
    if ($js.Contains($n)) {
        Write-Output ("  [!!]  STILL PRESENT: {0}" -f $n)
        $failures++
    } else {
        Write-Output ("  [OK]  not present:  {0}" -f $n)
    }
}

$sqlnet = Get-Content -Raw "$tmp\extension\oracle-network\admin\sqlnet.ora"
Write-Output ""
Write-Output "=== IC23 sqlnet.ora content audit ==="
foreach ($n in 'RADIUS','LOG_DIRECTORY_CLIENT','TRACE_DIRECTORY_CLIENT','C:\Developer') {
    if ($sqlnet.Contains($n)) {
        Write-Output ("  [!!]  STILL CONTAINS: {0}" -f $n)
        $failures++
    } else {
        Write-Output ("  [OK]  removed:        {0}" -f $n)
    }
}

$sqlplusSqlnet = Get-Content -Raw "$tmp\extension\bin\win32-x64\sqlplus12\network\admin\sqlnet.ora"
Write-Output ""
Write-Output "=== SQL*Plus 12.2 fallback sqlnet.ora content audit ==="
foreach ($n in 'SQLNET.AUTHENTICATION_SERVICES=(RADIUS)','USE_DEDICATED_SERVER=OFF') {
    if ($sqlplusSqlnet.Contains($n)) {
        Write-Output ("  [OK]  present:        {0}" -f $n)
    } else {
        Write-Output ("  [!!]  MISSING:        {0}" -f $n)
        $failures++
    }
}

Write-Output ""
Write-Output "=== Required OraFlow assets ==="
foreach ($p in 'assets\ORAFLOW_INSTRUCTIONS.md','assets\customers.toml','assets\help-topics.toml','dist\extension.js') {
    $full = Join-Path "$tmp\extension" $p
    if (Test-Path $full) { Write-Output ("  [OK]  present: {0}" -f $p) } else { Write-Output ("  [!!]  MISSING: {0}" -f $p); $failures++ }
}

Write-Output ""
Write-Output "=== Uninstall hook packaged and wired ==="
$uninstallJs = Join-Path "$tmp\extension" 'uninstall.js'
if (Test-Path -LiteralPath $uninstallJs) {
    Write-Output "  [OK]  present: uninstall.js"
    $uninstallText = Get-Content -LiteralPath $uninstallJs -Raw
    foreach ($n in 'managed-workspaces.json','isManagedOraFlowServer','ORAFLOW AGENT INSTRUCTIONS') {
        if ($uninstallText.Contains($n)) { Write-Output ("  [OK]  uninstall.js references: {0}" -f $n) }
        else { Write-Output ("  [!!]  uninstall.js MISSING reference: {0}" -f $n); $failures++ }
    }
} else {
    Write-Output "  [!!]  MISSING: uninstall.js"
    $failures++
}
$shippedPkg = Get-Content -LiteralPath (Join-Path "$tmp\extension" 'package.json') -Raw | ConvertFrom-Json
if ($shippedPkg.scripts.'vscode:uninstall' -eq 'node ./uninstall.js') {
    Write-Output "  [OK]  package.json declares vscode:uninstall -> node ./uninstall.js"
} else {
    Write-Output ("  [!!]  package.json vscode:uninstall hook missing/incorrect: {0}" -f $shippedPkg.scripts.'vscode:uninstall')
    $failures++
}

Write-Output ""
Write-Output "=== SQL*Plus bundled runtime trim audit ==="
$sqlplusBin = Join-Path "$tmp\extension" 'bin\win32-x64\sqlplus12\bin'
$extraSqlplusTools = Get-ChildItem -LiteralPath $sqlplusBin -File -ErrorAction SilentlyContinue |
    Where-Object { ($_.Extension -in '.bat', '.cmd', '.com', '.exe') -and $_.Name -ne 'sqlplus.exe' }
$lbuilder = Join-Path "$tmp\extension" 'bin\win32-x64\sqlplus12\nls\lbuilder'
if ($extraSqlplusTools) {
    $extraSqlplusTools | Select-Object -First 50 | ForEach-Object { Write-Output ("  [!!]  EXTRA TOOL: {0}" -f $_.FullName.Substring(("$tmp\extension").Length + 1)) }
    $failures += @($extraSqlplusTools).Count
} else {
    Write-Output "  [OK]  no unused SQL*Plus batch/cmd/com/exe tools except sqlplus.exe"
}
if (Test-Path -LiteralPath $lbuilder) {
    Write-Output "  [!!]  SQL*Plus Locale Builder tooling still packaged: bin\win32-x64\sqlplus12\nls\lbuilder"
    $failures++
} else {
    Write-Output "  [OK]  SQL*Plus Locale Builder tooling absent"
}

Write-Output ""
Write-Output "=== Optional FastMCP download/check utility audit ==="
$forbiddenRuntimePaths = @(
    'bin\win32-x64\oraflow-mcp\_internal\fastmcp\cli',
    'bin\win32-x64\oraflow-mcp\_internal\fastmcp\utilities\skills.py'
)
foreach ($p in $forbiddenRuntimePaths) {
    $full = Join-Path "$tmp\extension" $p
    if (Test-Path -LiteralPath $full) {
        Write-Output ("  [!!]  STILL PACKAGED: {0}" -f $p)
        $failures++
    } else {
        Write-Output ("  [OK]  absent:         {0}" -f $p)
    }
}
$allRuntimeText = Get-ChildItem "$tmp\extension\bin\win32-x64\oraflow-mcp\_internal\fastmcp" -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in '.py','.md','.txt','.json' }
$forbiddenTextHits = $allRuntimeText | Select-String -Pattern 'https://pypi\.org/pypi/fastmcp/json','download_skill\(' -ErrorAction SilentlyContinue
if ($forbiddenTextHits) {
    $forbiddenTextHits | Select-Object -First 20 | ForEach-Object {
        Write-Output ("  [!!]  FORBIDDEN TEXT: {0}" -f $_.Path.Substring(("$tmp\extension").Length + 1))
    }
    $failures += @($forbiddenTextHits).Count
} else {
    Write-Output "  [OK]  no FastMCP PyPI version-check or skill-download helper strings"
}
$versionCheckPath = Join-Path "$tmp\extension" 'bin\win32-x64\oraflow-mcp\_internal\fastmcp\utilities\version_check.py'
if (Test-Path -LiteralPath $versionCheckPath) {
    $versionCheck = Get-Content -LiteralPath $versionCheckPath -Raw
    if ($versionCheck.Contains('return None') -and -not $versionCheck.Contains('httpx') -and -not $versionCheck.Contains('pypi.org')) {
        Write-Output "  [OK]  FastMCP version check is local no-op stub"
    } else {
        Write-Output "  [!!]  FastMCP version check is not the expected local no-op stub"
        $failures++
    }
} else {
    Write-Output "  [!!]  FastMCP version check stub missing"
    $failures++
}

Write-Output ""
Write-Output "=== Source/secrets leak audit ==="
$allFiles = Get-ChildItem "$tmp\extension" -Recurse -File -Force
$blocked = $allFiles | Where-Object {
    $rel = $_.FullName.Substring(("$tmp\extension").Length + 1).Replace('/','\')
    ($rel -match '(^|\\)(src|tests|\.git|\.github|node_modules)(\\|$)') -or
    ($_.Name -match '(^test_.*\.py$|\.test\.js$|\.map$|package-lock\.json$|yarn\.lock$|pyproject\.toml$|requirements.*\.txt$|\.env$|credentials\.toml$|dbcreds\.env$|\.vsix$|\.ts$)') -or
    ($_.Extension -eq '.py' -and $rel -notmatch '^bin\\')
}
if ($blocked) {
    $blocked | Select-Object -First 50 | ForEach-Object { Write-Output ("  [!!]  BLOCKED: {0}" -f $_.FullName.Substring(("$tmp\extension").Length + 1)) }
    $failures += @($blocked).Count
} else {
    Write-Output "  [OK]  no obvious source/secrets leak files found"
}

if ($failures -gt 0) {
    Write-Output ""
    Write-Output ("!!! {0} INTERNAL VSIX CHECK(S) FAILED !!!" -f $failures)
    exit 1
}

Write-Output ""
Write-Output "*** ALL INTERNAL VSIX CHECKS PASSED ***"
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
exit 0

