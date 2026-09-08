@echo off
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Run setup_phase14.cmd first.
  pause
  exit /b 1
)
venv\Scripts\python.exe web_app.py %*
if errorlevel 1 pause
