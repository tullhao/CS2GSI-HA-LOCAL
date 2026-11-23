# Holt die eingebauten Bausteine für den Build (läuft auf GitHub Actions oder lokal unter Windows).
#   bundle/openrgb  -> OpenRGB-Kern (GPL-2.0, unverändert) + Visual-C++-Laufzeit
#   bundle/pawnio   -> PawnIO_setup.exe (signierter Treiber für RGB-Arbeitsspeicher)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root     = Split-Path -Parent $PSScriptRoot
$bundle   = Join-Path $root "bundle"
$openrgb  = Join-Path $bundle "openrgb"
$openrgbDev = Join-Path $bundle "openrgb_dev"
$pawnio   = Join-Path $bundle "pawnio"
$tmp      = Join-Path $env:RUNNER_TEMP "cs2local-fetch"
if (-not $env:RUNNER_TEMP) { $tmp = Join-Path $env:TEMP "cs2local-fetch" }

$OpenRGBUrl = if ($env:OPENRGB_URL) { $env:OPENRGB_URL } else {
    "https://codeberg.org/OpenRGB/OpenRGB/releases/download/release_1.1/OpenRGB_1.1_Windows_64_8e16de2.zip" }
$OpenRGBDevUrl = if ($env:OPENRGB_DEV_URL) { $env:OPENRGB_DEV_URL } else {
    "https://gitlab.com/CalcProgrammer1/OpenRGB/-/jobs/artifacts/master/download?job=Windows%2064" }
$PawnIOUrl  = if ($env:PAWNIO_URL) { $env:PAWNIO_URL } else {
    "https://github.com/namazso/PawnIO.Setup/releases/latest/download/PawnIO_setup.exe" }

Remove-Item -Recurse -Force $bundle, $tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $openrgb, $pawnio, $tmp | Out-Null

# ---------------------------------------------------------------- OpenRGB
Write-Host "Lade OpenRGB: $OpenRGBUrl"
$zip = Join-Path $tmp "openrgb.zip"
Invoke-WebRequest -Uri $OpenRGBUrl -OutFile $zip -UseBasicParsing
Write-Host ("SHA256 OpenRGB: " + (Get-FileHash $zip -Algorithm SHA256).Hash)
$extract = Join-Path $tmp "openrgb"
Expand-Archive -Path $zip -DestinationPath $extract -Force
$exe = Get-ChildItem -Path $extract -Recurse -Filter "OpenRGB.exe" | Select-Object -First 1
if (-not $exe) { throw "OpenRGB.exe nicht im ZIP gefunden" }
Copy-Item -Path (Join-Path $exe.DirectoryName "*") -Destination $openrgb -Recurse -Force
Write-Host "OpenRGB-Dateien: $((Get-ChildItem $openrgb -Recurse -File).Count)"

# Visual-C++-Laufzeit app-lokal dazulegen, damit OpenRGB auch auf frischen PCs startet
$crt = Get-ChildItem "C:\Program Files\Microsoft Visual Studio\*\*\VC\Redist\MSVC\*\x64\Microsoft.VC14*.CRT" -Directory -ErrorAction SilentlyContinue |
       Sort-Object FullName -Descending | Select-Object -First 1
if ($crt) {
    Write-Host "VC-Laufzeit aus $($crt.FullName)"
    Copy-Item -Path (Join-Path $crt.FullName "*.dll") -Destination $openrgb -Force
} else {
    Write-Host "VC-Redist-Ordner nicht gefunden, nehme System32-Kopien"
    foreach ($dll in "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140_1.dll", "msvcp140_2.dll") {
        $src = Join-Path $env:WINDIR "System32\$dll"
        if (Test-Path $src) { Copy-Item $src $openrgb -Force }
    }
}

# ---------------------------------------------------------------- OpenRGB Entwicklungsversion (neueste Geräte-Fixes)
try {
    Write-Host "Lade OpenRGB-Entwicklungsversion: $OpenRGBDevUrl"
    $devZip = Join-Path $tmp "openrgb_dev.zip"
    Invoke-WebRequest -Uri $OpenRGBDevUrl -OutFile $devZip -UseBasicParsing
    Write-Host ("SHA256 OpenRGB dev: " + (Get-FileHash $devZip -Algorithm SHA256).Hash)
    $devExtract = Join-Path $tmp "openrgb_dev"
    Expand-Archive -Path $devZip -DestinationPath $devExtract -Force
    # Das Pipeline-Artefakt kann ein ZIP im ZIP sein
    Get-ChildItem -Path $devExtract -Recurse -Filter "*.zip" | ForEach-Object {
        Expand-Archive -Path $_.FullName -DestinationPath (Join-Path $devExtract "inner") -Force }
    $devExe = Get-ChildItem -Path $devExtract -Recurse -Filter "OpenRGB.exe" | Select-Object -First 1
    if (-not $devExe) { throw "OpenRGB.exe nicht im Entwicklungs-Paket" }
    New-Item -ItemType Directory -Force $openrgbDev | Out-Null
    Copy-Item -Path (Join-Path $devExe.DirectoryName "*") -Destination $openrgbDev -Recurse -Force
    Get-ChildItem -Path $openrgb -Filter "*.dll" | Where-Object { $_.Name -match "^(msvcp|vcruntime|concrt)" } |
        Copy-Item -Destination $openrgbDev -Force
    $ver = (Get-Item (Join-Path $openrgbDev "OpenRGB.exe")).VersionInfo.FileVersion
    Write-Host "OpenRGB-Entwicklungsversion: $ver, Dateien: $((Get-ChildItem $openrgbDev -Recurse -File).Count)"
} catch {
    Write-Host "WARNUNG: Entwicklungsversion nicht verfügbar ($_). Build läuft nur mit 1.1 weiter."
    Remove-Item -Recurse -Force $openrgbDev -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- PawnIO
Write-Host "Lade PawnIO-Setup: $PawnIOUrl"
$setup = Join-Path $pawnio "PawnIO_setup.exe"
Invoke-WebRequest -Uri $PawnIOUrl -OutFile $setup -UseBasicParsing
Write-Host ("SHA256 PawnIO: " + (Get-FileHash $setup -Algorithm SHA256).Hash)
$sig = Get-AuthenticodeSignature $setup
Write-Host "PawnIO-Signatur: $($sig.Status) / $($sig.SignerCertificate.Subject)"
if ($sig.Status -ne "Valid") { throw "PawnIO-Setup ist nicht gültig signiert ($($sig.Status))" }

# ---------------------------------------------------------------- Lizenzen
$licenses = Join-Path $bundle "licenses"
New-Item -ItemType Directory -Force $licenses | Out-Null
Get-ChildItem -Path $openrgb -Filter "LICENSE*" -File | Copy-Item -Destination (Join-Path $licenses "OpenRGB-LICENSE.txt")
Set-Content -Path (Join-Path $licenses "SOURCES.txt") -Encoding UTF8 -Value @"
Eingebaute Bausteine (unverändert):
- OpenRGB 1.1, GPL-2.0. Quellcode: https://codeberg.org/OpenRGB/OpenRGB  Download: $OpenRGBUrl
- OpenRGB Entwicklungsversion (master), GPL-2.0. Quellcode: https://gitlab.com/CalcProgrammer1/OpenRGB  Download: $OpenRGBDevUrl
- PawnIO Setup (namazso). Quellcode: https://github.com/namazso/PawnIO  Download: $PawnIOUrl
- Microsoft Visual C++ Laufzeit (redistributable)
"@
Write-Host "Bundle fertig."
