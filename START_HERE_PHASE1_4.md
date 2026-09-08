# Yaw-Yaw — Setup and offline guide

The application is now named **Yaw-Yaw**. Launch `start_yaw_yaw.cmd` for the
desktop studio, or keep using the existing desktop/browser launchers. Existing
`kokoro-data` files and `KOKORO_*` environment settings remain compatible.
The desktop includes a speaking-speed slider, live text limit, and a separate
playback area. The notes below retain the source project's history and credits.

**Restored workspace:** The missing upstream application source has now been
merged into this folder from the exact commit below. Skip section 1 when using
this folder. Model/voice readiness is determined by `verify_offline.py`, not by
the presence of source files. The original package notes below describe the
update before this restoration.

**Local verification, September 5, 2026:** Python 3.12.10 and the virtual
environment are installed. All 35 regression tests passed. Desktop window
initialization/shutdown and browser interface construction passed. Real CPU
synthesis and WAV read/write passed offline for `af_heart` and `bf_emma`.
See `kokoro-data/offline-verification.json` and `requirements-local-verified.txt`.
The Windows offline guard now uses a subprocess audit hook so it does not break
imports that subclass `subprocess.Popen`. Physical speaker playback has not
been checked. You can launch `start_desktop_offline.cmd` directly now.

This ZIP is an update to a fresh download of:
https://github.com/PierrunoYT/Kokoro-TTS-Local

Prepared against commit `0906a4e3a32b988307615309c722cdc866782dce` on branch
`master`. It is not a complete standalone installation and contains no model
weights, voices, virtual environment, or downloaded language assets.

## 1. Copy into your new GitHub folder

Keep a backup of the newly extracted folder. Extract the CONTENTS of this ZIP
directly into the new project folder, beside its existing `pyproject.toml`.
Merge the `src` folder and accept replacement of these three files:

- `pyproject.toml`
- `requirements.txt`
- `src/kokoro_tts_local/gradio_interface.py`

The remaining files are additions, including `desktop_app.py` and
`src/kokoro_tts_local/speech_service.py`. If the Phase 1–2 desktop is already
there, replace it with this version. Do not copy the old Phase 1–2 requirements
or README over the new GitHub version. This update keeps the upstream removal
of mishkal-hebrew and the Python 3.10–3.12 requirement.

The upstream source may change in future: use the stated commit as your base if
your new download has a substantially different layout or dependencies.

## 2. Windows setup (internet required)

The default install prepares English. Extra language packages are now optional
because the Japanese `pyopenjtalk` source build failed on Windows without C++
build tools. If you need additional languages, install their prerequisites and
run `venv\Scripts\python.exe -m pip install -e ".[multilingual]"`. Language
models/dictionaries must also be prepared before using those languages offline.

Install 64-bit Python 3.12 with the Python Launcher. Double-click
`setup_phase14.cmd`. It creates `venv` if absent, installs the updated project,
runs dependency checks and regression tests, prepares English assets, and runs
an offline CPU test for `af_heart` and `bf_emma` in a separate process.

Only after those steps succeed does it save
`requirements-local-verified.txt`, a package-version snapshot for YOUR computer.
It is platform-specific and excludes the local editable project; install this
source separately. No universal Windows/GPU compatibility is implied.

If setup fails, read the error and rerun after fixing it. An existing environment
is preserved, but installing the project may change packages. Prefer the fresh
folder's own environment rather than copying an older `venv`.

## 3. Launch

- `start_desktop.cmd`: desktop with online asset download permitted.
- `start_desktop_offline.cmd`: desktop using local assets only.
- `start_web.cmd`: existing Gradio browser interface using the shared engine.
- `start_web.cmd --offline`: browser interface with offline flags.

The desktop remains English-focused, with 20 American and 8 British voices.
The browser retains upstream language options and export controls. Initial
offline preparation verifies only the selected English voices, not every
language in the browser. Other languages need their own G2P resources/models.

Enter generates and plays; Shift+Enter inserts a new line. Generation runs in a
background thread, with controls disabled against duplicate submissions.
Stop Playback stops sound; it does not cancel model generation. Closing the
window discards late results without waiting for model loading to finish.

