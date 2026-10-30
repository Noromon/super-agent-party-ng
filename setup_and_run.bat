@echo off
REM ============================================================
REM Super Agent Party - source deployment bootstrap (S171)
REM Thin launcher: hands over to setup_and_run.ps1 (PowerShell).
REM Everything the script installs or runs is prompted first.
REM ============================================================
title Super Agent Party - Setup and Run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_and_run.ps1" %*
if errorlevel 1 (
  echo.
  echo [Setup] Finished with an error. See messages above.
)
pause
