@echo off
chcp 65001 >nul
echo Stopping Memo services...

REM Aggressively kill ALL processes on port 9120
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9120"') do (
    taskkill /f /pid %%a 2>nul
)

REM Also kill dashboard/watcher python processes
taskkill /f /im pythonw.exe 2>nul
taskkill /f /im python.exe 2>nul

REM Wait for port release
timeout /t 2 >nul

REM Verify
netstat -ano | findstr ":9120.*LISTENING" >nul
if errorlevel 1 (
    echo Memo services stopped. Port 9120 is free.
) else (
    echo WARNING: Port 9120 still in use. Try again or restart computer.
)
pause
