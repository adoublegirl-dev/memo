@echo off
echo Stopping Memo services...

REM 杀掉 9120 端口上的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9120.*LISTENING"') do (
    taskkill /f /pid %%a 2>nul
)

REM 清理残留的 python 进程
taskkill /f /im pythonw.exe 2>nul
taskkill /f /im python.exe 2>nul

echo Memo services stopped.
pause
