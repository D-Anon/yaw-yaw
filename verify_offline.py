"""Attempt real CPU inference with Python socket connections disabled."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import socket
import subprocess
import sys
from phase14_bootstrap import configure


def block_network():
    def denied(*args, **kwargs):
        raise RuntimeError("Offline verification blocked a network connection.")
    socket.create_connection = denied
    socket.getaddrinfo = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    # Preserve Popen as a class: asyncio.windows_utils subclasses it during
    # import. Replacing it with a function breaks offline imports on Windows.
    # Audit hooks reject process creation without changing the subprocess API.
    def guard_process(event, arguments):
        if event != "subprocess.Popen":
            return
        executable, args, _, _ = arguments
        if isinstance(args, (list, tuple)) and list(args) in (
            ["/sbin/ldconfig", "-p"], ["/usr/sbin/ldconfig", "-p"]
        ) and executable == args[0]:
            return
        denied()
    sys.addaudithook(guard_process)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _digest_310(stream)


def _digest_310(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voices", nargs="+", default=["af_heart", "bf_emma"])
    args = parser.parse_args()
    base = configure(offline=True)
    base.mkdir(parents=True, exist_ok=True)
    report_path = base / "offline-verification.json"
    report = {"passed": False, "date": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(), "platform": platform.platform(), "voices": args.voices, "network_guard": "Python sockets and child processes blocked except local ldconfig -p"}
    try:
        from kokoro_tts_local import paths
        needed = [paths.get_model_dir() / "kokoro-v1_0.pth", paths.get_config_path()]
        for voice in args.voices:
            if not voice.startswith(("af_", "am_", "bf_", "bm_")) or not all(c.isalnum() or c == "_" for c in voice):
                raise ValueError(f"Invalid English voice: {voice}")
            needed.append(paths.get_voices_dir() / (voice + ".pt"))
        missing = [str(path) for path in needed if not path.is_file() or path.stat().st_size == 0]
        if missing:
            raise FileNotFoundError("Missing assets:\n" + "\n".join(missing))
        block_network()
        import numpy as np
        import soundfile as sf
        from kokoro_tts_local.speech_service import synthesize, SAMPLE_RATE
        durations = {}
        for voice in args.voices:
            print(f"Offline speech test: {voice}", flush=True)
            audio = synthesize("Hello. Offline speech generation is working.", voice, device="cpu")
            if not audio.size or not np.isfinite(audio).all() or not np.any(audio):
                raise ValueError(f"Invalid or silent output for {voice}")
            output = base / f"offline-test-{voice}.wav"
            sf.write(output, audio, SAMPLE_RATE)
            saved, rate = sf.read(output)
            if rate != SAMPLE_RATE or len(saved) != len(audio):
                raise ValueError("WAV round-trip validation failed")
            durations[voice] = len(audio) / SAMPLE_RATE
        report.update(passed=True, duration_seconds=durations,
                      files={str(p): digest(p) for p in needed},
                      packages={d.metadata['Name']: d.version for d in metadata.distributions() if d.metadata.get('Name')})
        print("PASS: requested voices generated speech with the network guard enabled.")
        return 0
    except Exception as error:
        report["error"] = str(error)
        print(f"FAIL: {error}\nRun prepare_offline.py online, then retry.", file=sys.stderr)
        return 1
    finally:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {report_path}")


if __name__ == "__main__":
    raise SystemExit(main())
