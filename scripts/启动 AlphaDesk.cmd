@echo off
title AlphaDesk Starter
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\Users\60576\Documents\Quantitative Sysytem\scripts\start-alphadesk.ps1"
if errorlevel 1 (
  echo.
  echo AlphaDesk failed to start. Please review the error above.
  pause
)
