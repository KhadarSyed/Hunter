# Starts everything HunterAgent needs locally, in order:
#   1. the Docker engine (Rancher Desktop via rdctl, if Docker is not answering)
#   2. the hunter-postgres container (port 5433)
#   3. the FastAPI backend on http://localhost:8002 (also serves the built SPA)
#   4. the Vite dev server on http://localhost:5173
# Anything already running is left as it is. Logs: data\logs\backend.*.log, data\logs\frontend.log
# Usage (repo root):  powershell -ExecutionPolicy Bypass -File deploy\start-all.ps1

# Continue, not Stop: in Windows PowerShell 5.1 any stderr line from docker/npm would abort the script.
# Failures are checked through $LASTEXITCODE and thrown explicitly below.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null

$BACKEND_PORT = 8002
$FRONTEND_PORT = 5173
$DB_CONTAINER = "hunter-postgres"
$RDCTL = "C:\Program Files\Rancher Desktop\resources\resources\win32\bin\rdctl.exe"

function Test-Port([int]$port) {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Until([scriptblock]$check, [int]$seconds, [string]$what) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (& $check) { return }
        Start-Sleep -Seconds 2
    }
    throw "Timed out after $seconds s waiting for $what"
}

function Test-Docker {
    docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
    $LASTEXITCODE -eq 0
}

# A python that can run the backend (a stray venv first on PATH may lack its packages).
function Find-Python {
    $candidates = @(
        (Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object Source)
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
        "C:\Program Files\Python312\python.exe"
    ) | Where-Object { $_ -and (Test-Path $_) -and $_ -notlike "*WindowsApps*" } | Select-Object -Unique
    foreach ($py in $candidates) {
        & $py -c "import uvicorn, fastapi, psycopg, cryptography" 2>$null
        if ($LASTEXITCODE -eq 0) { return $py }
    }
    throw "No Python with the backend packages found. Run: pip install -r backend\requirements.txt"
}

# 1. Docker engine
if (-not (Test-Docker)) {
    if (-not (Test-Path $RDCTL)) { throw "Docker is not answering and Rancher Desktop (rdctl) was not found. Start Docker manually." }
    Write-Host "Docker is not answering; starting Rancher Desktop..."
    & $RDCTL start | Out-Null
    Wait-Until { Test-Docker } 300 "the Docker engine"
}
Write-Host "Docker engine: ready"

# 2. Containers
docker start $DB_CONTAINER | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not start $DB_CONTAINER. Create it with: docker compose -f deploy\docker-compose.postgres.yml up -d" }
Write-Host "Waiting for Postgres to accept connections (after a crash it first recovers)..."
Wait-Until { docker exec $DB_CONTAINER pg_isready -U hunter 2>$null | Out-Null; $LASTEXITCODE -eq 0 } 180 "Postgres"
Write-Host "Postgres ($DB_CONTAINER, port 5433): ready"


# 3. Backend
if (Test-Port $BACKEND_PORT) {
    Write-Host "Backend: already running on port $BACKEND_PORT"
} else {
    $py = Find-Python
    Write-Host "Starting backend with $py ..."
    Start-Process -WindowStyle Hidden -FilePath $py -WorkingDirectory $root `
        -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "$BACKEND_PORT" `
        -RedirectStandardOutput (Join-Path $logs "backend.out.log") -RedirectStandardError (Join-Path $logs "backend.err.log")
    try {
        Wait-Until { Test-Port $BACKEND_PORT } 120 "the backend"
    } catch {
        Get-Content (Join-Path $logs "backend.err.log") -Tail 15
        throw
    }
}

# 4. Frontend dev server
if (Test-Port $FRONTEND_PORT) {
    Write-Host "Frontend: already running on port $FRONTEND_PORT"
} else {
    Write-Host "Starting Vite dev server..."
    Start-Process -WindowStyle Hidden -FilePath "cmd.exe" -WorkingDirectory (Join-Path $root "frontend") `
        -ArgumentList "/c", "npm run dev > `"$(Join-Path $logs 'frontend.log')`" 2>&1"
    Wait-Until { Test-Port $FRONTEND_PORT } 60 "the Vite dev server"
}

Write-Host ""
Write-Host "HunterAgent is running:"
Write-Host "  Backend + built app : http://localhost:$BACKEND_PORT"
Write-Host "  Frontend (dev)      : http://localhost:$FRONTEND_PORT"
Write-Host "  Logs                : $logs"
