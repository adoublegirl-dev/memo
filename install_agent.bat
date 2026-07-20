@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\install_agent.py
) else (
  python scripts\install_agent.py
  if errorlevel 1 py -3 scripts\install_agent.py
)

echo.
pause
