\
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbsPath = Join-Path $scriptDir 'start_cs2_led_everything_hidden.vbs'
$startupFolder = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder 'CS2 Local Bridge Hidden.lnk'

if (-not (Test-Path $vbsPath)) {
    Write-Error "VBS file not found: $vbsPath"
    exit 1
}

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $vbsPath
$shortcut.WorkingDirectory = $scriptDir
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,3"
$shortcut.Save()

Write-Host "Autostart shortcut created:"
Write-Host $shortcutPath
