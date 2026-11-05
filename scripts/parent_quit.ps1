# Parent temporary quit (requires PIN). Does not remove Startup/Task — use uninstall.ps1.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$cfg = Get-Content (Join-Path $root 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$pin = Read-Host 'Enter parent PIN to quit StudyOnPC'
if ($pin -ne $cfg.parent_pin) { Write-Host 'Wrong PIN'; exit 1 }
New-Item -ItemType Directory -Path (Join-Path $root 'logs') -Force | Out-Null
Set-Content (Join-Path $root 'logs\stop.flag') (Get-Date).ToString('o') -Encoding UTF8
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -like '*studyonpc.py*') } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host "Stopped $($_.ProcessId)" }
Write-Host 'Stopped. For permanent removal run scripts\uninstall.ps1'
