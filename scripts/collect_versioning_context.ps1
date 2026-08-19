$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OutputDir = Join-Path $ProjectRoot "artifacts\diagnostics"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutputFile = Join-Path $OutputDir "versioning_context_$Timestamp.txt"

function Add-Header {
    param(
        [string]$Title
    )

    Add-Content -Path $OutputFile -Value ""
    Add-Content -Path $OutputFile -Value ("=" * 100)
    Add-Content -Path $OutputFile -Value $Title
    Add-Content -Path $OutputFile -Value ("=" * 100)
    Add-Content -Path $OutputFile -Value ""
}

function Add-FileContent {
    param(
        [string]$RelativePath
    )

    $FullPath = Join-Path $ProjectRoot $RelativePath

    Add-Header "FILE: $RelativePath"

    if (Test-Path $FullPath) {
        Get-Content $FullPath |
            Out-String |
            Add-Content -Path $OutputFile
    }
    else {
        Add-Content -Path $OutputFile -Value "FILE NOT FOUND: $FullPath"
    }
}


Set-Content -Path $OutputFile -Value "crypto_trading_system - versioning implementation context"
Add-Content -Path $OutputFile -Value "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
Add-Content -Path $OutputFile -Value "Project: $ProjectRoot"


# --------------------------------------------------------------------
# Git state
# --------------------------------------------------------------------

Add-Header "GIT STATUS"

Push-Location $ProjectRoot

try {
    git status --short |
        Out-String |
        Add-Content -Path $OutputFile
}
finally {
    Pop-Location
}


Add-Header "GIT HEAD"

Push-Location $ProjectRoot

try {
    git log -1 --oneline |
        Out-String |
        Add-Content -Path $OutputFile
}
finally {
    Pop-Location
}


Add-Header "RECENT COMMITS"

Push-Location $ProjectRoot

try {
    git log --oneline -15 |
        Out-String |
        Add-Content -Path $OutputFile
}
finally {
    Pop-Location
}


# --------------------------------------------------------------------
# Indicator collectors
# --------------------------------------------------------------------

Add-FileContent "app\collectors\indicator_batch_collector.py"
Add-FileContent "app\collectors\indicator_collector.py"


# --------------------------------------------------------------------
# Indicator / regime implementation
# --------------------------------------------------------------------

Add-FileContent "app\indicators\market_regime.py"
Add-FileContent "app\indicators\volatility.py"


# --------------------------------------------------------------------
# Reproduction implementation
# --------------------------------------------------------------------

Add-FileContent "app\reporting\breakout_retest_v1_reproduction.py"
Add-FileContent "scripts\reproduce_breakout_retest_v1.py"


# --------------------------------------------------------------------
# Current SQL
# --------------------------------------------------------------------

Add-FileContent "database\migrations\008_create_backtest_audit.sql"
Add-FileContent "database\migrations\009_version_derived_backtest_dataset.sql"


# --------------------------------------------------------------------
# Find backtest persistence
# --------------------------------------------------------------------

Add-Header "SEARCH: backtest_run references"

Get-ChildItem (Join-Path $ProjectRoot "app") -Recurse -File |
    Select-String -Pattern "backtest_run" |
    ForEach-Object {
        "$($_.Path):$($_.LineNumber): $($_.Line.Trim())"
    } |
    Out-String |
    Add-Content -Path $OutputFile


Add-Header "SEARCH: INSERT INTO mart.backtest_run"

Get-ChildItem (Join-Path $ProjectRoot "app") -Recurse -File |
    Select-String -Pattern "INSERT INTO mart\.backtest_run" |
    ForEach-Object {
        "$($_.Path):$($_.LineNumber): $($_.Line.Trim())"
    } |
    Out-String |
    Add-Content -Path $OutputFile


# --------------------------------------------------------------------
# Find indicator persistence
# --------------------------------------------------------------------

Add-Header "SEARCH: INSERT INTO dds.indicator"

Get-ChildItem (Join-Path $ProjectRoot "app") -Recurse -File |
    Select-String -Pattern "INSERT INTO dds\.indicator" |
    ForEach-Object {
        "$($_.Path):$($_.LineNumber): $($_.Line.Trim())"
    } |
    Out-String |
    Add-Content -Path $OutputFile


Add-Header "SEARCH: dds.market_regime"

Get-ChildItem (Join-Path $ProjectRoot "app") -Recurse -File |
    Select-String -Pattern "dds\.market_regime" |
    ForEach-Object {
        "$($_.Path):$($_.LineNumber): $($_.Line.Trim())"
    } |
    Out-String |
    Add-Content -Path $OutputFile


# --------------------------------------------------------------------
# Search ON CONFLICT logic
# --------------------------------------------------------------------

Add-Header "SEARCH: ON CONFLICT in collectors/reporting/database"

$SearchPaths = @(
    (Join-Path $ProjectRoot "app\collectors"),
    (Join-Path $ProjectRoot "app\reporting"),
    (Join-Path $ProjectRoot "app\database")
)

foreach ($SearchPath in $SearchPaths) {
    if (Test-Path $SearchPath) {
        Get-ChildItem $SearchPath -Recurse -File |
            Select-String -Pattern "ON CONFLICT" |
            ForEach-Object {
                "$($_.Path):$($_.LineNumber): $($_.Line.Trim())"
            } |
            Out-String |
            Add-Content -Path $OutputFile
    }
}


# --------------------------------------------------------------------
# Python files likely related to persistence
# --------------------------------------------------------------------

Add-Header "APP DATABASE FILES"

$DatabaseDir = Join-Path $ProjectRoot "app\database"

if (Test-Path $DatabaseDir) {
    Get-ChildItem $DatabaseDir -Recurse -File |
        Select-Object FullName |
        Format-Table -AutoSize |
        Out-String |
        Add-Content -Path $OutputFile
}
else {
    Add-Content -Path $OutputFile -Value "app\database not found"
}


Add-Header "REPORTING FILES"

Get-ChildItem (Join-Path $ProjectRoot "app\reporting") -File |
    Select-Object Name |
    Format-Table -AutoSize |
    Out-String |
    Add-Content -Path $OutputFile


# --------------------------------------------------------------------
# Tests related to affected components
# --------------------------------------------------------------------

Add-Header "RELEVANT UNIT TEST FILES"

Get-ChildItem (Join-Path $ProjectRoot "tests\unit") -File |
    Where-Object {
        $_.Name -match "indicator|regime|backtest|breakout"
    } |
    Select-Object Name |
    Sort-Object Name |
    Format-Table -AutoSize |
    Out-String |
    Add-Content -Path $OutputFile


Add-Header "END"

Add-Content -Path $OutputFile -Value "Collection completed successfully."

Write-Host ""
Write-Host "Context saved:"
Write-Host $OutputFile
Write-Host ""