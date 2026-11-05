# Uninstall StudyOnPC (requires parent PIN)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$cfg = Get-Content (Join-Path $root 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$pin = Read-Host 'Enter parent PIN to uninstall StudyOnPC'
if ($pin -ne $cfg.parent_pin) {
  Write-Host 'Wrong PIN. Cancelled.'
  exit 1
}

$taskName = if ($cfg.task_name) { $cfg.task_name } else { 'StudyOnPC' }
New-Item -ItemType Directory -Path (Join-Path $root 'logs') -Force | Out-Null
Set-Content (Join-Path $root 'logs\stop.flag') (Get-Date).ToString('o') -Encoding UTF8

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -like '*studyonpc.py*') } |
  ForEach-Object {
    Write-Host "Stop PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
schtasks /Delete /TN $taskName /F 2>$null | Out-Null

$startup = [Environment]::GetFolderPath('Startup')
Get-ChildItem $startup -Filter '*.lnk' -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like '*StudyOnPC*' } |
  ForEach-Object { Remove-Item $_.FullName -Force; Write-Host "Removed $($_.Name)" }

Write-Host 'Uninstalled. Run scripts\install.ps1 to enable again.'