## 4. Reuse the model and voices from your old Drive folder

Download the old files onto your PC first. Instead of automatic preparation,
you may use these commands from the new project folder after installation:

```powershell
.\venv\Scripts\python.exe prepare_offline.py --source "C:\path\to\old\Kokoro-TTS-Local"
```

This copies missing `kokoro-v1_0.pth`, `config.json`, and known voice `.pt` files
into the configured data directory. Existing destination files are preserved.
The preparation still needs internet for missing model/language resources.
An old root-level model file alone is not an offline-ready installation.

Default application data location: `kokoro-data` beside these launchers.
Inside it, model/config live at the top level, voices under `voices`, Hugging
Face cache under `hf-cache`, and browser audio under `outputs`.
Use these launchers so desktop and browser resolve the same paths. Calling
upstream console commands directly uses upstream platform defaults unless you
set `KOKORO_BASE_DIR` yourself.

Advanced overrides are preserved: `KOKORO_BASE_DIR`, `KOKORO_MODEL_DIR`,
`KOKORO_CONFIG_PATH`, `KOKORO_VOICES_DIR`, `HF_HOME`. Set absolute paths and keep
them the same when preparing, verifying, and launching. `KOKORO_DEVICE=cpu`
forces CPU in both interfaces; `auto` is the default; `cuda` requires CUDA.

## 5. Verify offline operation on your PC

```powershell
.\venv\Scripts\python.exe verify_offline.py
```

The checker enables offline flags before importing the model libraries, blocks
Python socket connections and child processes (except local Linux library
lookup), then attempts actual CPU synthesis and WAV write/read for two voices.
It writes `kokoro-data/offline-verification.json` with success/failure, versions,
asset hashes and output durations. A failed attempt overwrites any old pass
report with a failure. The report covers that run, machine and those assets.

To test additional English voices:

```powershell
.\venv\Scripts\python.exe prepare_offline.py --voices af_heart af_bella bf_emma
.\venv\Scripts\python.exe verify_offline.py --voices af_heart af_bella bf_emma
```

For final acceptance, disconnect your PC from the network, launch the offline
desktop and play/save a sample. The checker validates inference and WAV files,
not speakers or the physical audio device. The Python network guard is not an
operating-system firewall.

## What each phase provides

| Phase | Implemented |
| --- | --- |
| 1 | Desktop sounddevice dependency; Python version gate; language/voice validation; setup checks and a version snapshot only after successful local verification |
| 2 | Background loading/generation; progress; duplicate guard; Stop Playback; playback/save errors; safe close |
| 3 | Explicit shared data paths; optional old-asset import; online preparation; offline launch and real-inference checker |
| 4 | Desktop and Gradio call speech_service; model construction, language-keyed caching and locking remain in upstream models.py; shared device and audio limits |

Within one process, upstream caches share model weights across compatible
language pipelines. Separate desktop/browser processes each have their own RAM
cache but use the same files. No background server is required.

## Validation and limits of this delivered package

35 automated tests passed under Python 3.12.13, including the upstream critical
regression tests. Syntax compilation passed. Model inference is mocked in those
tests. Checks cover the common Gradio/desktop call path, local voice routing,
language changes, cache/locking behavior, offline failure reporting, duplicate
requests, cancellation cleanup, playback failures and save errors.

The local dependency-install attempt ended with a network approval cancellation.
No actual model synthesis or Windows UI/audio test was completed here. Therefore
offline readiness and a complete tested Windows dependency set are NOT claimed.
The supplied setup/checker must pass on your PC before marking those acceptance
items complete. Offline verification is scoped to English for this update.

Run regression tests manually:

```powershell
.\venv\Scripts\python.exe -m unittest -v test_phase14 test_desktop_phase12 test_critical_fixes
```

Recovery: restore the three replaced files from your backup and remove only the
added update scripts if you no longer want this update. Keep `kokoro-data` and
your generated audio. No old model, voice, or environment files were deleted by
the delivered update.
