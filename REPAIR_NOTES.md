# Project repair — September 5, 2026

## Changes

- Restored ten missing application modules, upstream regression tests, and
  documentation from PierrunoYT/Kokoro-TTS-Local commit
  `0906a4e3a32b988307615309c722cdc866782dce`. Existing desktop and shared-service
  update files were preserved.
- Installed Python 3.12.10 alongside Python 3.14 and created the project `venv`.
- Made additional language dependencies optional after the Japanese
  `pyopenjtalk` build failed without Windows C++ build tools. Default installation
  supports the English desktop/browser workflow. Use `.[multilingual]` for
  extra language dependencies and prepare their dictionaries/models separately.
- Made `requirements.txt` use the dependency list in `pyproject.toml`.
- Added source/interpreter checks and the upstream regression suite to setup.
- Fixed the offline checker's Windows import failure by preserving the
  `subprocess.Popen` class and blocking process creation with an audit hook.
  The regression test checks that asyncio still imports and network/process
  attempts remain blocked.
- Downloaded the standard model, 54 voice packs, and English language assets.
  Added local data/downloads to `.gitignore` and saved verified package versions.

## Verified

- All 35 regression tests pass on Python 3.12.10.
- No broken package requirements reported by pip.
- Desktop window initialization and shutdown pass with a hidden window.
- Browser interface construction passes with server launch mocked.
- Real CPU synthesis and WAV write/read pass for `af_heart` and `bf_emma`
  with the offline checker's network/process guard enabled.

Evidence: `kokoro-data/offline-verification.json`,
`kokoro-data/offline-test-af_heart.wav`,
`kokoro-data/offline-test-bf_emma.wav`, and
`requirements-local-verified.txt`.

Physical speaker playback, a live browser session, and extra languages have
not been verified. The offline checker is a Python guard, not an OS firewall.

## Launch

Double-click `start_desktop_offline.cmd` for the prepared desktop app.
Use `start_web.cmd --offline` from a terminal for the browser interface.
Use the launchers so the correct Python environment and data paths are selected.

## Suggested next improvements

1. Add a desktop speech-speed slider and remember the last selected voice.
2. Show downloaded voices and their offline readiness in the interface.
3. Add text-file import and a generation queue for longer documents.
4. Add a Cancel Generation button; Stop Playback currently only stops audio.
5. Use the verified version snapshot for repeatable installations on similar
   Windows systems, updating dependencies only after rerunning verification.
