# Launches the Hunter brief-to-deck agent: Ollama (if not already running),
# builds the React frontend (if needed), starts the Python/FastAPI backend,
# and opens the browser at http://localhost:8000.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# Refresh PATH from the registry
$machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"

$pythonExe = "C:\Users\sweta.shah\AppData\Local\Python\bin\python3.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source
}
if (-not $pythonExe) {
    Write-Error "Could not find a working Python interpreter. See README.md."
    exit 1
}

$ollamaExe = "C:\Users\sweta.shah\AppData\Local\Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollamaExe)) {
    $ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
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

# 1. Ollama
if (-not (Test-PortOpen 11434)) {
    Write-Host "Starting Ollama server..."
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
} else {
    Write-Host "Ollama already running."
}

# 2. Build frontend if needed
$staticIndex = Join-Path $root "agent\static\index.html"
if (-not (Test-Path $staticIndex)) {
    Write-Host "Building frontend (first time)..."
    Push-Location (Join-Path $root "web")
    & $nodeExe "node_modules\vite\bin\vite.js" build --config vite.config.ts
    Pop-Location
} else {
    Write-Host "Frontend already built."
}

# 3. Start backend
Write-Host "Starting backend on http://127.0.0.1:8000 ..."
Start-Process -FilePath $pythonExe `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory (Join-Path $root "agent") -WindowStyle Normal

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
