@echo off
rem Double-click launcher: runs deploy\start.ps1 (builds the frontend once, starts the backend, opens the browser).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\start.ps1"
pause
