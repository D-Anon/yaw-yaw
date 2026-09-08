@echo off
setlocal
cd /d "%~dp0"
set HF_HUB_OFFLINE=0
set TRANSFORMERS_OFFLINE=0
set KOKORO_BASE_DIR=%~dp0kokoro-data
if "%~1"=="" (
  echo Usage: setup_local_languages.cmd install tgl ceb
  echo        setup_local_languages.cmd install all
  echo        setup_local_languages.cmd status
  exit /b 2
)
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" -m kokoro_tts_local.mms_engine %*
) else if exist "runtime\python.exe" (
  "runtime\python.exe" -m kokoro_tts_local.mms_engine %*
) else (
  python -m kokoro_tts_local.mms_engine %*
)
