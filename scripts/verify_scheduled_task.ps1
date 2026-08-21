# Verify that the Crypto Trading Paper Runtime scheduled task exists and is healthy
[CmdletBinding()]
param(
    [string]$TaskName = 'Crypto Trading Paper Runtime'
)

$ErrorActionPreference = 'Stop'

Write-Host "=" * 60
Write-Host "Scheduled Task Verification"
Write-Host "=" * 60
Write-Host

try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Write-Host "[PASS] Task exists: $TaskName"
    Write-Host "  State: $($task.State)"
    Write-Host "  Triggers:"
    foreach ($trigger in $task.Triggers) {
        Write-Host "    - $($trigger.CimClass.CimClassName): DaysOfWeek=$($trigger.DaysOfWeek) At=$($trigger.StartBoundary)"
    }
    Write-Host "  Settings:"
    Write-Host "    ExecutionTimeLimit: $($task.Settings.ExecutionTimeLimit)"
    Write-Host "    RestartCount: $($task.Settings.RestartCount)"
    Write-Host "    RestartInterval: $($task.Settings.RestartInterval)"
    Write-Host

    # Check last run result
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($info) {
        Write-Host "  LastRunTime: $($info.LastRunTime)"
        Write-Host "  LastTaskResult: $($info.LastTaskResult)"
        Write-Host "  NextRunTime: $($info.NextRunTime)"
        if ($info.LastTaskResult -eq 0) {
            Write-Host "[PASS] Last run succeeded"
        } else {
            Write-Host "[WARN] Last run result: $($info.LastTaskResult)"
        }
    }
    Write-Host
    Write-Host "Verification PASSED"
} catch {
    Write-Host "[FAIL] Task not found: $TaskName"
    Write-Host "  Run install_paper_runtime_task.ps1 to create it"
    exit 1
}

Write-Host "=" * 60
