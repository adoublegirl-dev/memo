@echo off
chcp 65001 >nul
echo Stopping Memo services...

REM Kill processes on port 9120
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9120 " ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a 2>nul
)

REM Clean up remaining python processes
taskkill /f /im pythonw.exe 2>nul
taskkill /f /im python.exe 2>nul

echo Memo services stopped.
pause
