@echo off
chcp 65001 >nul
setlocal

set ROOT=%~dp0
set PID_DIR=%ROOT%data\pids
if not exist "%PID_DIR%" mkdir "%PID_DIR%"

REM Prefer explicit PYTHON_EXE if user configured it; otherwise use python command.
REM Microsoft Store Python App Execution Alias works when invoked by cmd/PowerShell.
if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"
"%PYTHON_EXE%" -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python is not usable. Set PYTHON_EXE to a real python.exe or enable Python App Execution Alias.
  pause
  exit /b 1
)

echo Memo - Starting...
echo Python: %PYTHON_EXE%
echo Dashboard: http://localhost:9120

set PYTHONIOENCODING=utf-8
set PYTHONLEGACYWINDOWSSTDIO=utf-8
set PYTHONWARNINGS=ignore
set HF_HUB_DISABLE_SYMLINKS_WARNING=1

REM 首次升级建议先手动执行：%PYTHON_EXE% scripts\init_db.py
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath $env:PYTHON_EXE -ArgumentList @('%ROOT%scripts\memo_dashboard.py') -WorkingDirectory '%ROOT%' -PassThru -WindowStyle Hidden; Set-Content -Encoding ascii '%PID_DIR%\dashboard.pid' $p.Id"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath $env:PYTHON_EXE -ArgumentList @('%ROOT%scripts\memo_watcher.py') -WorkingDirectory '%ROOT%' -PassThru -WindowStyle Hidden; Set-Content -Encoding ascii '%PID_DIR%\watcher.pid' $p.Id"

powershell -NoProfile -Command "Start-Sleep -Seconds 5"
echo Memo services started. PID files: %PID_DIR%
echo Open http://localhost:9120 in your browser.
exit /b 0
