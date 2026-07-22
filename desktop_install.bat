@echo off
chcp 65001 >nul
setlocal

set ROOT=%~dp0
cd /d "%ROOT%"

echo Memo Desktop Companion - Install Helper
echo.

if not exist "package.json" (
  echo ERROR: package.json not found. Please run this file from the Memo project directory.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm is not available. Please install Node.js first.
  pause
  exit /b 1
)

echo Installing desktop dependencies...
npm install
if errorlevel 1 (
  echo ERROR: npm install failed.
  pause
  exit /b 1
)

echo.
echo Desktop companion is ready.
echo.
echo Start now:
echo   desktop.bat
echo.
echo Build unpacked desktop app:
echo   npm run desktop:pack
echo.
echo Build Windows installer / portable exe:
echo   npm run desktop:dist
echo.
echo Note: Startup at login is controlled inside the desktop companion window and must be enabled by the user.
echo.
pause
