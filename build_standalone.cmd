@echo off
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo Error: Python virtual environment not found in venv.
    pause
    exit /b 1
)
venv\Scripts\python.exe build_standalone.py
if errorlevel 1 (
    echo Build failed. Read the error above.
    pause
    exit /b 1
)
pause
