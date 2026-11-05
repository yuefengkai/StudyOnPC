$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfg = Get-Content (Join-Path $root 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$pin = Read-Host 'Enter parent PIN to quit StudyOnPC'
if ($pin -ne $cfg.parent_pin) { Write-Host 'Wrong PIN'; exit 1 }
New-Item -ItemType Directory -Path (Join-Path $root 'logs') -Force | Out-Null
Set-Content (Join-Path $root 'logs\stop.flag') (Get-Date).ToString('o') -Encoding UTF8

# Stop python script runs
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -like '*studyonpc.py*') } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host "Stopped python $($_.ProcessId)" }

# Stop frozen exe runs
Get-CimInstance Win32_Process -Filter "Name='StudyOnPC.exe'" -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host "Stopped exe $($_.ProcessId)" }

Write-Host 'Stopped. For permanent removal run uninstall.ps1'
