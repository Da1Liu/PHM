@echo off
REM ============================================================
REM  Start the web backend (dashboard + OPC UA poller + APIs).
REM  ASCII-only launcher. Chinese messages come from the .ps1
REM  (PowerShell handles Unicode; avoids cmd's UTF-8 batch bug).
REM ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-server.ps1"
echo.
echo (backend stopped) press any key to close...
pause >nul
