$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $env:LOCALAPPDATA 'ETS2Garage/server.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { exit 0 }
$garageProcessId = [int](Get-Content -LiteralPath $pidFile)
$garageProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $garageProcessId"
if ($garageProcess) {
    $expectedScript = Join-Path $PSScriptRoot 'backend/server.py'
    if (-not $garageProcess.CommandLine.Contains($expectedScript)) {
        throw 'The recorded process ID belongs to another program. The garage did not stop it.'
    }
    Stop-Process -Id $garageProcessId
}
Remove-Item -LiteralPath $pidFile
