@echo off
setlocal
cd /d "%~dp0"
if not exist "pyproject.toml" goto wrongfolder
if not exist "src\kokoro_tts_local\models.py" goto wrongfolder
if not exist "src\kokoro_tts_local\paths.py" goto wrongfolder
if not exist "venv\Scripts\python.exe" (
  py -3.12 -c "import sys" >nul 2>&1
  if errorlevel 1 goto missingpython
  py -3.12 -m venv venv
  if errorlevel 1 goto failed
)
venv\Scripts\python.exe -c "import sys; assert (3,10) <= sys.version_info[:2] < (3,13), 'Use Python 3.10-3.12'"
if errorlevel 1 goto failed
venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 goto failed
venv\Scripts\python.exe -m pip check
if errorlevel 1 goto failed
venv\Scripts\python.exe -m unittest -v test_phase14 test_desktop_phase12 test_critical_fixes
if errorlevel 1 goto failed
venv\Scripts\python.exe prepare_offline.py
if errorlevel 1 goto failed
venv\Scripts\python.exe -m pip freeze --exclude-editable > requirements-local-verified.txt
if errorlevel 1 goto failed
echo Setup and offline CPU verification passed for af_heart and bf_emma.
echo Package versions recorded in requirements-local-verified.txt for this computer.
pause
exit /b 0
:wrongfolder
echo Required application source files are missing. Restore the complete Kokoro-TTS-Local source.
pause
exit /b 1
:missingpython
echo Python 3.12 is required for this setup. Python 3.14 is not supported.
echo Install Python 3.12 using the Python install manager: py install 3.12
echo Then run this setup again.
pause
exit /b 1
:failed
echo Setup did not finish. Read the error above; do not treat offline mode as verified.
pause
exit /b 1
