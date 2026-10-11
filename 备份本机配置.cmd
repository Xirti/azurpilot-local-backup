@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -X utf8 "%~dp0local-maintenance\maintain.py" backup
if errorlevel 1 pause
