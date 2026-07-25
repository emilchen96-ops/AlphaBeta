@echo off
title AlphaDesk Stopper
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\Users\60576\Documents\Quantitative Sysytem\scripts\stop-alphadesk-safe.ps1"
if errorlevel 1 (
  echo.
  echo AlphaDesk failed to stop. Please review the error above.
  pause
)
