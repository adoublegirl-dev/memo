@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Publish Memo 0.10.8-alpha.4 Signed Release

set "WORKSPACE=%~dp0..\.."
set "INSTALLER=%WORKSPACE%\Memo_Installer"
set "PRIVATE_SIGNER=%WORKSPACE%\.private\memo-release-signing\sign-manifest.cjs"
set "VERIFY_MODULE=%INSTALLER%\desktop\update-signature.cjs"
set "DRAFT=%INSTALLER%\artifacts\latest.alpha4.draft.DO_NOT_PUBLISH.json"
set "SIGNED=%~dp0downloads\latest.json"
set "DEPLOY=%~dp0deploy_memo_site.py"
set "ONLINE_VERIFY=%~dp0verify_online_release.py"

echo ==================================================
echo   Memo 0.10.8-alpha.4 Signed Release Publisher
echo   Launcher: 0.10.8-alpha.4
echo   Service : 0.10.8-alpha.4
echo   Order   : sign - validate - backup - upload - activate - verify
echo ==================================================
echo.

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] node.exe was not found in PATH.
  goto :failed
)
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
for %%F in ("%PRIVATE_SIGNER%" "%VERIFY_MODULE%" "%DRAFT%" "%DEPLOY%" "%ONLINE_VERIFY%") do (
  if not exist "%%~F" (
    echo [ERROR] Required release file is missing:
    echo %%~F
    goto :failed
  )
)

echo [1/5] Signing latest.json with the repository-external Ed25519 key...
node "%PRIVATE_SIGNER%" "%VERIFY_MODULE%" "%DRAFT%" "%SIGNED%"
if errorlevel 1 goto :failed

echo.
echo [2/5] Validating signature, versions, URLs, sizes and SHA256...
python "%DEPLOY%" --validate-only
if errorlevel 1 goto :failed

echo.
echo [3/5] Final confirmation.
echo The server script will only update Memo release files under:
echo   /root/MEMO/guanwang/downloads
echo   /var/www/memo/downloads
echo Existing release files are backed up before upload.
echo latest.json is activated only after every referenced asset passes SHA256.
set /p "CONFIRM=Type PUBLISH 0.10.8-alpha.4 to continue: "
if /I not "%CONFIRM%"=="PUBLISH 0.10.8-alpha.4" (
  echo Publish cancelled. Signed local manifest was kept; no server connection was opened.
  pause
  exit /b 2
)

echo.
echo [4/5] Uploading immutable assets and atomically activating signed latest.json...
python "%DEPLOY%" --exe-only
if errorlevel 1 goto :failed

echo.
echo [5/5] Verifying public manifest and every referenced download...
python "%ONLINE_VERIFY%"
if errorlevel 1 goto :failed

echo.
echo ==================================================
echo   PUBLISH SUCCEEDED
echo   Memo 0.10.8-alpha.4 is online.
echo ==================================================
pause
exit /b 0

:failed
echo.
echo ==================================================
echo   PUBLISH FAILED
echo   Review the error above. Do not manually replace latest.json.
echo   Existing remote files were backed up before any activation attempt.
echo ==================================================
pause
exit /b 1
