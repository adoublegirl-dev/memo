@echo off
echo Stopping Memo services...
taskkill /f /im python.exe 2>nul
taskkill /f /im pythonw.exe 2>nul
echo Memo services stopped.
pause
