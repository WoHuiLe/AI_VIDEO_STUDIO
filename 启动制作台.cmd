@echo off
powershell.exe -NoProfile -File "%~dp0environment\start-web.ps1"
if errorlevel 1 pause
