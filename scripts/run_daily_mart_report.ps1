# Run MART ETL and generate daily report
[CmdletBinding()]
param(
    [string]$ProjectRoot = 'D:\py_pro\crypto_trading_system',
    [string]$ReportDir = 'artifacts\reports'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$activateScript = Join-Path $ProjectRoot '.venv\Scripts\Activate.ps1'
$martScript = Join-Path $ProjectRoot 'scripts\load_mart.py'

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Project directory not found: $ProjectRoot"
}
if (-not (Test-Path -LiteralPath $activateScript -PathType Leaf)) {
    throw "Virtual environment activation script not found: $activateScript"
}

Set-Location -LiteralPath $ProjectRoot

# Activate the project's virtual environment
& $activateScript
$env:TRADING_MODE = 'paper'

# Create report directory if it doesn't exist
$reportPath = Join-Path $ProjectRoot $ReportDir
if (-not (Test-Path -LiteralPath $reportPath -PathType Container)) {
    New-Item -ItemType Directory -Path $reportPath -Force | Out-Null
}

Write-Host "Running MART ETL..."
python $martScript
$martExit = $LASTEXITCODE

if ($martExit -ne 0) {
    Write-Host "MART ETL failed with exit code: $martExit"
    exit $martExit
}

Write-Host "MART ETL completed successfully"

# Generate daily report
$date = Get-Date -Format "yyyy-MM-dd"
$dailyReport = Join-Path $reportPath "daily_report_$date.json"

Write-Host "Generating daily report: $dailyReport"
python -c "
from app.reporting.daily_report import DailyReportGenerator
from pathlib import Path

gen = DailyReportGenerator(exchange='bybit', symbols=('BTCUSDT', 'ETHUSDT'))
report = gen.generate(report_date=None)  # uses today
gen.write_report(report, '$($reportPath.Replace('\','/'))')
print(f'Daily report written: $dailyReport')
"

Write-Host "Done"
Write-Host "=" * 60
