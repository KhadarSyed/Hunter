@echo off
setlocal
title Hunter Agent
cd /d "%~dp0"

echo.
echo  ========================================
echo   Hunter Agent  -  Brief to Deck
echo  ========================================
echo.

set "PYTHON=C:\Users\sweta.shah\AppData\Local\Python\bin\python3.exe"
set "OLLAMA=C:\Users\sweta.shah\AppData\Local\Programs\Ollama\ollama.exe"
set "NODE=C:\Program Files\nodejs\node.exe"

:: ------- 1. Ollama -------
echo  [1/3] Checking Ollama...
powershell -NoProfile -Command "try{(New-Object System.Net.Sockets.TcpClient).Connect('127.0.0.1',11434);exit 0}catch{exit 1}" >nul 2>&1
if errorlevel 1 (
    echo        Starting Ollama server...
    start "" /min "%OLLAMA%" serve
    ping -n 4 127.0.0.1 >nul
) else (
    echo        Ollama already running.
)

:: ------- 2. Build frontend (first time only) -------
if not exist "%~dp0agent\static\index.html" (
    echo  [2/3] Building frontend...
    pushd "%~dp0web"
    "%NODE%" node_modules\vite\bin\vite.js build --config vite.config.ts
    if errorlevel 1 (
        echo  ERROR: Frontend build failed.
        pause
        exit /b 1
    )
    popd
) else (
    echo  [2/3] Frontend already built.
)

:: ------- 3. Start backend -------
echo  [3/3] Starting backend...

:: Check if port 8000 is already in use
powershell -NoProfile -Command "try{(New-Object System.Net.Sockets.TcpClient).Connect('127.0.0.1',8000);exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 (
    echo        Backend already running on port 8000.
    goto :open_browser
)

:: Start uvicorn in a new minimised window
pushd "%~dp0agent"
start "Hunter Agent - Backend" /min "%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
popd

echo        Waiting for server to start...
:wait
ping -n 2 127.0.0.1 >nul
powershell -NoProfile -Command "try{(New-Object System.Net.Sockets.TcpClient).Connect('127.0.0.1',8000);exit 0}catch{exit 1}" >nul 2>&1
if errorlevel 1 goto :wait

:open_browser
echo.
echo  ==========================================
echo   Hunter Agent is ready!
echo  ==========================================
echo.
echo   URL:  http://localhost:8000
echo.
echo   Bookmark the URL above in your browser.
echo   Keep this window open while using the agent.
echo.
start "" http://localhost:8000
pause >nul
