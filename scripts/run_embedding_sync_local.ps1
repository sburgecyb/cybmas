# Run JIRA → pgvector embedding worker against .env.local (repo root).
#
# Prereqs:
#   - PostgreSQL reachable via DATABASE_URL in .env.local (with pgvector + migrations + Default BU)
#   - Redis via REDIS_URL (delta mode stores last_sync here)
#   - JIRA_BASE_URL, JIRA_API_TOKEN, JIRA_USER_EMAIL
#   - GCP_PROJECT_ID + Vertex auth (GOOGLE_APPLICATION_CREDENTIALS or gcloud auth application-default login)
#
# asyncpg often has no wheel on bleeding-edge Python — use 3.11 or 3.12 venv:
#   py -3.12 -m venv .venv-embedding
#   .\.venv-embedding\Scripts\pip install -r pipeline\embedding_worker\requirements.txt
#
# Usage (from repo root):
#   .\scripts\run_embedding_sync_local.ps1
#   .\scripts\run_embedding_sync_local.ps1 -SyncMode full
#   .\scripts\run_embedding_sync_local.ps1 -Python .\.venv-embedding\Scripts\python.exe

param(
    [ValidateSet("delta", "full")]
    [string] $SyncMode = "delta",
    [string] $Python = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $RepoRoot "pipeline\embedding_worker\main.py"))) {
    Write-Error "Could not find repo root (expected pipeline\embedding_worker\main.py under $RepoRoot)"
}
Set-Location $RepoRoot

function Find-Python {
    if ($Python -and (Test-Path $Python)) { return (Resolve-Path $Python).Path }
    if ($env:PYTHON_EMBEDDING_SYNC -and (Test-Path $env:PYTHON_EMBEDDING_SYNC)) {
        return (Resolve-Path $env:PYTHON_EMBEDDING_SYNC).Path
    }
    $candidates = @(
        (Join-Path $RepoRoot ".venv-embedding\Scripts\python.exe"),
        (Join-Path $RepoRoot ".venv\Scripts\python.exe")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return (Resolve-Path $c).Path }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Error @"
No suitable Python found. Install Python 3.11 or 3.12, then:

  cd $RepoRoot
  py -3.12 -m venv .venv-embedding
  .\.venv-embedding\Scripts\pip install -r pipeline\embedding_worker\requirements.txt

Or pass -Python path\to\python.exe
"@
}

Write-Host "Using: $py"
& $py -c "import asyncpg, redis, httpx; print('deps ok')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing pipeline/embedding_worker/requirements.txt ..."
    & $py -m pip install -r (Join-Path $RepoRoot "pipeline\embedding_worker\requirements.txt")
}

$env:SYNC_MODE = $SyncMode
Write-Host "SYNC_MODE=$SyncMode"
& $py (Join-Path $RepoRoot "pipeline\embedding_worker\main.py")
