@echo off
taskkill /f /im pythonw.exe 2>nul
taskkill /f /im python.exe /fi "WINDOWTITLE eq Memo*" 2>nul
echo Memo services stopped.
pause
