# Baut CS2LocalClaude.exe (eine Datei, Adminabfrage per Doppelklick, alle Bausteine eingebaut).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "bundle\openrgb\OpenRGB.exe") -or -not (Test-Path "bundle\pawnio\PawnIO_setup.exe")) {
    & (Join-Path $PSScriptRoot "fetch_bundle.ps1")
}

$extra = @()
if (Test-Path "bundle\openrgb_dev\OpenRGB.exe") { $extra = @("--add-data", "bundle\openrgb_dev;openrgb_dev") }

python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin `
    --name CS2LocalClaude `
    --paths src `
    --add-data "bundle\openrgb;openrgb" `
    --add-data "bundle\pawnio;pawnio" `
    --add-data "bundle\licenses;licenses" `
    @extra `
    run.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fehlgeschlagen" }

$exe = Join-Path $root "dist\CS2LocalClaude.exe"
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash
Set-Content -Path (Join-Path $root "dist\CS2LocalClaude.exe.sha256") -Value "$hash  CS2LocalClaude.exe"
Write-Host ("Fertig: $exe ({0:N0} MB)" -f ((Get-Item $exe).Length / 1MB))
Write-Host "SHA256: $hash"
