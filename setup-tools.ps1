$ErrorActionPreference = 'Stop'
$toolDirectory = Join-Path $PSScriptRoot 'tools'
New-Item -ItemType Directory -Force -Path $toolDirectory | Out-Null
$toolDownloads = @(
    @{ Name = 'converter_pix.exe'; Url = 'https://raw.githubusercontent.com/Senior-S/ConverterPIX-SGarage/cfdbd60d5654881bb8eb7997fe228e53dc1acbe7/bin/win_x64/converter_pix.exe'; Hash = '0D1B45A49B210402B0DCB3F884C69E609EDCB946377BBC8DB576ABA8D9772C39' },
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
