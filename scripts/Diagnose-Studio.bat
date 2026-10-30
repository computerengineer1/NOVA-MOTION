@echo off
rem NOVA MOTION — read-only diagnostic report (add -HashModels to verify SHA-256)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Diagnose-Studio.ps1" %*
pause
