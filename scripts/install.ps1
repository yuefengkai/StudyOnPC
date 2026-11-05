# Install StudyOnPC (Startup shortcut + optional Scheduled Task)
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$cfgPath = Join-Path $root 'config.json'
$cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
$taskName = if ($cfg.task_name) { $cfg.task_name } else { 'StudyOnPC' }

New-Item -ItemType Directory -Path (Join-Path $root 'logs') -Force | Out-Null
$stop = Join-Path $root 'logs\stop.flag'
if (Test-Path $stop) { Remove-Item $stop -Force }

$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $pythonw) { $pythonw = 'pythonw.exe' }
$arg = "`"$root\studyonpc.py`" --role=watchdog"

$registered = $false
try {
  $action = New-ScheduledTaskAction -Execute $pythonw -Argument $arg -WorkingDirectory $root
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
  $registered = $true
  Write-Host "OK Scheduled Task: $taskName"
} catch {
  Write-Host "Scheduled Task failed: $($_.Exception.Message)"
  $registered = $false
}

if (-not $registered) {
  $tr = "`"$pythonw`" $arg"
  schtasks /Create /TN $taskName /TR $tr /SC ONLOGON /RL LIMITED /F 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) {
    $registered = $true
    Write-Host "OK schtasks: $taskName"
  }
}

$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup 'StudyOnPC.lnk'
$w = New-Object -ComObject WScript.Shell
$lnk = $w.CreateShortcut($lnkPath)
$lnk.TargetPath = $pythonw
$lnk.Arguments = $arg
$lnk.WorkingDirectory = $root
$lnk.WindowStyle = 7
$lnk.Description = 'StudyOnPC watchdog'
$lnk.Save()
Write-Host "OK Startup shortcut: $lnkPath"
if (-not $registered) { Write-Host "Note: using Startup shortcut (task not registered)" }

# remove legacy youtube quiz shortcuts if desired? leave them — don't touch other apps.

Start-Process -FilePath $pythonw -ArgumentList $arg -WorkingDirectory $root -WindowStyle Hidden
Start-Sleep -Seconds 2
Write-Host "Started hidden."
Write-Host "Default parent PIN: $($cfg.parent_pin)  -- change config.json soon"
Write-Host "Admin: http://127.0.0.1:$($cfg.admin_port)/"
Write-Host "Quit: Ctrl+Shift+Q or scripts\parent_quit.ps1 ; Uninstall: scripts\uninstall.ps1"
