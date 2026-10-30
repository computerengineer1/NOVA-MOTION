@echo off
rem NOVA MOTION — repair dependencies and verify model checksums
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Repair-Studio.ps1" %*
pause
