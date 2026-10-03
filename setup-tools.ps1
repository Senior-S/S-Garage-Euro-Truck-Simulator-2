$ErrorActionPreference = 'Stop'
$toolDirectory = Join-Path $PSScriptRoot 'tools'
New-Item -ItemType Directory -Force -Path $toolDirectory | Out-Null
$toolDownloads = @(
    @{ Name = 'converter_pix.exe'; Url = 'https://raw.githubusercontent.com/mwl4/ConverterPIX/3cd4e73a86d0c6bd28e117664c50a36cabeccf38/bin/win_x64/converter_pix.exe'; Hash = '60310EE8E01563145B71A8FB62F63D7A8B03906334E84E1463918F615F192ED2' },
    @{ Name = 'SII_Decrypt.exe'; Url = 'https://raw.githubusercontent.com/TheLazyTomcat/SII_Decrypt/683e1d8addc96947967148a29a07e0859736a926/Program_Console/Lazarus/Release/win_x64/SII_Decrypt.exe'; Hash = '3AD9389B328AC47BD2D069068A94ABDB816ADAE26A777C33B627554882FEA45F' }
)
foreach ($tool in $toolDownloads) {
    $target = Join-Path $toolDirectory $tool.Name
    if (Test-Path -LiteralPath $target) {
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $tool.Hash) {
            throw ('Existing tool checksum did not match: ' + $tool.Name + '. Move it aside before downloading the pinned version.')
        }
        continue
    }
    $download = $target + '.download'
    Invoke-WebRequest -Uri $tool.Url -OutFile $download -UseBasicParsing
    if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ne $tool.Hash) {
        Remove-Item -LiteralPath $download
        throw ('Downloaded tool checksum did not match: ' + $tool.Name)
    }
    Move-Item -LiteralPath $download -Destination $target
}
