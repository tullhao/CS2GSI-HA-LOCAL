\
$startupFolder = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder 'CS2 Local Bridge Hidden.lnk'

if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
    Write-Host "Autostart shortcut removed:"
    Write-Host $shortcutPath
} else {
    Write-Host "No autostart shortcut found."
}
