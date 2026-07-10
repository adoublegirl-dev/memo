@echo off
chcp 65001 >nul
echo Stopping Memo services...

REM 1: Kill by port 9120
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9120.*LISTENING"') do (
    taskkill /f /pid %%a 2>nul
)

REM 2: Kill pythonw/python background processes
taskkill /f /im pythonw.exe 2>nul
taskkill /f /im python.exe /fi "WINDOWTITLE eq Memo*" 2>nul

REM 3: Wait for release
timeout /t 2 >nul

REM 4: Verify port free
netstat -ano | findstr ":9120.*LISTENING" >nul
if errorlevel 1 (
    echo Memo services stopped.
) else (
    echo WARNING: Port 9120 still in use. Check Task Manager.
)
pause
