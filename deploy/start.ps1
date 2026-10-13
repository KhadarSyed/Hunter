# Launches the Hunter brief-to-deck agent: builds the React frontend (if
# needed), starts the Python/FastAPI backend, and opens the browser at
# http://localhost:8000.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot   # the repo root (this script lives in deploy/)

# Refresh PATH from the registry
$machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"

# Try multiple Python installation locations
$pythonCandidates = @(
    "python3.exe",  # In PATH
    "python.exe",   # In PATH
    "C:\Program Files\Python312\python.exe",
    "C:\Program Files\Python311\python.exe",
    "C:\Program Files\Python310\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\python.exe",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python311\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe"
)

$pythonExe = $null
foreach ($candidate in $pythonCandidates) {
    $resolved = (Get-Command $candidate -ErrorAction SilentlyContinue).Source
    if ($resolved -and (Test-Path $resolved) -and $resolved -notlike "*Microsoft*") {
        $pythonExe = $resolved
        Write-Host "Found Python: $pythonExe"
        break
    }
}

if (-not $pythonExe) {
    Write-Error "Could not find a working Python interpreter. Install Python 3.11+ or add it to PATH."
    exit 1
}

$nodeExe = "C:\Program Files\nodejs\node.exe"

function Test-PortOpen($port) {
    try {
        $conn = New-Object System.Net.Sockets.TcpClient
        $conn.Connect("127.0.0.1", $port)
        $conn.Close()
        return $true
    } catch {
        return $false
    }
}

# 1. Build frontend if needed
$staticIndex = Join-Path $root "backend\static\index.html"
if (-not (Test-Path $staticIndex)) {
    Write-Host "Building frontend (first time)..."
    Push-Location (Join-Path $root "frontend")
    & $nodeExe "node_modules\vite\bin\vite.js" build --config vite.config.ts
    Pop-Location
} else {
    Write-Host "Frontend already built."
}

# 2. Start backend
Write-Host "Starting backend on http://127.0.0.1:8000 ..."
# The supervisor restarts the backend when an applied fix (or its rollback) needs a restart.
Start-Process -FilePath $pythonExe `
    -ArgumentList "-m", "backend.supervisor", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $root -WindowStyle Normal

# Wait for backend
Start-Sleep -Seconds 3
$attempts = 0
while (-not (Test-PortOpen 8000) -and $attempts -lt 15) {
    Start-Sleep -Seconds 1
    $attempts++
}

Start-Process "http://localhost:8000"

Write-Host ""
Write-Host "Hunter Agent is running at http://localhost:8000"
Write-Host "Bookmark this URL in your browser for quick access."
Write-Host ""
