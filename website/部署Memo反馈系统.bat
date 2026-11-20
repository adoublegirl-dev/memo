@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Deploy Memo Feedback System

echo ==================================================
echo   Memo Feedback System Deployment
echo ==================================================
echo This deploys only:
echo   Website feedback entry and feedback page
echo   Feedback API and admin console
echo   Feedback service requirements
echo   Required systemd and Nginx snippet
echo.
echo Existing feedback database, uploads and .env are preserved.
echo Other server projects are not modified.
echo ==================================================
echo.

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
if not exist "%~dp0deploy_feedback_system.py" (
  echo [ERROR] deploy_feedback_system.py was not found.
  goto :failed
)

python "%~dp0deploy_feedback_system.py"
if errorlevel 1 goto :failed

echo.
echo ==================================================
echo   Deployment completed.
echo   Feedback: https://memo.zhaguzhagu.com/feedback.html
echo   Admin:    https://memo.zhaguzhagu.com/admin/feedback
echo ==================================================
echo.
pause
exit /b 0

:failed
echo.
echo ==================================================
echo   Deployment failed. Review the error above.
echo ==================================================
echo.
pause
exit /b 1
