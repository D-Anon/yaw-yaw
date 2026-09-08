# Yaw-Yaw v2

**Your words. Your voice.** A local speech studio powered by the Kokoro model.

## Open the app

Double-click **start_yaw_yaw.cmd** to open the desktop studio.
For local assets only, use **start_desktop_offline.cmd**.
For the browser studio, use **start_web.cmd** (or `start_web.cmd --offline`).

The launchers select the project's Python environment automatically.

## A workspace for your voice

- **Modern Theming**: Instant toggle between Nordic Light and Midnight Dark studio themes.
- **Script Editor**: Spacious writing area with live character limit, word count, and estimated duration.
- **File & Clipboard Tools**: One-click text copying (`Ctrl+C` or `📋 Copy`), `.txt` file import, and script export.
- **Voices with Character**: American and British English voices with descriptive tone traits and gender indicators.
- **Philippine Languages**: Seamless local engine switching for Filipino/Tagalog, Cebuano, Ilocano, Hiligaynon, and Waray.
- **Speaking Speed**: Smooth 0.5× to 2.0× slider plus quick speed presets (`0.8×`, `1.0×`, `1.2×`, `1.5×`).
- **Audio Playback Studio**: Play, stop, volume control slider (0–100%), and export to WAV or MP3.
- **Take History**: Session clip history drawer to review, replay, or restore past generations.
- **Keyboard Shortcuts**: **Enter** / **Ctrl+Enter** generates and plays, **Shift+Enter** adds a new line, **Ctrl+L** clears text, **Ctrl+O** opens a text file, and **Ctrl+S** saves script. Slower speeds dynamically adapt the allowed text limit. Stop Playback stops sound while generation continues in the background.

## Setup

Use Python 3.12 and run `setup_phase14.cmd`. The setup installs dependencies,
runs regression tests, prepares English assets, and verifies offline speech.
This workspace already has its model assets and Python environment installed.

Additional languages are optional:

```powershell
.\venv\Scripts\python.exe -m pip install -e ".[multilingual]"
```

Some additional language packages need Windows C++ build tools and separate
language dictionaries. MP3/AAC export in the browser needs FFmpeg. WAV export
works without FFmpeg.

## Philippine language packs

Yaw-Yaw automatically uses Kokoro for English and Meta MMS-TTS for Philippine
languages. Generation, playback, subtitles, history, and export work through the
same controls. Open **Manage language packs** in the desktop app to install and
check optional models without leaving the interface. The command-line alternative is:

```powershell
.\setup_local_languages.cmd install tgl ceb
.\setup_local_languages.cmd status
```

Use `install all` to add Filipino/Tagalog (`tgl`), Cebuano (`ceb`), Ilocano
(`ilo`), Hiligaynon (`hil`), and Waray (`war`). Each MMS language currently has
one voice, so Kokoro voice blending is automatically unavailable for those
selections. Meta's MMS checkpoints are licensed CC BY-NC 4.0; review that
license before commercial distribution.

See [the setup and offline guide](START_HERE_PHASE1_4.md) for asset preparation,
verification, and environment overrides.

## Compatibility and credits

The Python distribution is named `yaw-yaw`. The `kokoro_tts_local` module name,
existing launcher names, `KOKORO_*` settings, and `kokoro-data` directory are
retained for compatibility with your downloaded assets and existing scripts.
New CLI aliases are `yaw-yaw` and `yaw-yaw-web`; the original commands remain.

Yaw-Yaw builds on [PierrunoYT/Kokoro-TTS-Local](https://github.com/PierrunoYT/Kokoro-TTS-Local),
restored from commit `0906a4e3a32b988307615309c722cdc866782dce`, and uses
[hexgrad's Kokoro](https://github.com/hexgrad/kokoro) speech engine.
Upstream author credits and the [Apache 2.0 license](LICENSE) are preserved.

## Checks

```powershell
.\venv\Scripts\python.exe -m unittest -q test_phase14 test_desktop_phase12 test_critical_fixes
.\venv\Scripts\python.exe verify_offline.py
```

The offline report and sample WAV files are saved in `kokoro-data`.
