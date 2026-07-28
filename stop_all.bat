@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo Stopping Memo services...
"%PYTHON_EXE%" "%ROOT%scripts\service_control.py" --stop
if errorlevel 1 (
  echo ERROR: Memo services could not be stopped completely. Check data\logs and ports 9120/9121.
  exit /b 1
)
echo Memo services stopped.
exit /b 0
