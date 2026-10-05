$ErrorActionPreference = 'Stop'
$toolDirectory = Join-Path $PSScriptRoot 'tools'
New-Item -ItemType Directory -Force -Path $toolDirectory | Out-Null
$toolDownloads = @(
    @{ Name = 'converter_pix.exe'; Url = 'https://raw.githubusercontent.com/Senior-S/ConverterPIX-SGarage/cfdbd60d5654881bb8eb7997fe228e53dc1acbe7/bin/win_x64/converter_pix.exe'; Hash = '0D1B45A49B210402B0DCB3F884C69E609EDCB946377BBC8DB576ABA8D9772C39' },
    @{ Name = 'SII_Decrypt.exe'; Url = 'https://github.com/liam-dong/SII-Decrypt-cpp/releases/download/v1.0.0/SII_Decrypt-v1.0.0-win32.zip'; Hash = '816F2DBB511785DE9BDCCE086D934C6D1AE68AF144014AC3078034B168617B12'; ArchiveHash = 'E9A845E4BD989A77F1E88ECCE03D5B2EFF9483E21641E9A6CE2B695232E1BBD9'; Member = 'SII_Decrypt.exe'; PreviousHashes = @('3AD9389B328AC47BD2D069068A94ABDB816ADAE26A777C33B627554882FEA45F') }
)
foreach ($tool in $toolDownloads) {
    $target = Join-Path $toolDirectory $tool.Name
    if (Test-Path -LiteralPath $target) {
        $installedHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        if ($installedHash -eq $tool.Hash) { continue }
        if ($installedHash -notin $tool.PreviousHashes) {
            throw ('Existing tool checksum did not match: ' + $tool.Name + '. Move it aside before downloading the pinned version.')
        }
    }
    $download = $target + '.download'
    Invoke-WebRequest -Uri $tool.Url -OutFile $download -UseBasicParsing
    $downloadHash = if ($tool.ArchiveHash) { $tool.ArchiveHash } else { $tool.Hash }
    if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ne $downloadHash) {
        Remove-Item -LiteralPath $download
        throw ('Downloaded tool checksum did not match: ' + $tool.Name)
    }
    if ($tool.Member) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [System.IO.Compression.ZipFile]::OpenRead($download)
        $extracted = $target + '.extracted'
        try {
            $member = $archive.GetEntry($tool.Member)
            if (-not $member) { throw ('Tool archive is missing ' + $tool.Member) }
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($member, $extracted, $true)
        } finally { $archive.Dispose() }
        Remove-Item -LiteralPath $download
        if ((Get-FileHash -LiteralPath $extracted -Algorithm SHA256).Hash -ne $tool.Hash) {
            Remove-Item -LiteralPath $extracted
            throw ('Extracted tool checksum did not match: ' + $tool.Name)
        }
        $download = $extracted
    }
    Move-Item -LiteralPath $download -Destination $target -Force
}
