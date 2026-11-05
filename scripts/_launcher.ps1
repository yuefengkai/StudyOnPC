# Dot-source helper: sets $LauncherExe / $LauncherArgs / $UseExe
$script:UseExe = $false
$script:LauncherExe = $null
$script:LauncherArgs = $null
$exeCandidate = Join-Path $root 'StudyOnPC.exe'
if (Test-Path $exeCandidate) {
  $script:UseExe = $true
  $script:LauncherExe = $exeCandidate
  $script:LauncherArgs = '--role=watchdog'
} else {
  $pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
  if (-not $pythonw) { $pythonw = 'pythonw.exe' }
  $script:LauncherExe = $pythonw
  $script:LauncherArgs = "`"$root\studyonpc.py`" --role=watchdog"
}
