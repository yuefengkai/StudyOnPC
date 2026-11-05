# Install StudyOnPC from project / dist root (prefers StudyOnPC.exe)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfgPath = Join-Path $root 'config.json'
if (-not (Test-Path $cfgPath)) {
  Write-Host "Missing config.json in $root"
  exit 1
}
$cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
$taskName = if ($cfg.task_name) { $cfg.task_name } else { 'StudyOnPC' }

New-Item -ItemType Directory -Path (Join-Path $root 'logs') -Force | Out-Null
$stop = Join-Path $root 'logs\stop.flag'
if (Test-Path $stop) { Remove-Item $stop -Force }

$exePath = Join-Path $root 'StudyOnPC.exe'
$useExe = Test-Path $exePath
if ($useExe) {
  $launchExe = $exePath
  $arg = '--role=watchdog'
  Write-Host "Using EXE: $exePath"
} else {
  $pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
  if (-not $pythonw) { $pythonw = 'pythonw.exe' }
  $launchExe = $pythonw
  $arg = "`"$root\studyonpc.py`" --role=watchdog"
  Write-Host "Using Python: $launchExe"
}

$registered = $false
try {
  $action = New-ScheduledTaskAction -Execute $launchExe -Argument $arg -WorkingDirectory $root
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
  $registered = $true
  Write-Host "OK Scheduled Task: $taskName"
} catch {
  Write-Host "Scheduled Task failed: $($_.Exception.Message)"
}

if (-not $registered) {
  if ($useExe) {
    $tr = "`"$launchExe`" $arg"
  } else {
    $tr = "`"$launchExe`" $arg"
  }
  schtasks /Create /TN $taskName /TR $tr /SC ONLOGON /RL LIMITED /F 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) { $registered = $true; Write-Host "OK schtasks: $taskName" }
}

$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup 'StudyOnPC.lnk'
$w = New-Object -ComObject WScript.Shell
$lnk = $w.CreateShortcut($lnkPath)
$lnk.TargetPath = $launchExe
$lnk.Arguments = $arg
$lnk.WorkingDirectory = $root
$lnk.WindowStyle = 7
$lnk.Description = 'StudyOnPC watchdog'
$lnk.Save()
Write-Host "OK Startup shortcut: $lnkPath"

Start-Process -FilePath $launchExe -ArgumentList $arg -WorkingDirectory $root -WindowStyle Hidden
Start-Sleep -Seconds 2
Write-Host "Started. PIN=$($cfg.parent_pin)  Admin=http://127.0.0.1:$($cfg.admin_port)/"
Write-Host "Quit: Ctrl+Shift+Q or .\parent_quit.ps1 ; Uninstall: .\uninstall.ps1"
