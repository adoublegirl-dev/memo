@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Publish Memo 0.10.8-alpha.3 Signed Release

echo ==================================================
echo   Memo 0.10.8-alpha.3 Signed Release Publisher
echo   Launcher: 0.10.8-alpha.3
echo   Service : 0.10.8-alpha.2
echo ==================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  goto :failed
)
python -c "import paramiko, cryptography" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Paramiko or cryptography is missing.
  echo Run: pip install paramiko cryptography
  goto :failed
)
if not exist "%~dp0deploy_memo_site.py" (
  echo [ERROR] deploy_memo_site.py is missing.
  goto :failed
)

echo [1/3] Validating Ed25519 signature and all release asset hashes...
python "%~dp0deploy_memo_site.py" --validate-only
if errorlevel 1 goto :failed

echo.
echo [2/3] Final confirmation.
echo This will back up the current remote release, upload versioned Full/Lite/Service Patch,
echo activate signed latest.json after all referenced assets, then refresh website aliases.
set /p "CONFIRM=Type PUBLISH 0.10.8-alpha.3 to continue: "
if /I not "%CONFIRM%"=="PUBLISH 0.10.8-alpha.3" (
  echo Publish cancelled. No server connection was opened.
  pause
  exit /b 2
)

echo.
echo [3/3] Publishing signed release assets...
python "%~dp0deploy_memo_site.py" --exe-only
if errorlevel 1 goto :failed

echo.
echo ==================================================
echo   PUBLISH SUCCEEDED
echo   Signed latest.json was activated after all referenced assets.
echo ==================================================
pause
exit /b 0

:failed
echo.
echo ==================================================
echo   PUBLISH FAILED
echo   Review the error above. Existing server files were not intentionally deleted.
echo ==================================================
pause
exit /b 1
