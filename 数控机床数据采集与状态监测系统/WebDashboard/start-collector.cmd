@echo off
REM ============================================================
REM  Start the NI vibration collector daemon (resident).
REM  Waits for the web "start" command (collector_control.ni_run).
REM  ASCII-only launcher; Chinese messages come from the .ps1.
REM ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-collector.ps1"
echo.
echo (collector stopped) press any key to close...
pause >nul
