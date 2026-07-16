@echo off
chcp 65001 >nul
setlocal

if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"
"%PYTHON_EXE%" -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python is not usable. Set PYTHON_EXE to a real python.exe or enable Python App Execution Alias.
  pause
  exit /b 1
)

echo Memo - Safe Upgrade
echo Python: %PYTHON_EXE%
echo 1. Stop services
call "%~dp0stop_all.bat"
echo.
echo 2. Run database migration in single process
"%PYTHON_EXE%" "%~dp0scripts\init_db.py"
if errorlevel 1 (
  echo Upgrade failed during init_db.
  pause
  exit /b 1
)
echo.
echo 3. Run doctor
"%PYTHON_EXE%" "%~dp0scripts\doctor.py"
echo.
echo Upgrade finished. You can run start_all.bat now.
pause
