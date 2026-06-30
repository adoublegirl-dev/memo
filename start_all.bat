@echo off
chcp 65001 >nul
title Memo

echo Memo - Starting...
echo Dashboard: http://localhost:9120

set PYTHONIOENCODING=utf-8
set PYTHONLEGACYWINDOWSSTDIO=utf-8
set PYTHONWARNINGS=ignore
set HF_HUB_DISABLE_SYMLINKS_WARNING=1

start "" /B python "%~dp0scripts\memo_dashboard.py"
start "" /B python "%~dp0scripts\memo_watcher.py"

timeout /t 5 >nul
start http://localhost:9120
