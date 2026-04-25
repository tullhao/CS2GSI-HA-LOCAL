\
@echo off
setlocal

echo Stopping hidden local bridge...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'pc_local_bridge\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo Done.
timeout /t 1 /nobreak >nul
