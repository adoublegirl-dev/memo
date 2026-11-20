param(
  [ValidateSet('Detect','Kill')]
  [string]$Mode = 'Detect',
  [string]$Flag = ''
)

$ErrorActionPreference = 'SilentlyContinue'
$targets = Get-CimInstance Win32_Process | Where-Object {
  $name = $_.Name
  $cmd = [string]$_.CommandLine
  $path = [string]$_.ExecutablePath
  if ($PID -eq $_.ProcessId) { return $false }
  if ($name -eq 'Memo.exe' -or $name -eq 'Memo Desktop Companion.exe') { return $true }
  if ($name -like 'python*.exe' -and ($cmd -match 'memo_dashboard\.py|memo_watcher\.py|boot_server\.py|run_mcp\.py|Memo\\Programs\\Memo|MEMO_USER_ROOT|memo_source_aware')) { return $true }
  if ($name -eq 'cmd.exe' -and ($cmd -match 'start_all\.bat|stop_all\.bat|memo_dashboard\.py|memo_watcher\.py')) { return $true }
  return $false
}

if ($Mode -eq 'Detect') {
  if ($targets) {
    if ($Flag) { Set-Content -Path $Flag -Value 'running' -Encoding ASCII }
    $targets | ForEach-Object { Write-Output "$($_.ProcessId) $($_.Name) $($_.ExecutablePath)" }
    exit 2
  }
  if ($Flag -and (Test-Path $Flag)) { Remove-Item $Flag -Force }
  exit 0
}

foreach ($proc in $targets) {
  try {
    Stop-Process -Id $proc.ProcessId -Force
    Write-Output "Stopped $($proc.ProcessId) $($proc.Name)"
  } catch {
    Write-Output "Failed $($proc.ProcessId) $($proc.Name): $($_.Exception.Message)"
  }
}
Start-Sleep -Milliseconds 800
exit 0
