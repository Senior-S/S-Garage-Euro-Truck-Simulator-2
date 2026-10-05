param([string]$Version = '0.3.3')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & python -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
    Push-Location ui
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'UI dependency installation failed.' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'UI build failed.' }
    } finally { Pop-Location }
    & ./setup-tools.ps1
    & python -m PyInstaller --noconfirm --onedir --windowed --name 'S Garage' --paths backend --add-data 'ui/dist:ui/dist' --add-data 'tools:tools' --add-data 'backend/assets.py:.' --add-data 'backend/converter_formats.py:.' desktop.py
    if ($LASTEXITCODE -ne 0) { throw 'Portable application build failed.' }
    & python scripts/package-release.py $Version
    if ($LASTEXITCODE -ne 0) { throw 'Release packaging failed.' }
} finally { Pop-Location }
