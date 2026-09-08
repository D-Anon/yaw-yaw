"""Offline-capable Meta MMS-TTS backend for Philippine language packs."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import paths


LANGUAGE_PACKS = {
    "tgl": {"name": "Filipino / Tagalog", "model": "facebook/mms-tts-tgl"},
    "ceb": {"name": "Cebuano", "model": "facebook/mms-tts-ceb"},
    "ilo": {"name": "Ilocano", "model": "facebook/mms-tts-ilo"},
    "hil": {"name": "Hiligaynon", "model": "facebook/mms-tts-hil"},
    "war": {"name": "Waray", "model": "facebook/mms-tts-war"},
}

_MODEL_FILES = ("config.json", "tokenizer_config.json", "vocab.json", "model.safetensors")
_CACHE = {}
_CACHE_LOCK = threading.RLock()


def validate_language(language: str) -> str:
    language = str(language or "").strip().lower()
    if language not in LANGUAGE_PACKS:
        raise ValueError(f"Unsupported MMS language: {language!r}")
    return language


def pack_dir(language: str) -> Path:
    return paths.get_language_packs_dir() / validate_language(language)


def pack_status(language: str) -> dict:
    """Return lightweight readiness information without loading the model."""
    language = validate_language(language)
    directory = pack_dir(language)
    missing = [name for name in _MODEL_FILES if not (directory / name).is_file()]
    size = sum(item.stat().st_size for item in directory.glob("**/*") if item.is_file()) if directory.is_dir() else 0
    return {
        "language": language,
        "name": LANGUAGE_PACKS[language]["name"],
        "engine": "Meta MMS-TTS",
        "model": LANGUAGE_PACKS[language]["model"],
        "path": str(directory),
        "ready": not missing,
        "missing": missing,
        "size_bytes": size,
        "license": "CC BY-NC 4.0",
    }


def list_pack_statuses() -> list[dict]:
    return [pack_status(language) for language in LANGUAGE_PACKS]


def install_pack(language: str, progress=None) -> Path:
    """Download one model into a deterministic directory for later offline use."""
    language = validate_language(language)
    destination = pack_dir(language)
    destination.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(f"Downloading {LANGUAGE_PACKS[language]['name']} language pack...")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise ImportError("Install huggingface-hub to download language packs.") from exc

    snapshot_download(
        repo_id=LANGUAGE_PACKS[language]["model"],
        local_dir=str(destination),
        allow_patterns=list(_MODEL_FILES) + ["README.md"],
        local_files_only=False,
    )
    status = pack_status(language)
    if not status["ready"]:
        raise FileNotFoundError("Language pack download is incomplete: " + ", ".join(status["missing"]))
    marker = {
        "language": language,
        "model": status["model"],
        "license": status["license"],
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    (destination / "yaw-yaw-pack.json").write_text(json.dumps(marker, indent=2), encoding="utf-8")
    return destination


def _load(language: str, device: str):
    language = validate_language(language)
    status = pack_status(language)
    if not status["ready"]:
        command = f"setup_local_languages.cmd install {language}"
        raise FileNotFoundError(
            f"{status['name']} is not installed. Run `{command}` while online, then reopen Yaw-Yaw."
        )
    key = (language, device)
    with _CACHE_LOCK:
        if key not in _CACHE:
            try:
                from transformers import AutoTokenizer, VitsModel
            except ImportError as exc:
                raise ImportError("The Philippine language engine requires the `transformers` package.") from exc
            directory = str(pack_dir(language))
            tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True)
            model = VitsModel.from_pretrained(directory, local_files_only=True).to(device)
            model.eval()
            _CACHE[key] = (tokenizer, model)
        return _CACHE[key]


def synthesize(text: str, language: str, speed: float = 1.0, device: str = "cpu", cancelled=None):
    """Synthesize one MMS segment and normalize it to Yaw-Yaw's 24 kHz format."""
    if cancelled is not None and cancelled.is_set():
        from .speech_service import GenerationCancelled
        raise GenerationCancelled()
    tokenizer, model = _load(language, device)
    import torch

    inputs = tokenizer(text, return_tensors="pt")
    inputs = {name: value.to(device) for name, value in inputs.items()}
    with torch.inference_mode():
        waveform = model(**inputs, speaking_rate=float(speed)).waveform
    audio = waveform.squeeze().detach().cpu().numpy().astype(np.float32)
    source_rate = int(model.config.sampling_rate)
    if source_rate != 24000 and audio.size:
        target_size = max(1, int(round(audio.size * 24000 / source_rate)))
        old_x = np.linspace(0.0, 1.0, audio.size, endpoint=False)
        new_x = np.linspace(0.0, 1.0, target_size, endpoint=False)
        audio = np.interp(new_x, old_x, audio).astype(np.float32)
    return audio


def shutdown():
    with _CACHE_LOCK:
        _CACHE.clear()


def cli(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Manage Yaw-Yaw Philippine language packs.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", help="Download packs for offline use.")
    install.add_argument("languages", nargs="+", choices=[*LANGUAGE_PACKS, "all"])
    subparsers.add_parser("status", help="Show installed language packs.")
    args = parser.parse_args(argv)
    if args.command == "status":
        for status in list_pack_statuses():
            state = "ready" if status["ready"] else "not installed"
            print(f"{status['language']:3}  {status['name']:<20} {state}")
        return 0
    requested = list(LANGUAGE_PACKS) if "all" in args.languages else args.languages
    # The setup command is explicitly online even if a prior shell set offline mode.
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ["TRANSFORMERS_OFFLINE"] = "0"
    for language in requested:
        destination = install_pack(language, progress=print)
        print(f"Ready: {LANGUAGE_PACKS[language]['name']} ({destination})")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
