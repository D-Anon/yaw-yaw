"""Configure local asset paths before importing Kokoro/Hugging Face."""
import io
import os
import sys
from pathlib import Path

# Safe stream fallback for GUI environments (pythonw.exe, windowed launchers)
class _NullStream(io.StringIO):
    def write(self, s):
        return len(s)
    def flush(self):
        pass

if sys.stdout is None:
    sys.stdout = _NullStream()
if sys.stderr is None:
    sys.stderr = _NullStream()

ROOT = Path(__file__).resolve().parent


def configure(offline=True):
    if not (3, 10) <= sys.version_info[:2] < (3, 13):
        raise RuntimeError("Use Python 3.10–3.12 (the Windows setup uses 3.12).")
    if not (ROOT / "src" / "kokoro_tts_local" / "models.py").is_file():
        raise RuntimeError("Extract this update into the new Kokoro-TTS-Local GitHub folder, beside pyproject.toml.")
    sys.path.insert(0, str(ROOT / "src"))
    os.environ.setdefault("KOKORO_BASE_DIR", str(ROOT / "kokoro-data"))
    base = Path(os.environ["KOKORO_BASE_DIR"]).expanduser().resolve()
    os.environ["KOKORO_BASE_DIR"] = str(base)
    os.environ.setdefault("HF_HOME", str(base / "hf-cache"))
    if offline or os.environ.get("HF_HUB_OFFLINE") != "0":
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["DO_NOT_TRACK"] = "1"
        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    return base
