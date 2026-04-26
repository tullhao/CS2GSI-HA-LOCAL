@echo off
setlocal

echo Stopping hidden local bridge...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'pc_local_bridge\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

timeout /t 2 /nobreak >nul

echo Starting hidden local bridge...
start "" wscript.exe "%~dp0start_cs2_led_everything_hidden.vbs"

exit /b 0
