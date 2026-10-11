@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0initialize-offline-release.ps1"
if errorlevel 1 (
  echo Offline initialization failed. Read the error above.
  pause
  exit /b 1
)
echo Initialization completed. Run the WebUI CMD entry next.
pause
