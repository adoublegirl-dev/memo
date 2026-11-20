@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Memo Website and Installer Update

set "DEPLOY_SCRIPT=%~dp0deploy_memo_site.py"
set "FULL_EXE=%~dp0..\..\Memo_Installer\build\Memo-Setup-latest.exe"
set "LITE_EXE=%~dp0..\..\Memo_Installer\build-lite\Memo-Lite-Setup-latest.exe"
set "UPDATE_MANIFEST=%~dp0downloads\latest.json"

echo ==================================================
echo   Memo Full Website Deployment
echo ==================================================
echo This updates only:
echo   index.html
echo   mobile.html
echo   boot-visual.html
echo   assets/memo-bg.png
echo   downloads/Memo-Setup-latest.exe
echo   downloads/Memo-Lite-Setup-latest.exe
echo   downloads/latest.json
echo.
echo Other server projects and Nginx config are not changed.
echo Existing online files will be backed up first.
echo ==================================================
echo.

echo [1/4] Checking local website files...
for %%F in ("%~dp0index-glass.html" "%~dp0mobile.html" "%~dp0boot-visual.html" "%~dp0assets\memo-bg.png") do (
  if not exist "%%~F" (
    echo [ERROR] Missing file: %%~F
    goto :failed
  )
)

echo [2/4] Checking installer files...
if not exist "%FULL_EXE%" (
  echo [ERROR] Missing Full installer: "%FULL_EXE%"
  goto :failed
)
if not exist "%LITE_EXE%" (
  echo [ERROR] Missing Lite installer: "%LITE_EXE%"
  goto :failed
)
if not exist "%DEPLOY_SCRIPT%" (
  echo [ERROR] Missing deploy script: "%DEPLOY_SCRIPT%"
  goto :failed
)
if not exist "%UPDATE_MANIFEST%" (
  echo [ERROR] Missing update manifest: "%UPDATE_MANIFEST%"
  goto :failed
)

echo [3/4] Checking Python and Paramiko...
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

echo [4/4] Backing up and uploading Memo website...
python "%DEPLOY_SCRIPT%"
if errorlevel 1 goto :failed

echo.
echo ==================================================
echo   Deployment completed successfully.
echo   Website and both installers were updated.
echo ==================================================
echo.
pause
exit /b 0

:failed
echo.
echo ==================================================
echo   Deployment failed.
echo   Review the error message above.
echo ==================================================
echo.
pause
exit /b 1
