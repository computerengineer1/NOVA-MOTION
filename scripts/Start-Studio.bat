@echo off
rem NOVA MOTION — start backend (+ managed ComfyUI) and open the UI
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Studio.ps1" %*
if errorlevel 1 pause
