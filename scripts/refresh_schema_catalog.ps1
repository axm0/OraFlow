<#
.SYNOPSIS
    Refresh the schema catalog from the monolithic dumps in trexone_data_dumps\.
.DESCRIPTION
    Re-runs the splitter on every TREXONE_*_tables.sql dump in trexone_data_dumps\
    and writes per-table .sql files into the appropriate layer folder under schemas\.
    Layer mapping:
      TREXONE_DATA      -> schemas\oltp\trexone_data
      TREXONE_ODS_DATA  -> schemas\olap\trexone_ods_data
      TREXONE_AUD_DATA  -> schemas\olap\trexone_aud_data
      TREXONE_DW_DATA   -> schemas\olap\trexone_dw_data
.NOTES
    Run the four extract_trexone_*_ddl.sql scripts in Toad first to refresh
    the dumps, then run this script. End-to-end refresh of the AI grounding
    catalog.
#>
param(
    [string]$DumpsDir   = 'trexone_data_dumps',
    [string]$SchemasDir = 'schemas',
    [string]$Python     = '.\.venv\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
$mapping = @(
    @{ Schema = 'TREXONE_DATA';     Layer = 'oltp'; Folder = 'trexone_data'     },
    @{ Schema = 'TREXONE_ODS_DATA'; Layer = 'olap'; Folder = 'trexone_ods_data' },
    @{ Schema = 'TREXONE_AUD_DATA'; Layer = 'olap'; Folder = 'trexone_aud_data' },
    @{ Schema = 'TREXONE_DW_DATA';  Layer = 'olap'; Folder = 'trexone_dw_data'  }
)
foreach ($m in $mapping) {
    $dump = Join-Path $DumpsDir "$($m.Schema)_tables.sql"
    $out  = Join-Path $SchemasDir (Join-Path $m.Layer $m.Folder)
    if (-not (Test-Path $dump)) {
        Write-Host "skip $($m.Schema): dump not found at $dump" -ForegroundColor Yellow
        continue
    }
    Write-Host "splitting $($m.Schema) -> $out" -ForegroundColor Cyan
    & $Python 'scripts\split_ddl_dump.py' $dump $out --schema $m.Schema
}
Write-Host "`n=== Final state ===" -ForegroundColor Green
Get-ChildItem -Path $SchemasDir -Directory -Recurse -Depth 1 |
    Where-Object { Get-ChildItem "$($_.FullName)\*.sql" -ErrorAction SilentlyContinue } |
    ForEach-Object {
        $files = (Get-ChildItem "$($_.FullName)\*.sql").Count
        "{0,-40} {1,5} files" -f $_.FullName.Replace($PWD.Path + '\',''), $files
    }
