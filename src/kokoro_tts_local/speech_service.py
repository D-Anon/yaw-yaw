"""Shared, bounded inference for desktop and Gradio, using models.py's cache."""
from contextlib import closing
import json
import math
import os
import re
from pathlib import Path
from typing import Optional, Tuple, List, Union

SAMPLE_RATE = 24000
MAX_TEXT_LENGTH = 5000
MIN_SPEED = 0.1
MAX_SPEED = 3.0
MAX_SEGMENTS = 100
MAX_SAMPLES = 600 * SAMPLE_RATE


class GenerationCancelled(Exception):
    pass


def select_device():
    import torch
    chosen = os.environ.get("KOKORO_DEVICE", "auto").lower()
    if chosen not in ("auto", "cpu", "cuda"):
        raise ValueError("KOKORO_DEVICE must be auto, cpu or cuda.")
    if chosen == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable. Set KOKORO_DEVICE=cpu.")
    return ("cuda" if torch.cuda.is_available() else "cpu") if chosen == "auto" else chosen


def validate_request(text, speed):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Please enter text first.")
    speed = float(speed)
    if not math.isfinite(speed) or not MIN_SPEED <= speed <= MAX_SPEED:
        raise ValueError(f"Speed must be between {MIN_SPEED} and {MAX_SPEED}.")
    if len(text) > MAX_TEXT_LENGTH or len(text) / speed > MAX_TEXT_LENGTH:
        raise ValueError("Text is too long for this speed; shorten it or increase speed.")
    return speed


def get_pronunciations_path():
    from . import paths
    return paths.get_base_dir() / "pronunciations.json"


