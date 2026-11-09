# Stops what deploy\start-all.ps1 started: the Vite dev server (5173), the backend (8002) and the
# hunter-postgres / hunter-objects containers. Rancher Desktop itself keeps running (other projects use it).
# Stopping the backend kills any running deck or tagging job, so the script refuses while jobs are
# running or queued unless you pass -Force.
# Usage (repo root):  powershell -ExecutionPolicy Bypass -File deploy\stop-all.ps1 [-Force]

param([switch]$Force)

$BACKEND_PORT = 8002
$FRONTEND_PORT = 5173
$CONTAINERS = @("hunter-postgres", "hunter-objects")

function Stop-Port([int]$port, [string]$name) {
    $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    if (-not $pids) { Write-Host "${name}: not running"; return }
    foreach ($procId in $pids) {
        taskkill /PID $procId /T /F 2>$null | Out-Null   # /T: also its children (npm -> node)
    }
    Write-Host "${name}: stopped (PID $($pids -join ', '))"
}

# Guard: running or queued jobs die with the backend.
$dbUp = (docker inspect -f "{{.State.Running}}" hunter-postgres 2>$null) -eq "true"
if ($dbUp -and -not $Force) {
    $active = docker exec hunter-postgres psql -U hunter -d hunter -tAc `
        "SELECT count(*) FROM intel_jobs WHERE status IN ('running','queued')" 2>$null
    if ($LASTEXITCODE -eq 0 -and [int]$active -gt 0) {
        Write-Warning "$active job(s) running or queued; stopping now would kill them. Wait, or rerun with -Force."
        exit 1
    }
}

Stop-Port $FRONTEND_PORT "Frontend (Vite)"
Stop-Port $BACKEND_PORT "Backend"

foreach ($c in $CONTAINERS) {
    if ((docker inspect -f "{{.State.Running}}" $c 2>$null) -eq "true") {
        docker stop $c | Out-Null
        Write-Host "${c}: stopped"
    } else {
        Write-Host "${c}: not running"
    }
}
Write-Host "All HunterAgent servers are stopped."
