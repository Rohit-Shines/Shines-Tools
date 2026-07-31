@echo off
setlocal
title HL7 SHINES Explorer Installer
echo ========================================================
echo        HL7 SHINES EXPLORER 1.2.0 - INSTALLER
echo ========================================================
echo.
echo Installing the application for the current Windows user...
echo The first installation downloads the official Python runtime.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Installer Support - Do Not Open.ps1"
if errorlevel 1 (
  echo.
  echo Installation did not complete. Read "2 - READ ME FIRST.txt".
  pause
  exit /b 1
)
exit /b 0
