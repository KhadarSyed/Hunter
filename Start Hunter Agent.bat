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
set "NODE=C:\Program Files\nodejs\node.exe"

:: ------- 1. Build frontend (first time only) -------
if not exist "%~dp0agent\static\index.html" (
    echo  [1/2] Building frontend...
    pushd "%~dp0web"
    "%NODE%" node_modules\vite\bin\vite.js build --config vite.config.ts
    if errorlevel 1 (
        echo  ERROR: Frontend build failed.
        pause
        exit /b 1
    )
    popd
) else (
    echo  [1/2] Frontend already built.
)

:: ------- 2. Start backend -------
echo  [2/2] Starting backend...

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
