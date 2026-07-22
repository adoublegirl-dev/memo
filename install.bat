@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo Memo 一键安装器
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
    echo 请先安装 Python 3.11 或更高版本，然后重新双击 install.bat。
    echo 下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
  )
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\easy_install.py
) else (
  %BASE_PYTHON% scripts\easy_install.py
)

echo.
echo 是否同时安装 Memo Desktop Companion 桌面助手？
echo 它可以作为桌面软件启动 Memo 服务，并提供待办/项目候选提醒。
echo.
choice /C YN /N /M "安装桌面助手？[Y/N] "
if errorlevel 2 goto skip_desktop
if errorlevel 1 call "%~dp0desktop_install.bat"

:skip_desktop
echo.
pause
