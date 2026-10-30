@echo off
rem NOVA MOTION — graceful stop (only our own processes)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Stop-Studio.ps1" %*
pause
