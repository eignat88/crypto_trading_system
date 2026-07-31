[CmdletBinding()]
param(
    [ValidateSet('BTCUSDT', 'ETHUSDT')]
    [string]$Symbol = 'BTCUSDT',

    [string]$Interval = '1h',

    [string]$Exchange = 'bybit',

    [switch]$RunActiveChecks,

    [switch]$SkipCI
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonScript = Join-Path $PSScriptRoot 'diagnose_readiness.py'
$logDir = Join-Path $projectRoot 'logs'

if (-not (Test-Path -LiteralPath $pythonScript -PathType Leaf)) {
    throw "Diagnostic Python script not found: $pythonScript"
}

Set-Location -LiteralPath $projectRoot

$arguments = @(
    $pythonScript,
    '--exchange', $Exchange,
    '--symbol', $Symbol,
    '--interval', $Interval,
    '--log-dir', $logDir
)

if ($RunActiveChecks) {
    $arguments += '--run-active-checks'
}
if ($SkipCI) {
    $arguments += '--skip-ci'
}

Write-Host "Project: $projectRoot"
Write-Host "Logs:    $logDir"
Write-Host "Stream:  $Exchange $Symbol $Interval"
Write-Host ""

& python @arguments
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "Readiness decision: SUCCESS" -ForegroundColor Green
} elseif ($exitCode -eq 2) {
    Write-Host "Readiness decision: BLOCKED. Do not start the full history load." -ForegroundColor Yellow
} else {
    Write-Host "Diagnostic failed with exit code $exitCode." -ForegroundColor Red
}

exit $exitCode
