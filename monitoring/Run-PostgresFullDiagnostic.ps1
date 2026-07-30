[CmdletBinding()]
param(
    [string]$PsqlPath = "C:\Program Files\PostgreSQL\17\bin\psql.exe",
    [string]$Server = "localhost",
    [int]$Port = 5432,
    [string]$Database = "crypto_trading",
    [string]$User = "postgres",
    [string]$SqlFile = "",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDirectory = Split-Path -Parent $PSCommandPath

if ([string]::IsNullOrWhiteSpace($SqlFile)) {
    $SqlFile = Join-Path $scriptDirectory "postgres_full_diagnostic.sql"
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $scriptDirectory "diagnostic_reports"
}

function Assert-FileExists {
    param(
        [Parameter(Mandatory)]
        [string]$Path,
        [Parameter(Mandatory)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description not found: $Path"
    }
}

function ConvertTo-SafeFilePart {
    param([Parameter(Mandatory)][string]$Value)

    return ($Value -replace '[^a-zA-Z0-9._-]', '_')
}

Assert-FileExists -Path $PsqlPath -Description "psql.exe"
Assert-FileExists -Path $SqlFile -Description "Diagnostic SQL file"

if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$safeDatabase = ConvertTo-SafeFilePart -Value $Database
$reportPath = Join-Path $OutputDirectory "postgres_diagnostic_${safeDatabase}_${timestamp}.txt"
$errorPath = Join-Path $OutputDirectory "postgres_diagnostic_${safeDatabase}_${timestamp}.error.txt"
$metadataPath = Join-Path $OutputDirectory "postgres_diagnostic_${safeDatabase}_${timestamp}.metadata.json"

$metadata = [ordered]@{
    started_at_local = (Get-Date).ToString("o")
    computer_name = $env:COMPUTERNAME
    server = $Server
    port = $Port
    database = $Database
    database_user = $User
    psql_path = $PsqlPath
    sql_file = $SqlFile
    report_file = $reportPath
    status = "RUNNING"
}
$metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $metadataPath -Encoding UTF8

Write-Host ""
Write-Host "PostgreSQL full diagnostic" -ForegroundColor Cyan
Write-Host "Server:   ${Server}:${Port}"
Write-Host "Database: $Database"
Write-Host "User:     $User"
Write-Host "SQL:      $SqlFile"
Write-Host "Report:   $reportPath"
Write-Host ""
Write-Host "The script is read-only. It does not alter tables, indexes or settings." `
    -ForegroundColor Yellow
Write-Host "If PGPASSWORD is not set, psql will request the password interactively."
Write-Host ""

$psqlArguments = @(
    "-X",
    "--host=$Server",
    "--port=$Port",
    "--username=$User",
    "--dbname=$Database",
    "--set=ON_ERROR_STOP=1",
    "--file=$SqlFile"
)

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

try {
    & $PsqlPath @psqlArguments 1> $reportPath 2> $errorPath
    $exitCode = $LASTEXITCODE
}
catch {
    $exitCode = -1
    $_ | Out-String | Add-Content -LiteralPath $errorPath -Encoding UTF8
}
finally {
    $stopwatch.Stop()
}

$metadata.ended_at_local = (Get-Date).ToString("o")
$metadata.duration_seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 2)
$metadata.exit_code = $exitCode
$metadata.status = if ($exitCode -eq 0) { "SUCCESS" } else { "FAILED" }
$metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $metadataPath -Encoding UTF8

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "Diagnostic failed. Database changes were not made." -ForegroundColor Red
    Write-Host "Exit code: $exitCode"
    Write-Host "Error log: $errorPath"
    Write-Host ""
    Write-Host "Last error lines:" -ForegroundColor Yellow
    if (Test-Path -LiteralPath $errorPath) {
        Get-Content -LiteralPath $errorPath -Tail 30
    }
    exit $exitCode
}

if ((Test-Path -LiteralPath $errorPath) -and
    ((Get-Item -LiteralPath $errorPath).Length -eq 0)) {
    Remove-Item -LiteralPath $errorPath
}

Write-Host ""
Write-Host "Diagnostic completed successfully." -ForegroundColor Green
Write-Host "Duration: $([math]::Round($stopwatch.Elapsed.TotalMinutes, 2)) min"
Write-Host "Report:   $reportPath"
Write-Host "Metadata: $metadataPath"
Write-Host ""
Write-Host "Send the TXT report for analysis. Do not send passwords or API keys."
