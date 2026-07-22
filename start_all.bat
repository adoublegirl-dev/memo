@echo off
chcp 65001 >nul
setlocal

set ROOT=%~dp0
set PID_DIR=%ROOT%data\pids
set LOG_DIR=%ROOT%data\logs
if not exist "%PID_DIR%" mkdir "%PID_DIR%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Prefer explicit PYTHON_EXE if user configured it; otherwise use bundled project .venv; finally use python command.
REM This avoids starting services with a different Python from the one used by install.bat.
if "%PYTHON_EXE%"=="" (
  if exist "%ROOT%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"
  ) else (
    set "PYTHON_EXE=python"
  )
)
"%PYTHON_EXE%" -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python is not usable. Set PYTHON_EXE to a real python.exe or enable Python App Execution Alias.
  pause
  exit /b 1
)

echo Memo - Starting...
echo Python: %PYTHON_EXE%
echo Boot Page: http://localhost:9120
echo Dashboard backend: http://localhost:9121

set PYTHONIOENCODING=utf-8
set PYTHONLEGACYWINDOWSSTDIO=utf-8
set PYTHONWARNINGS=ignore
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set MEMO_BOOT_PORT=9120
set MEMO_DASHBOARD_PORT=9121
set MEMO_DASHBOARD_TARGET_PORT=9121

REM 首先启动轻量启动页，占用 9120，避免浏览器在服务预热时显示拒绝访问。
powershell -NoProfile -ExecutionPolicy Bypass -Command "$script=Join-Path $env:ROOT 'scripts\boot_server.py'; $out=Join-Path $env:LOG_DIR 'boot.out.log'; $err=Join-Path $env:LOG_DIR 'boot.err.log'; $pidFile=Join-Path $env:PID_DIR 'boot.pid'; $args='-u \"' + $script + '\"'; $p=Start-Process -FilePath $env:PYTHON_EXE -ArgumentList $args -WorkingDirectory $env:ROOT -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden; Set-Content -Encoding ascii $pidFile $p.Id"

REM 立刻打开启动页。真正 Dashboard 在 9121 预热，ready 后由 boot server 代理到 9120。
powershell -NoProfile -Command "Start-Sleep -Milliseconds 700; Start-Process 'http://localhost:9120'"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:MEMO_DASHBOARD_PORT='9121'; $script=Join-Path $env:ROOT 'scripts\memo_dashboard.py'; $out=Join-Path $env:LOG_DIR 'dashboard.out.log'; $err=Join-Path $env:LOG_DIR 'dashboard.err.log'; $pidFile=Join-Path $env:PID_DIR 'dashboard.pid'; $args='-u \"' + $script + '\"'; $p=Start-Process -FilePath $env:PYTHON_EXE -ArgumentList $args -WorkingDirectory $env:ROOT -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden; Set-Content -Encoding ascii $pidFile $p.Id"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$script=Join-Path $env:ROOT 'scripts\memo_watcher.py'; $out=Join-Path $env:LOG_DIR 'watcher.out.log'; $err=Join-Path $env:LOG_DIR 'watcher.err.log'; $pidFile=Join-Path $env:PID_DIR 'watcher.pid'; $args='-u \"' + $script + '\"'; $p=Start-Process -FilePath $env:PYTHON_EXE -ArgumentList $args -WorkingDirectory $env:ROOT -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden; Set-Content -Encoding ascii $pidFile $p.Id"

echo Memo services starting. PID files: %PID_DIR%
echo Boot page will enter dashboard automatically when services are ready.
exit /b 0
