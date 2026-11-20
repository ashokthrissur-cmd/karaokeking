@echo off
REM Double-click this file to set up ABI Karaoke on Windows.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-ABIKaraoke.ps1" %*
echo.
pause
