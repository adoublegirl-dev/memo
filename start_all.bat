@echo off
chcp 65001 >nul
title Memo
set PYTHONIOENCODING=utf-8

echo Memo - 启动中...
echo Dashboard: http://localhost:9120
echo.

start "Memo Dashboard" /MIN python "%~dp0scripts\memo_dashboard.py" >nul 2>&1
start "Memo Watcher" /MIN python "%~dp0scripts\memo_watcher.py" >nul 2>&1

echo 服务已启动（最小化窗口）。
echo 停止：双击 stop_all.bat
echo.

timeout /t 3 >nul
start http://localhost:9120
