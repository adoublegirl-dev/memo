@echo off
chcp 65001 >nul
setlocal

set ROOT=%~dp0
set PID_DIR=%ROOT%data\pids

echo Stopping Memo services...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pidDir='%PID_DIR%';" ^
  "$names=@('boot','dashboard','watcher');" ^
  "foreach($name in $names){ $file=Join-Path $pidDir ($name+'.pid'); if(Test-Path $file){ $pidText=(Get-Content $file -ErrorAction SilentlyContinue | Select-Object -First 1); if($pidText -match '^\d+$'){ Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue }; Remove-Item $file -Force -ErrorAction SilentlyContinue }};" ^
  "$ports=@(9120,9121); foreach($port in $ports){ $listeners=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue; foreach($c in $listeners){ Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }};" ^
  "Start-Sleep -Seconds 2;" ^
  "$still=@(); foreach($port in $ports){ if(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue){ $still+=$port }}; if($still.Count -gt 0){ Write-Host ('WARNING: Ports still in use: ' + ($still -join ', ')); exit 1 } else { Write-Host 'Memo services stopped.' }"

exit /b %ERRORLEVEL%
