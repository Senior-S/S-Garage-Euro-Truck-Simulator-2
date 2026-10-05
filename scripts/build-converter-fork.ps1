param(
    [string]$ConverterSource = (Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'ConverterPIX-SGarage'),
    [string]$MSBuildPath,
    [string]$PlatformToolset = 'v145'
)
$ErrorActionPreference = 'Stop'
$solution = Join-Path $ConverterSource 'src\ConverterPIX.sln'
if (-not (Test-Path -LiteralPath $solution)) {
    throw "ConverterPIX fork source not found at $ConverterSource. Clone https://github.com/Senior-S/ConverterPIX-SGarage beside the garage checkout or pass -ConverterSource."
}
if (-not $MSBuildPath) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) {
        throw 'Visual Studio Installer was not found. Pass -MSBuildPath to MSBuild.exe.'
    }
    $MSBuildPath = & $vswhere -latest -products '*' -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
}
if (-not $MSBuildPath -or -not (Test-Path -LiteralPath $MSBuildPath)) {
    throw 'MSBuild.exe was not found. Install the Visual Studio C++ build tools or pass -MSBuildPath.'
}
& $MSBuildPath $solution /m /p:Configuration=Release /p:Platform=x64 "/p:PlatformToolset=$PlatformToolset" /p:WindowsTargetPlatformVersion=10.0 /verbosity:quiet /nologo
if ($LASTEXITCODE -ne 0) { throw 'ConverterPIX fork build failed.' }
$executable = Join-Path $ConverterSource 'bin\win_x64\converter_pix.exe'
$capabilities = & $executable --garage-capabilities
if ($LASTEXITCODE -ne 0 -or -not (($capabilities | ConvertFrom-Json).garageFormatVersion -eq 1)) {
    throw 'The built converter does not support the garage formats.'
}
$env:ETS_GARAGE_CONVERTER = (Resolve-Path -LiteralPath $executable).Path
Write-Output "Garage converter for this terminal: $env:ETS_GARAGE_CONVERTER"
Write-Output 'Run .\launch.ps1 from this terminal, or choose this executable in Garage Settings.'
