"""Online preparation; optionally reuse model/voice files from an older folder."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from phase14_bootstrap import configure, ROOT


def copy_missing(source, destination):
    if destination.exists():
        return False
    if not source.is_file() or source.stat().st_size == 0:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = Path(temporary) / source.name
        shutil.copyfile(source, staged)
        if not destination.exists():
            os.replace(staged, destination)
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Optional old Kokoro folder containing model/config/voices")
    parser.add_argument("--voices", nargs="+", default=["af_heart", "bf_emma"], help="English voices to warm and verify")
    args = parser.parse_args()
    base = configure()
    if os.environ.get("HF_HUB_OFFLINE") == "1":
        parser.error("Preparation needs online mode. Use a new terminal without HF_HUB_OFFLINE=1.")
    from kokoro_tts_local import models, paths, speech_service
    voices = list(dict.fromkeys(args.voices))
    for voice in voices:
        if voice + ".pt" not in models.VOICE_FILES or models.get_language_code_from_voice(voice) not in ("a", "b"):
            parser.error(f"Not a supported English voice: {voice}")
    if args.source:
        source = args.source.expanduser().resolve()
        if not source.is_dir():
            parser.error(f"Source folder does not exist: {source}")
        for name, target in [("kokoro-v1_0.pth", paths.get_model_dir() / "kokoro-v1_0.pth"), ("config.json", paths.get_config_path())]:
            if copy_missing(source / name, target):
                print(f"Reused {name}")
        for name in models.VOICE_FILES:
            if copy_missing(source / "voices" / name, paths.get_voices_dir() / name):
                print(f"Reused {name}")
    print(f"Application data: {base}")
    # Warm each requested language: this also prepares English spaCy/G2P assets.
    # The upstream model loader downloads the standard voice set on first build.
    for voice in voices:
        print(f"Preparing {voice}...", flush=True)
        speech_service.synthesize("Hello. This is an offline preparation test.", voice, device="cpu", progress=print)
    result = subprocess.run([sys.executable, str(ROOT / "verify_offline.py"), "--voices", *voices], cwd=ROOT)
    return result.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Preparation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
