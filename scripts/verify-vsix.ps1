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

function Get-TreeDigest($Root) {
    if (-not (Test-Path -LiteralPath $Root)) {
        return [pscustomobject]@{ Files = -1; Digest = 'MISSING' }
    }
    $rootPath = (Resolve-Path -LiteralPath $Root).Path
    $files = @(Get-ChildItem -LiteralPath $rootPath -Recurse -File -ErrorAction Stop | Sort-Object FullName)
    $lines = foreach ($file in $files) {
        $relative = $file.FullName.Substring($rootPath.Length).TrimStart('\', '/')
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        "{0} {1}" -f $relative, $hash
    }
    $combined = $lines -join "`n"
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($combined)
        $digest = [System.BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '')
    } finally {
        $sha.Dispose()
    }
    return [pscustomobject]@{ Files = $files.Count; Digest = $digest }
}

function Assert-SameFile($Left, $Right, $Label) {
    if (-not (Test-Path -LiteralPath $Left)) {
        Write-Output ("  [!!]  MISSING left file for {0}: {1}" -f $Label, $Left)
        $script:syncFailures++
        return
    }
    if (-not (Test-Path -LiteralPath $Right)) {
        Write-Output ("  [!!]  MISSING right file for {0}: {1}" -f $Label, $Right)
        $script:syncFailures++
        return
    }
    $leftHash = (Get-FileHash -LiteralPath $Left -Algorithm SHA256).Hash
    $rightHash = (Get-FileHash -LiteralPath $Right -Algorithm SHA256).Hash
    if ($leftHash -ne $rightHash) {
        Write-Output ("  [!!]  DRIFT  {0}" -f $Label)
        Write-Output ("        left:  {0}" -f $Left)
        Write-Output ("        right: {0}" -f $Right)
        $script:syncFailures++
        return
    }
    Write-Output ("  [OK]  {0}" -f $Label)
}

function Assert-SameTree($Left, $Right, $Label) {
    $leftDigest = Get-TreeDigest $Left
    $rightDigest = Get-TreeDigest $Right
    if ($leftDigest.Files -lt 0 -or $rightDigest.Files -lt 0 -or
        $leftDigest.Files -ne $rightDigest.Files -or
        $leftDigest.Digest -ne $rightDigest.Digest) {
        Write-Output ("  [!!]  DRIFT  {0}" -f $Label)
        Write-Output ("        left:  {0} ({1} files, {2})" -f $Left, $leftDigest.Files, $leftDigest.Digest)
        Write-Output ("        right: {0} ({1} files, {2})" -f $Right, $rightDigest.Files, $rightDigest.Digest)
        $script:syncFailures++
        return
    }
    Write-Output ("  [OK]  {0} ({1} files)" -f $Label, $leftDigest.Files)
}

function Assert-MaxMB($Label, $Bytes, $MaxMB) {
    $mb = $Bytes / 1MB
    if ($mb -gt $MaxMB) {
        Write-Output ("  [!!]  {0}: {1:N2} MB exceeds {2:N2} MB" -f $Label, $mb, $MaxMB)
        $script:bloatFailures++
        return
    }
    Write-Output ("  [OK]  {0}: {1:N2} MB <= {2:N2} MB" -f $Label, $mb, $MaxMB)
}

function Assert-MaxCount($Label, $Count, $MaxCount) {
    if ($Count -gt $MaxCount) {
        Write-Output ("  [!!]  {0}: {1:N0} exceeds {2:N0}" -f $Label, $Count, $MaxCount)
        $script:bloatFailures++
        return
    }
    Write-Output ("  [OK]  {0}: {1:N0} <= {2:N0}" -f $Label, $Count, $MaxCount)
}

function Assert-NoPackageEntries($RelativePaths, $Label) {
    $hits = @($RelativePaths | Where-Object {
        $_ -match '^(node_modules|\.venv|\.vscode|\.git|\.github|build|src|test|tests|context|prompts|trexone_data_dumps|OraFlow|mcp-main)(/|$)' -or
        $_ -match '^oracle-network/(log|trace)/' -or
        $_ -match '^package-lock\.json$' -or
        $_ -match '^extension\.js$' -or
        $_ -match '^\.vscodeignore$' -or
        $_ -match '^oraflow-.*\.(vsix|zip)$' -or
        $_ -match '\.(pyc|pyo|pdb|map|ts|tsx|pyi|bak|tmp|log|ipynb|sqlite|vscdb)$' -or
        $_ -match '(^|/)__pycache__(/|$)' -or
        $_ -match '^bin/.*/fastmcp/cli(/|$)' -or
        $_ -match '^bin/.*/fastmcp/utilities/skills\.py$'
    })
    if ($hits.Count -eq 0) {
        Write-Output ("  [OK]  {0}" -f $Label)
        return
    }

    Write-Output ("  [!!]  {0}: {1} unexpected package item(s)" -f $Label, $hits.Count)
    $hits | Select-Object -First 25 | ForEach-Object { Write-Output ("        {0}" -f $_) }
    if ($hits.Count -gt 25) { Write-Output ("        ... {0} more" -f ($hits.Count - 25)) }
    $script:bloatFailures++
}

