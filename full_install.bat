@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo Memo 全量安装器 / 升级器
echo ============================================================
echo.

where python >nul 2>nul
if %errorlevel% equ 0 (
  set "BASE_PYTHON=python"
) else (
  where py >nul 2>nul
  if %errorlevel% equ 0 (
    set "BASE_PYTHON=py -3"
  ) else (
    echo 未找到 Python。
    echo 请先安装 Python 3.11 或更高版本，然后重新双击 full_install.bat。
    pause
    exit /b 1
  )
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\full_install.py
) else (
  %BASE_PYTHON% scripts\full_install.py
)

echo.
pause