def load_pronunciations() -> dict:
    """Load user pronunciation rules from local JSON."""
    dict_file = get_pronunciations_path()
    if dict_file.is_file():
        try:
            with open(dict_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_pronunciations(rules: dict):
    """Save user pronunciation rules to local JSON."""
    dict_file = get_pronunciations_path()
    dict_file.parent.mkdir(parents=True, exist_ok=True)
    with open(dict_file, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)


def apply_pronunciations(text: str, rules: Optional[dict] = None) -> str:
    """Replace words in text according to whole-word dictionary rules."""
    if rules is None:
        rules = load_pronunciations()
    if not rules:
        return text
    for word, replacement in rules.items():
        w = word.strip()
        if w:
            text = re.sub(rf'\b{re.escape(w)}\b', replacement.strip(), text, flags=re.IGNORECASE)
    return text


def parse_pause_segments(text: str) -> List[Tuple[str, Union[str, float]]]:
    """Parse text for [pause Xs] or [pause Xms] tags into ('speech', text) or ('pause', sec)."""
    pattern = re.compile(r'\[pause\s*([\d\.]+)\s*(s|sec|seconds|ms)?\]', re.IGNORECASE)
    segments = []
    last_end = 0
    for match in pattern.finditer(text):
        start, end = match.span()
        if start > last_end:
            chunk = text[last_end:start].strip()
            if chunk:
                segments.append(("speech", chunk))
        val = float(match.group(1))
        unit = (match.group(2) or "s").lower()
        duration = val / 1000.0 if unit == "ms" else val
        duration = max(0.05, min(duration, 10.0))  # 50ms to 10s
        segments.append(("pause", duration))
        last_end = end
    if last_end < len(text):
        chunk = text[last_end:].strip()
        if chunk:
            segments.append(("speech", chunk))
    return segments if segments else [("speech", text)]


def parse_dialogue(text: str, default_voice: str) -> Optional[List[Tuple[str, str]]]:
    """Detect dialogue lines: [voice_name]: text or voice_name: text.
    Returns list of (voice_name, text_line) or None if no dialogue tags detected."""
    lines = text.strip().splitlines()
    dialogue = []
    line_pattern = re.compile(r'^(?:\[([a-zA-Z0-9_\-]+)\]:?|([a-zA-Z0-9_\-]+):)\s*(.+)$')
    has_dialogue = False
    current_voice = default_voice

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        m = line_pattern.match(line)
        if m:
            v_name = (m.group(1) or m.group(2)).strip()
            content = m.group(3).strip()
            if v_name.startswith(('af_', 'am_', 'bf_', 'bm_', 'zf_', 'zm_', 'ef_', 'em_', 'ff_', 'hf_', 'hm_', 'if_', 'im_', 'jf_', 'jm_', 'pf_', 'pm_')):
                has_dialogue = True
                current_voice = v_name
                dialogue.append((current_voice, content))
            else:
                dialogue.append((current_voice, line))
        else:
            dialogue.append((current_voice, line))

    return dialogue if has_dialogue else None


def get_voice_payload(voice: str, secondary_voice: Optional[str] = None, blend_ratio: float = 0.0):
    """Return safe voice file path or blended PyTorch tensor."""
    from . import models
    import torch
    if secondary_voice and blend_ratio > 0.001 and secondary_voice != voice:
        v1_path = models.get_safe_voice_path(voice)
        v2_path = models.get_safe_voice_path(secondary_voice)
        t1 = torch.load(str(v1_path), weights_only=True, map_location='cpu')
        t2 = torch.load(str(v2_path), weights_only=True, map_location='cpu')
        w = max(0.0, min(float(blend_ratio), 1.0))
        return (1.0 - w) * t1 + w * t2
    return str(models.get_safe_voice_path(voice))


def apply_tone_shaping(audio, tone: str = "natural"):
    """Apply gentle acoustic EQ (warmth, clarity, broadcast). Pure numpy FIR."""
    if tone == "natural" or not tone or len(audio) < 100:
        return audio
    import numpy as np

    kernel = np.array([0.25, 0.5, 0.25], dtype=np.float32)
    smoothed = np.convolve(audio, kernel, mode="same")

    if tone in ("warm", "warmth"):
        # Low-mid emphasis
        out = 0.65 * audio + 0.35 * smoothed
    elif tone in ("crisp", "clarity"):
        # Presence boost (unsharp mask)
        out = audio + 0.30 * (audio - smoothed)
    elif tone == "broadcast":
        # Rich warmth with subtle presence
        out = 0.85 * audio + 0.15 * smoothed + 0.15 * (audio - smoothed)
    else:
        return audio

    peak = np.max(np.abs(out))
    if peak > 1.0:
        out = (out / peak) * 0.98
    return out.astype(np.float32)


def generate_subtitles_srt(subtitles: List[Tuple[float, float, str]]) -> str:
    """Format subtitle segments (start_sec, end_sec, text) into standard SRT format."""
    def format_ts(sec: float) -> str:
        sec = max(0.0, sec)
        millis = int(round((sec - int(sec)) * 1000))
        secs = int(sec) % 60
        mins = (int(sec) // 60) % 60
        hrs = int(sec) // 3600
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    lines = []
    for idx, (start, end, text) in enumerate(subtitles, 1):
        clean_text = text.strip()
        if clean_text:
            lines.append(str(idx))
            lines.append(f"{format_ts(start)} --> {format_ts(end)}")
            lines.append(clean_text)
            lines.append("")
    return "\n".join(lines)


def get_pipeline_for_voice(voice, device=None):
    from . import models
    import torch
    language = models.get_language_code_from_voice(voice)
    path = models.get_safe_voice_path(voice)
    if not path.is_file() or path.stat().st_size == 0:
        if models.OFFLINE_MODE:
            raise FileNotFoundError(f"Offline voice is missing: {path}. Run prepare_offline.py while online.")
        models.download_voice_files([voice + ".pt"], required_count=1)
    device = device or select_device()
    return models.build_model(None, device, lang_code=language)


def synthesize(
    text,
    voice,
    speed=1.0,
    device=None,
    language=None,
    progress=None,
    cancelled=None,
    secondary_voice=None,
    blend_ratio=0.0,
    tone="natural",
    apply_dict=True,
    return_subtitles=False,
):
    """Return finite mono float32 samples with voice blending, pause tags, and tone shaping."""
    speed = validate_request(text, speed)
    from . import models
    import numpy as np

    if apply_dict:
        text = apply_pronunciations(text)

    detected = models.get_language_code_from_voice(voice)
    if language is not None and detected != language:
        raise ValueError("Choose a voice matching the selected language.")

    def checkpoint():
        if cancelled is not None and cancelled.is_set():
            raise GenerationCancelled()

    checkpoint()
    device = device or select_device()

    dialogue = parse_dialogue(text, default_voice=voice)
    if dialogue:
        tasks = []
        for v_name, line in dialogue:
            for kind, val in parse_pause_segments(line):
                tasks.append((v_name, kind, val))
    else:
        tasks = []
        for kind, val in parse_pause_segments(text):
            tasks.append((voice, kind, val))

    chunks = []
    subtitles = []
    current_time = 0.0
    total_samples = 0
    segment_count = 0

    for task_idx, (cur_voice, kind, val) in enumerate(tasks):
        checkpoint()
        if kind == "pause":
            pause_samples = int(float(val) * SAMPLE_RATE)
            if pause_samples > 0:
                silence = np.zeros(pause_samples, dtype=np.float32)
                chunks.append(silence)
                current_time += float(val)
                total_samples += pause_samples
            continue

        speech_text = str(val).strip()
        if not speech_text:
            continue

        pipeline = get_pipeline_for_voice(cur_voice, device)
        if cur_voice == voice and secondary_voice and blend_ratio > 0.001:
            voice_payload = get_voice_payload(cur_voice, secondary_voice, blend_ratio)
        else:
            voice_payload = str(models.get_safe_voice_path(cur_voice))

        start_time_for_task = current_time
        with closing(pipeline.iter_speech(speech_text, voice=voice_payload, speed=speed, split_pattern=r'\n+')) as generator:
            for _, (_, ps, audio) in enumerate(generator, start=1):
                checkpoint()
                segment_count += 1
                if segment_count > MAX_SEGMENTS:
                    raise ValueError("Audio exceeds 100 segments. Please split the text.")
                if audio is None:
                    continue
                if hasattr(audio, "detach"):
                    audio = audio.detach().cpu().numpy()
                chunk = np.asarray(audio, dtype=np.float32)
                if chunk.ndim != 1 or not np.all(np.isfinite(chunk)):
                    raise ValueError("The model returned invalid audio.")
                total_samples += chunk.size
                if total_samples > MAX_SAMPLES:
                    raise ValueError("Audio exceeds ten minutes. Please split the text.")
                if chunk.size:
                    chunks.append(chunk)
                    duration = chunk.size / SAMPLE_RATE
                    current_time += duration
                    if progress:
                        progress(f"Generated {len(chunks)} audio segment(s)...")

        end_time_for_task = current_time
        if end_time_for_task > start_time_for_task:
            subtitles.append((start_time_for_task, end_time_for_task, speech_text))

        # Natural 150ms pause between separate lines/dialogue turns
        if dialogue and task_idx < len(tasks) - 1:
            gap = np.zeros(int(0.15 * SAMPLE_RATE), dtype=np.float32)
            chunks.append(gap)
            current_time += 0.15
            total_samples += len(gap)

    checkpoint()
    if not chunks:
        raise ValueError("No audio was generated. Try another text or voice.")

    combined = np.concatenate(chunks)
    if tone != "natural":
        combined = apply_tone_shaping(combined, tone=tone)

    if return_subtitles:
        srt_text = generate_subtitles_srt(subtitles)
        return combined, srt_text
    return combined
