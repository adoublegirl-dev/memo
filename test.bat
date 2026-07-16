@echo off
chcp 65001 >nul
setlocal
set MEMO_ENV=test
if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"
"%PYTHON_EXE%" -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python is not usable. Set PYTHON_EXE to a real python.exe or enable Python App Execution Alias.
  exit /b 1
)
"%PYTHON_EXE%" -m pytest %*
