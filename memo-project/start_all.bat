@echo off
title Memo

echo Memo - Starting in background...
echo Dashboard: http://localhost:9120
echo.

start "" /B pythonw "D:\个人\Hanako项目文件\Memo_V0.1.0\memo-project\memo_dashboard.py"
start "" /B pythonw "D:\个人\Hanako项目文件\Memo_V0.1.0\memo-project\memo_watcher.py"

echo Both services started (no windows).
echo To stop: run stop_all.bat or kill pythonw.exe in Task Manager.
echo.

timeout /t 6 >nul
start http://localhost:9120
