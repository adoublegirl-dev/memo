@echo off
chcp 65001 >nul
setlocal

set ROOT=%~dp0
cd /d "%ROOT%"

if not exist "package.json" (
  echo ERROR: package.json not found. Please run this file from the Memo project directory.
  pause
  exit /b 1
)

if not exist "node_modules\electron" (
  echo Installing desktop dependencies...
  npm install
  if errorlevel 1 (
    echo ERROR: npm install failed.
    pause
    exit /b 1
  )
)

set MEMO_ROOT=%ROOT%

echo Starting Memo Desktop Companion...
npm run desktop:dev
