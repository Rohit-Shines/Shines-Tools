@echo off
setlocal
title HL7 SHINES Explorer Uninstaller
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Installer Support - Do Not Open.ps1" -Uninstall
if errorlevel 1 pause
