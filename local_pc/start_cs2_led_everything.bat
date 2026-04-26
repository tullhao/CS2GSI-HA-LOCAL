@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "OPENRGB_EXE="

if exist "C:\Program Files\OpenRGB\OpenRGB.exe" set "OPENRGB_EXE=C:\Program Files\OpenRGB\OpenRGB.exe"
if not defined OPENRGB_EXE if exist "C:\Program Files (x86)\OpenRGB\OpenRGB.exe" set "OPENRGB_EXE=C:\Program Files (x86)\OpenRGB\OpenRGB.exe"
if not defined OPENRGB_EXE if exist "%LocalAppData%\Programs\OpenRGB\OpenRGB.exe" set "OPENRGB_EXE=%LocalAppData%\Programs\OpenRGB\OpenRGB.exe"

if not defined OPENRGB_EXE (
    echo OpenRGB.exe not found in common paths.
    echo Edit this BAT and set OPENRGB_EXE manually if needed.
    pause
    exit /b 1
)

start "" "%OPENRGB_EXE%" --startminimized --server
timeout /t 12 /nobreak >nul

cd /d "%SCRIPT_DIR%"
py .\pc_local_bridge.py
pause
