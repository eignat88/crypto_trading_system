[CmdletBinding()]
param(
    [string]$TaskName = 'Crypto Trading Paper Runtime',
    [string]$ProjectRoot = 'D:\py_pro\crypto_trading_system',
    [string]$StartAt = '08:55'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$scriptPath = Join-Path $ProjectRoot 'scripts\start_paper_runtime.ps1'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "Paper runtime script not found: $scriptPath"
}

$actionArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ProjectRoot `"$ProjectRoot`""
$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument $actionArguments

$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At $StartAt

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'Scheduled paper trading runtime for crypto_trading_system' `
    -Force