$info = Get-Item $VsixPath
Write-Output "=== VSIX FILE ==="
Write-Output ("Path:    {0}" -f $info.FullName)
Write-Output ("Size:    {0:N2} MB" -f ($info.Length / 1MB))
Write-Output ("Built:   {0}" -f $info.LastWriteTime)
Write-Output ""

$tmp = Join-Path $env:TEMP ("oraflow_v_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
try {
[System.IO.Compression.ZipFile]::ExtractToDirectory($VsixPath, $tmp)
$ext = Join-Path $tmp "extension"

Write-Output "=== TOP-LEVEL CONTENTS ==="
Get-ChildItem $ext | ForEach-Object {
    if ($_.PSIsContainer) {
        $sz = (Get-ChildItem -Recurse $_.FullName -File -ErrorAction SilentlyContinue |
            Measure-Object Length -Sum).Sum / 1MB
        Write-Output ("  {0,9:N2} MB  {1}/" -f $sz, $_.Name)
    } else {
        Write-Output ("  {0,9:N2} KB  {1}" -f ($_.Length / 1KB), $_.Name)
    }
}

Write-Output ""
Write-Output "=== PACKAGE BLOAT GUARDS ==="
$bloatFailures = 0
$packageFiles = @(Get-ChildItem -Recurse $ext -File -Force -ErrorAction Stop)
$relativePackagePaths = @($packageFiles | ForEach-Object {
    $_.FullName.Substring($ext.Length).TrimStart('\', '/') -replace '\\', '/'
})
$allowedTopLevel = @('assets','bin','dist','oracle-network','schemas','license.txt','package.json','readme.md','uninstall.js')
$topLevelUnexpected = @(Get-ChildItem -LiteralPath $ext -Force | Where-Object { $allowedTopLevel -notcontains $_.Name.ToLowerInvariant() })
if ($topLevelUnexpected.Count -eq 0) {
    Write-Output "  [OK]  top-level package entries are expected"
} else {
    Write-Output ("  [!!]  unexpected top-level package entries: {0}" -f (($topLevelUnexpected | ForEach-Object { $_.Name }) -join ', '))
    $bloatFailures++
}
Assert-NoPackageEntries $relativePackagePaths 'no source/cache/temp/debug artifacts packaged'

$maxVsixMB = 235
$maxUncompressedMB = 675
$maxBackendMB = 90
$maxInstantClientMB = 320
$maxSqlplusMB = 270
$maxPackageFiles = 6600

Write-Output ""
Write-Output "=== CRITICAL FILE CHECKS ==="
$checks = @(
    'bin\win32-x64\oraflow-mcp\oraflow-mcp.exe',
    'bin\win32-x64\oraflow-mcp\_internal\ORAFLOW_INSTRUCTIONS.md',
    'bin\win32-x64\oraflow-mcp\_internal\sqlglot\dialects\oracle.py',
    'bin\win32-x64\oraflow-mcp\_internal\oracledb\thin_impl.cp313-win_amd64.pyd',
    'bin\win32-x64\oraflow-mcp\_internal\oracledb\thick_impl.cp313-win_amd64.pyd',
    'bin\win32-x64\oraflow-mcp\_internal\rapidfuzz',
    'bin\win32-x64\oraflow-mcp\_internal\dotenv',
    'bin\win32-x64\oraflow-mcp\_internal\rich',
    'bin\win32-x64\oraflow-mcp\_internal\typer',
    'bin\win32-x64\oraflow-mcp\_internal\truststore',
    'bin\win32-x64\oraflow-mcp\_internal\dns',
    'bin\win32-x64\oraflow-mcp\_internal\fastmcp',
    'bin\win32-x64\oraflow-mcp\_internal\mcp',
    'bin\win32-x64\oraflow-mcp\_internal\pydantic',
    'bin\win32-x64\oraflow-mcp\_internal\pydantic_settings',
    'bin\win32-x64\instantclient\oci.dll',
    'bin\win32-x64\instantclient\oraociei.dll',
    'bin\win32-x64\instantclient\orannz.dll',
    'bin\win32-x64\sqlplus12\bin\sqlplus.exe',
    'bin\win32-x64\sqlplus12\network\admin\sqlnet.ora',
    'bin\win32-x64\sqlplus12\sqlplus\mesg\sp1us.msb',
    'bin\win32-x64\sqlplus12\oracore\zoneinfo\timezlrg_26.dat',
    'oracle-network\admin\tnsnames.ora',
    'oracle-network\admin\cloud-tnsnames.ora',
    'oracle-network\admin\sqlnet.ora',
    'assets\ORAFLOW_INSTRUCTIONS.md',
    'dist\extension.js',
    'package.json',
    'LICENSE.txt'
)
$missing = 0
foreach ($p in $checks) {
    $full = Join-Path $ext $p
    if (Test-Path $full) {
        $item = Get-Item $full
        if ($item.PSIsContainer) {
            $n = (Get-ChildItem -Recurse $full -File | Measure-Object).Count
            Write-Output ("  [OK]  {0,5} files            {1}" -f $n, $p)
        } else {
            Write-Output ("  [OK]  {0,12:N0} bytes      {1}" -f $item.Length, $p)
        }
    } else {
        Write-Output ("  [!!]  MISSING                  {0}" -f $p)
        $missing++
    }
}

Write-Output ""
Write-Output "=== SOURCE / PACKAGE SYNC CHECKS ==="
$syncFailures = 0
Assert-SameFile (Join-Path $repoRoot 'tnsnames.ora') (Join-Path $repoRoot 'oracle-network\\admin\\tnsnames.ora') 'root tnsnames.ora == oracle-network/admin tnsnames.ora'
Assert-SameFile (Join-Path $repoRoot 'cloud-tnsnames.ora') (Join-Path $repoRoot 'oracle-network\\admin\\cloud-tnsnames.ora') 'root cloud-tnsnames.ora == oracle-network/admin cloud-tnsnames.ora'
Assert-SameFile (Join-Path $repoRoot 'oracle-network\\admin\\tnsnames.ora') (Join-Path $repoRoot 'extensions\\vscode\\oracle-network\\admin\\tnsnames.ora') 'source TNS == extension source TNS'
Assert-SameFile (Join-Path $repoRoot 'oracle-network\\admin\\cloud-tnsnames.ora') (Join-Path $repoRoot 'extensions\\vscode\\oracle-network\\admin\\cloud-tnsnames.ora') 'source cloud TNS == extension source cloud TNS'
Assert-SameFile (Join-Path $repoRoot 'oracle-network\\admin\\sqlnet.ora') (Join-Path $repoRoot 'extensions\\vscode\\oracle-network\\admin\\sqlnet.ora') 'source sqlnet.ora == extension source sqlnet.ora'
Assert-SameFile (Join-Path $repoRoot 'extensions\\vscode\\oracle-network\\admin\\tnsnames.ora') (Join-Path $ext 'oracle-network\\admin\\tnsnames.ora') 'extension source TNS == VSIX TNS'
Assert-SameFile (Join-Path $repoRoot 'extensions\\vscode\\oracle-network\\admin\\cloud-tnsnames.ora') (Join-Path $ext 'oracle-network\\admin\\cloud-tnsnames.ora') 'extension source cloud TNS == VSIX cloud TNS'
Assert-SameFile (Join-Path $repoRoot 'extensions\\vscode\\oracle-network\\admin\\sqlnet.ora') (Join-Path $ext 'oracle-network\\admin\\sqlnet.ora') 'extension source sqlnet.ora == VSIX sqlnet.ora'
Assert-SameFile (Join-Path $repoRoot 'ORAFLOW_INSTRUCTIONS.md') (Join-Path $repoRoot 'extensions\\vscode\\assets\\ORAFLOW_INSTRUCTIONS.md') 'root instructions == extension source instructions'
Assert-SameFile (Join-Path $repoRoot 'extensions\\vscode\\assets\\ORAFLOW_INSTRUCTIONS.md') (Join-Path $ext 'assets\\ORAFLOW_INSTRUCTIONS.md') 'extension source instructions == VSIX instructions asset'
Assert-SameFile (Join-Path $repoRoot 'extensions\\vscode\\assets\\ORAFLOW_INSTRUCTIONS.md') (Join-Path $ext 'bin\\win32-x64\\oraflow-mcp\\_internal\\ORAFLOW_INSTRUCTIONS.md') 'extension source instructions == backend internal instructions'
Assert-SameFile (Join-Path $repoRoot 'customers.toml') (Join-Path $repoRoot 'extensions\\vscode\\assets\\customers.toml') 'root customers.toml == extension source customers.toml'
Assert-SameFile (Join-Path $repoRoot 'extensions\\vscode\\assets\\customers.toml') (Join-Path $ext 'assets\\customers.toml') 'extension source customers.toml == VSIX customers.toml'
Assert-SameFile (Join-Path $repoRoot 'extensions\\vscode\\assets\\help-topics.toml') (Join-Path $ext 'assets\\help-topics.toml') 'extension source help topics == VSIX help topics'
Assert-SameTree (Join-Path $repoRoot 'schemas') (Join-Path $repoRoot 'extensions\\vscode\\schemas') 'root schemas == extension source schemas'
Assert-SameTree (Join-Path $repoRoot 'extensions\\vscode\\schemas') (Join-Path $ext 'schemas') 'extension source schemas == VSIX schemas'

Write-Output ""
Write-Output "=== INSTANT CLIENT FILES ==="
Get-ChildItem (Join-Path $ext 'bin\win32-x64\instantclient') -File |
    Sort-Object Name |
    ForEach-Object { Write-Output ("  {0,8:N2} MB  {1}" -f ($_.Length / 1MB), $_.Name) }

Write-Output ""
Write-Output "=== SCHEMA CATALOG ==="
foreach ($s in 'oltp\trexone_data','olap\trexone_aud_data','olap\trexone_dw_data','olap\trexone_ods_data') {
    $d = Join-Path $ext "schemas\$s"
    $n = (Get-ChildItem -Recurse $d -File -ErrorAction SilentlyContinue | Measure-Object).Count
    Write-Output ("  {0,-30}  {1,5} DDL files" -f $s, $n)
}

Write-Output ""
$bs = Get-ChildItem -Recurse (Join-Path $ext 'bin\win32-x64\oraflow-mcp') -File | Measure-Object Length -Sum
$is = Get-ChildItem -Recurse (Join-Path $ext 'bin\win32-x64\instantclient') -File | Measure-Object Length -Sum
$sp = Get-ChildItem -Recurse (Join-Path $ext 'bin\win32-x64\sqlplus12') -File | Measure-Object Length -Sum
$tot = Get-ChildItem -Recurse $ext -File | Measure-Object Length -Sum
Write-Output "=== SIZE BREAKDOWN ==="
Write-Output ("  Backend (PyInstaller):   {0,5} files    {1,7:N2} MB" -f $bs.Count, ($bs.Sum / 1MB))
Write-Output ("  Oracle Instant Client:   {0,5} files    {1,7:N2} MB" -f $is.Count, ($is.Sum / 1MB))
Write-Output ("  SQL*Plus 12.2 fallback:  {0,5} files    {1,7:N2} MB" -f $sp.Count, ($sp.Sum / 1MB))
Write-Output ("  TOTAL UNCOMPRESSED:      {0,5} files    {1,7:N2} MB" -f $tot.Count, ($tot.Sum / 1MB))
Write-Output ("  VSIX (compressed):       {0,7:N2} MB" -f ($info.Length / 1MB))

Write-Output ""
Write-Output "=== SIZE CEILINGS ==="
Assert-MaxMB 'VSIX compressed size' $info.Length $maxVsixMB
Assert-MaxMB 'total uncompressed package size' $tot.Sum $maxUncompressedMB
Assert-MaxMB 'frozen backend size' $bs.Sum $maxBackendMB
Assert-MaxMB 'Oracle Instant Client size' $is.Sum $maxInstantClientMB
Assert-MaxMB 'SQL*Plus fallback size' $sp.Sum $maxSqlplusMB
Assert-MaxCount 'total packaged files' $tot.Count $maxPackageFiles

Write-Output ""
if ($missing -gt 0 -or $syncFailures -gt 0 -or $bloatFailures -gt 0) {
    if ($missing -gt 0) { Write-Output ("!!! {0} CRITICAL FILE(S) MISSING !!!" -f $missing) }
    if ($syncFailures -gt 0) { Write-Output ("!!! {0} SOURCE/PACKAGE SYNC CHECK(S) FAILED !!!" -f $syncFailures) }
    if ($bloatFailures -gt 0) { Write-Output ("!!! {0} PACKAGE BLOAT CHECK(S) FAILED !!!" -f $bloatFailures) }
    $exitCode = 1
} else {
    Write-Output "*** ALL CRITICAL FILES PRESENT, SYNCED, AND SIZE-GUARDED ***"
    $exitCode = 0
}
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
exit $exitCode

