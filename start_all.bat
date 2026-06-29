@echo off
title Memo

echo Memo - Starting in background...
echo Dashboard: http://localhost:9120
echo.

start "" /B pythonw E:\memo\scripts\memo_dashboard.py
start "" /B pythonw E:\memo\scripts\memo_watcher.py

echo Both services started (no windows).
echo To stop: run stop_all.bat or kill pythonw.exe in Task Manager.
echo.

timeout /t 6 >nul
start http://localhost:9120
