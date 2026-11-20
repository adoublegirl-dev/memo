@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Memo Signed Release Update

set "FULL_EXE=%~dp0..\..\Memo_Installer\build\Memo-Setup-latest.exe"
set "LITE_EXE=%~dp0..\..\Memo_Installer\build-lite\Memo-Lite-Setup-latest.exe"
set "DEPLOY_SCRIPT=%~dp0deploy_memo_site.py"
set "UPDATE_MANIFEST=%~dp0downloads\latest.json"

echo ==================================================
echo   Memo Signed Release Assets Update
echo   Full, Lite, Service Patch and signed latest.json only.
echo   HTML, images and other files will not be changed.
echo ==================================================
echo.

echo [1/3] Checking local files...
if not exist "%FULL_EXE%" (
  echo [ERROR] Full installer not found:
  echo "%FULL_EXE%"
  goto :failed
)
if not exist "%LITE_EXE%" (
  echo [ERROR] Lite installer not found:
  echo "%LITE_EXE%"
  goto :failed
)
if not exist "%DEPLOY_SCRIPT%" (
  echo [ERROR] Deploy script not found:
  echo "%DEPLOY_SCRIPT%"
  goto :failed
)
if not exist "%UPDATE_MANIFEST%" (
  echo [ERROR] Update manifest not found:
  echo "%UPDATE_MANIFEST%"
  goto :failed
)

echo [2/3] Checking Python and Paramiko...
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  goto :failed
)
python -c "import paramiko" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Paramiko is missing. Run: pip install paramiko
  goto :failed
)

echo [3/3] Uploading signed release assets...
python "%DEPLOY_SCRIPT%" --exe-only
if errorlevel 1 goto :failed

echo.
echo ==================================================
echo   Update completed successfully.
echo   Updated: Memo-Setup-latest.exe
echo   Updated: Memo-Lite-Setup-latest.exe
echo   Updated: Service Patch full snapshot and delta chain
echo   Updated: signed latest.json
echo ==================================================
echo.
pause
exit /b 0

:failed
echo.
echo ==================================================
echo   Update failed.
echo   Existing server EXE files were not intentionally deleted.
echo   Review the error message above.
echo ==================================================
echo.
pause
exit /b 1
