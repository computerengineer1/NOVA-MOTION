@echo off
rem NOVA MOTION — one-time installer (no admin rights needed)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Studio.ps1" %*
if errorlevel 1 pause
