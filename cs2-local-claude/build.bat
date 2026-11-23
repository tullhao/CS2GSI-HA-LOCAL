@echo off
setlocal
cd /d "%~dp0"
title CS2 Local Claude - Build

where py >nul 2>nul
if errorlevel 1 (
  echo [FEHLER] Python 3.12 fehlt: https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist .venv (
  py -3 -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt pyinstaller || goto :fail
python tests\test_core.py || goto :fail
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1 || goto :fail
echo.
echo Fertig: dist\CS2LocalClaude.exe
pause
exit /b 0

:fail
echo.
echo [FEHLER] Build abgebrochen, siehe Meldungen oben.
pause
exit /b 1
