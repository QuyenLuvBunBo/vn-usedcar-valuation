# Unattended driver: crawl bonbanh in 30-minute chunks (resumable), then run the v2 chain.
# Every step appends to logs\chain.log so progress can be checked without touching the process.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = 'utf-8'
$log = Join-Path $root 'logs\chain.log'
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = 'F:\Admin\miniconda3\python.exe' }
$patch = Join-Path $root 'data\processed\bonbanh_backfill.csv'

function Log([string]$message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $message" | Out-File -FilePath $log -Append -Encoding utf8
}

function Patch-Rows {
    if (Test-Path $patch) { return [int]((Get-Content $patch | Measure-Object -Line).Lines - 1) }
    return 0
}

Log "=== driver start (python=$python) ==="
$iterations = 0
while ($iterations -lt 40) {
    $iterations++
    $before = Patch-Rows
    Log "crawl chunk $iterations — patch rows $before / 7704"
    & $python -m tools.backfill_bonbanh --workers 3 --delay 2.5 --max-minutes 90 --flush-every 150 2>&1 |
        Out-File -FilePath $log -Append -Encoding utf8
    $exit = $LASTEXITCODE
    $rows = Patch-Rows
    Log "  chunk $iterations finished: patch rows $rows (+$($rows - $before)) exit=$exit"
    if ($rows -ge 7704) { break }
    if ($rows -gt $before) {
        Start-Sleep -Seconds 30                 # the chunk made progress: just keep going
    } else {
        Log '  no progress this chunk — sleeping 10 min before retrying'
        Start-Sleep -Seconds 600
    }
}

Log 'crawl loop finished — running the v2 chain'
foreach ($step in @(
    @('-m', 'tools.apply_backfill', '--write'),
    @('-m', 'src.features.extend', '--write', '--cohort-dir', 'data/master/v2'),
    @('-m', 'tools.feature_steps_eval', '--out', 'data/master/feature_steps_v2.json', '--doc', 'docs/features_steps_v2.md'),
    @('-m', 'tools.generalisation_check', '--features', 'v2')
)) {
    Log "run: $($step -join ' ')"
    & $python @step 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    Log "  exit=$LASTEXITCODE"
}
Log '=== driver done ==='

