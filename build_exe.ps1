# Build StudyOnPC onefile with PyInstaller (run from project root on Windows)
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

if (-not (Test-Path (Join-Path $root 'config.json'))) {
  Write-Host "config.json missing; PyInstaller will bundle config.example.json"
}

& $py -m PyInstaller --noconfirm --clean (Join-Path $root 'StudyOnPC.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }

$built = Join-Path $dist 'StudyOnPC.exe'
if (-not (Test-Path $built)) { throw "Missing onefile output: $built" }

$dest = $env:STUDYONPC_DIST
if ([string]::IsNullOrWhiteSpace($dest)) {
  $dest = Join-Path (Split-Path -Parent $root) 'StudyOnPC-dist'
}
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory -Path $dest -Force | Out-Null
Copy-Item $built (Join-Path $dest 'StudyOnPC.exe') -Force

$exe = Join-Path $dest 'StudyOnPC.exe'
$size = (Get-Item $exe).Length
Write-Host "OK built (onefile): $exe ($([math]::Round($size/1MB,2)) MB)"
Write-Host "Dist folder: $dest"
Write-Host "Note: first run seeds config.json / data / logs beside the exe from the bundled payload."
