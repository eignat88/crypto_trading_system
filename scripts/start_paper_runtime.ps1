[CmdletBinding()]
param(
    [string]$ProjectRoot = 'D:\py_pro\crypto_trading_system',
    [double]$DurationHours = 10,
    [string]$OutputReport
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$activateScript = Join-Path $ProjectRoot '.venv\Scripts\Activate.ps1'
$soakScript = Join-Path $ProjectRoot 'scripts\run_paper_soak.py'

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Project directory not found: $ProjectRoot"
}
if (-not (Test-Path -LiteralPath $activateScript -PathType Leaf)) {
    throw "Virtual environment activation script not found: $activateScript"
}
if (-not (Test-Path -LiteralPath $soakScript -PathType Leaf)) {
    throw "Paper soak runner not found: $soakScript"
}

Set-Location -LiteralPath $ProjectRoot

# Keep each scheduled run as separate acceptance evidence. An explicitly supplied
# path is still honoured for manual runs and backwards-compatible automation.
if ([string]::IsNullOrWhiteSpace($OutputReport)) {
    $runDate = Get-Date -Format 'yyyyMMdd'
    $OutputReport = "artifacts/paper_soak_report_$runDate.json"
}

# Activate the project's virtual environment and force the safe trading mode.
& $activateScript
$env:TRADING_MODE = 'paper'

python $soakScript `
    --duration-hours $DurationHours `
    --output-report $OutputReport

exit $LASTEXITCODE
