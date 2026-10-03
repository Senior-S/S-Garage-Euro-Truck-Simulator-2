$ErrorActionPreference = 'Stop'
$garageRoot = $PSScriptRoot
$garageData = Join-Path $env:LOCALAPPDATA 'ETS2Garage'
$garageUrl = 'http://127.0.0.1:8765'
New-Item -ItemType Directory -Force -Path $garageData | Out-Null

$existingGarage = $null
try {
    $existingGarage = Invoke-RestMethod -Uri "$garageUrl/api/status" -TimeoutSec 2
} catch {
    if ($_.Exception.Response) { throw }
    if ($_.Exception -isnot [System.Net.WebException] -and $_.Exception -isnot [System.OperationCanceledException] -and $_.Exception.GetType().FullName -ne 'System.Net.Http.HttpRequestException') { throw }
}
if ($existingGarage) {
    if ($existingGarage.appId -ne 'ets2-local-garage') {
        throw 'Port 8765 belongs to another application.'
    }
    Start-Process $garageUrl
    exit 0
}

$pythonCommand = Get-Command python -ErrorAction Stop
& $pythonCommand.Source -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer is required"; import PIL'
if ($LASTEXITCODE -ne 0) {
    & $pythonCommand.Source -m pip install -r (Join-Path $garageRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $garageRoot 'ui/dist/index.html'))) {
    Push-Location (Join-Path $garageRoot 'ui')
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'UI dependency installation failed. Install Node.js 20 or newer.' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'UI build failed.' }
    } finally { Pop-Location }
}
& (Join-Path $garageRoot 'setup-tools.ps1')

$serverScript = Join-Path $garageRoot 'backend/server.py'
$serverProcess = Start-Process -FilePath $pythonCommand.Source -ArgumentList @('"' + $serverScript + '"') -WorkingDirectory $garageRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $garageData 'server.log') -RedirectStandardError (Join-Path $garageData 'server-errors.log')
$serverProcess.Id | Set-Content -LiteralPath (Join-Path $garageData 'server.pid')
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 300
    $serverProcess.Refresh()
    if ($serverProcess.HasExited) {
        throw ('Garage failed to start. ' + (Get-Content -LiteralPath (Join-Path $garageData 'server-errors.log') -Raw))
    }
    try {
        $serverStatus = Invoke-RestMethod -Uri "$garageUrl/api/status" -TimeoutSec 2
        if ($serverStatus.appId -eq 'ets2-local-garage') {
            Start-Process $garageUrl
            exit 0
        }
    } catch {
        if ($_.Exception.Response) { throw }
        if ($_.Exception -isnot [System.Net.WebException] -and $_.Exception -isnot [System.OperationCanceledException] -and $_.Exception.GetType().FullName -ne 'System.Net.Http.HttpRequestException') { throw }
    }
}
throw "Garage did not become ready. See $garageData/server-errors.log."
