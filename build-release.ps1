param([string]$Version = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'VERSION') -Raw).Trim())
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Release version must use major.minor.patch.' }
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'VERSION'), $Version + [Environment]::NewLine)
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
    & python -m PyInstaller --noconfirm --onedir --windowed --name 'S Garage' --paths backend --add-data 'ui/dist:ui/dist' --add-data 'tools:tools' --add-data 'backend/assets.py:.' --add-data 'backend/converter_formats.py:.' --add-data 'VERSION:.' desktop.py
    if ($LASTEXITCODE -ne 0) { throw 'Portable application build failed.' }
    & python scripts/package-release.py $Version
    if ($LASTEXITCODE -ne 0) { throw 'Release packaging failed.' }
} finally { Pop-Location }
