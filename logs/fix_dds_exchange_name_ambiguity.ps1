[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$PythonCommand = "python",
    [string]$Exchange = "bybit",
    [ValidateSet("BTCUSDT", "ETHUSDT")]
    [string]$Symbol = "BTCUSDT",
    [string]$Interval = "1h",
    [switch]$SkipLoadTest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-PythonStep {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    Write-Host "`n==> $Description" -ForegroundColor Cyan
    & $PythonCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $currentDirectory = (Get-Location).Path
    if (Test-Path -LiteralPath (Join-Path $currentDirectory "sql\005_raw_to_dds_etl.sql")) {
        $ProjectRoot = $currentDirectory
    }
    else {
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    }
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$migrationPath = Join-Path $ProjectRoot "sql\005_raw_to_dds_etl.sql"
$migrationRunner = Join-Path $ProjectRoot "scripts\apply_migrations.py"
$ddsLoader = Join-Path $ProjectRoot "scripts\load_dds.py"

foreach ($requiredPath in @($migrationPath, $migrationRunner, $ddsLoader)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file not found: $requiredPath"
    }
}

if (-not (Get-Command $PythonCommand -ErrorAction SilentlyContinue)) {
    throw "Python command not found: $PythonCommand"
}

$sql = [System.IO.File]::ReadAllText($migrationPath)
$directivePattern = '(?m)^#variable_conflict[ \t]+use_column[ \t]*\r?$'
$functionHeaderPattern = '(?m)^AS \$\$\r?\nDECLARE\r?$'
$patchedFunctionPattern = '(?m)^AS \$\$\r?\n#variable_conflict[ \t]+use_column[ \t]*\r?\nDECLARE\r?$'

if ([regex]::IsMatch($sql, $directivePattern)) {
    Write-Host "PL/pgSQL variable-conflict fix is already present." -ForegroundColor Yellow
}
else {
    $matches = [regex]::Matches($sql, $functionHeaderPattern)
    if ($matches.Count -ne 1) {
        throw "Expected exactly one load_raw_candles function body, found $($matches.Count). File was not changed."
    }

    $backupDirectory = Join-Path $env:TEMP "crypto_trading_system_backups"
    [System.IO.Directory]::CreateDirectory($backupDirectory) | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupPath = Join-Path $backupDirectory "005_raw_to_dds_etl_$timestamp.sql"
    [System.IO.File]::Copy($migrationPath, $backupPath, $false)

    $newline = if ($sql.Contains("`r`n")) { "`r`n" } else { "`n" }
    $replacement = 'AS $$' + $newline + '#variable_conflict use_column' + $newline + 'DECLARE'
    $targetMatch = $matches[0]
    $patchedSql = $sql.Substring(0, $targetMatch.Index) +
        $replacement +
        $sql.Substring($targetMatch.Index + $targetMatch.Length)

    if (-not [regex]::IsMatch($patchedSql, $patchedFunctionPattern)) {
        throw "Patch validation failed. Original migration was not overwritten."
    }

    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($migrationPath, $patchedSql, $utf8WithoutBom)

    Write-Host "Patched: $migrationPath" -ForegroundColor Green
    Write-Host "Backup:  $backupPath"
}

Push-Location $ProjectRoot
try {
    Invoke-PythonStep `
        -Description "Applying PostgreSQL migrations" `
        -Arguments @(".\scripts\apply_migrations.py")

    if (-not $SkipLoadTest) {
        Invoke-PythonStep `
            -Description "Running RAW to DDS verification for $Exchange $Symbol $Interval" `
            -Arguments @(
                ".\scripts\load_dds.py",
                "--exchange", $Exchange,
                "--symbol", $Symbol,
                "--interval", $Interval
            )
    }
}
finally {
    Pop-Location
}

Write-Host "`nFix applied successfully." -ForegroundColor Green
if ($SkipLoadTest) {
    Write-Host "DDS load test was skipped by request."
}
else {
    Write-Host "Run the same load_dds.py command once more; inserted=0 is expected when RAW has not changed."
}
