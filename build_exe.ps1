# Build StudyOnPC onedir with PyInstaller (run from project root on Windows)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$pyCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $pyCmd) { throw 'python.exe not found on PATH' }
$py = $pyCmd.Source
Write-Host "Using Python: $py"

& $py -m pip install -U pyinstaller pypinyin pillow | Out-Host

$dist = Join-Path $root 'dist'
$build = Join-Path $root 'build'
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
if (Test-Path $build) { Remove-Item $build -Recurse -Force }

& $py -m PyInstaller --noconfirm --clean (Join-Path $root 'StudyOnPC.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }

$out = Join-Path $dist 'StudyOnPC'
# Seed writable copies next to the exe (also seeded at runtime from _internal)
$cfgSrc = Join-Path $root 'config.json'
if (-not (Test-Path $cfgSrc)) {
  $cfgSrc = Join-Path $root 'config.example.json'
  Write-Host "config.json missing; seeding dist from config.example.json"
}
Copy-Item $cfgSrc (Join-Path $out 'config.json') -Force
New-Item -ItemType Directory -Path (Join-Path $out 'data\banks') -Force | Out-Null
Copy-Item (Join-Path $root 'data\banks\*') (Join-Path $out 'data\banks') -Force -Recurse
New-Item -ItemType Directory -Path (Join-Path $out 'assets') -Force | Out-Null
if (Test-Path (Join-Path $root 'assets')) {
  Copy-Item (Join-Path $root 'assets\*') (Join-Path $out 'assets') -Force -Recurse
}
New-Item -ItemType Directory -Path (Join-Path $out 'scripts') -Force | Out-Null
Copy-Item (Join-Path $root 'scripts\set_mute.ps1') (Join-Path $out 'scripts\set_mute.ps1') -Force
Copy-Item (Join-Path $root 'install.ps1') (Join-Path $out 'install.ps1') -Force
Copy-Item (Join-Path $root 'uninstall.ps1') (Join-Path $out 'uninstall.ps1') -Force
Copy-Item (Join-Path $root 'parent_quit.ps1') (Join-Path $out 'parent_quit.ps1') -Force
Copy-Item (Join-Path $root 'start.bat') (Join-Path $out 'start.bat') -Force
Copy-Item (Join-Path $root 'start-console.bat') (Join-Path $out 'start-console.bat') -Force
# VBS helper lives under scripts/
Copy-Item (Join-Path $root 'scripts\run_hidden.vbs') (Join-Path $out 'scripts\run_hidden.vbs') -Force
if (Test-Path (Join-Path $root 'README.md')) {
  Copy-Item (Join-Path $root 'README.md') (Join-Path $out 'README.md') -Force
}
if (Test-Path (Join-Path $root 'config.example.json')) {
  Copy-Item (Join-Path $root 'config.example.json') (Join-Path $out 'config.example.json') -Force
}

$dest = $env:STUDYONPC_DIST
if ([string]::IsNullOrWhiteSpace($dest)) {
  $dest = Join-Path (Split-Path -Parent $root) 'StudyOnPC-dist'
}
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory -Path $dest -Force | Out-Null
Copy-Item (Join-Path $out '*') $dest -Recurse -Force

$exe = Join-Path $dest 'StudyOnPC.exe'
$size = (Get-Item $exe).Length
Write-Host "OK built: $exe ($([math]::Round($size/1MB,2)) MB)"
Write-Host "Dist folder: $dest"
