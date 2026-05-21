<#
.SYNOPSIS
  Build a self-contained Windows mini-cad.exe with PyInstaller and zip it.

.DESCRIPTION
  Uses the repo's .venv (or $env:CAD_APP_PYTHON). Installs PyInstaller if
  missing, runs packaging/mini-cad.spec, and packs dist/mini-cad into
  dist/mini-cad-windows.zip ready to attach to a GitHub Release.

.EXAMPLE
  .\build_exe.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = $env:CAD_APP_PYTHON
if (-not $Python) { $Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe" }
if (-not (Test-Path $Python)) { throw "Python not found. Create .venv or set `$env:CAD_APP_PYTHON." }

Write-Host "Python: $Python"

# Ensure PyInstaller is available.
& $Python -c "import PyInstaller" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller..."
    & $Python -m pip install pyinstaller
}

# Clean previous build artifacts.
Remove-Item -Recurse -Force dist\mini-cad, build\pyi -ErrorAction SilentlyContinue

Write-Host "Building..."
& $Python -m PyInstaller packaging\mini-cad.spec --noconfirm --distpath dist --workpath build\pyi
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$zip = Join-Path $PSScriptRoot "dist\mini-cad-windows.zip"
Remove-Item -Force $zip -ErrorAction SilentlyContinue
Write-Host "Zipping -> $zip"
Compress-Archive -Path dist\mini-cad\* -DestinationPath $zip

Write-Host ""
Write-Host "Done."
Write-Host "  App:  dist\mini-cad\mini-cad.exe"
Write-Host "  Zip:  $zip"
