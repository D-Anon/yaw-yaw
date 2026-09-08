"""Yaw-Yaw desktop speech studio, powered by Kokoro.

Only the Tk main thread touches widgets. The generation worker communicates
through a queue and owns its pipeline; only one generation may run at a time.
"""
import io
import sys

# Safeguard standard streams for GUI execution (e.g. pythonw.exe or native launcher)
class _NullStream(io.StringIO):
    def write(self, s):
        return len(s)
    def flush(self):
        pass

if sys.stdout is None:
    sys.stdout = _NullStream()
if sys.stderr is None:
    sys.stderr = _NullStream()

import logging
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
from phase14_bootstrap import configure

configure(offline="--online" not in sys.argv)
from kokoro_tts_local import speech_service

LANGUAGES = {"American English": "a", "British English": "b"}
VOICES = [
    "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica",
    "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
    "am_michael", "am_onyx", "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]
SAMPLE_RATE = speech_service.SAMPLE_RATE
logger = logging.getLogger(__name__)

VOICE_TRAITS = {
    "af_heart": "Expressive, warm & lifelike",
    "af_alloy": "Modern, crisp & energetic",
    "af_aoede": "Lyrical, bright & melodic",
    "af_bella": "Gentle, approachable & soft",
    "af_jessica": "Engaging, conversational tone",
    "af_kore": "Poised, balanced narration",
    "af_nicole": "Friendly, upbeat & natural",
    "af_nova": "Dynamic, vibrant & bright",
    "af_river": "Calm, soothing & steady",
    "af_sarah": "Professional, articulate & clear",
    "af_sky": "Breezy, youthful & lively",
    "am_adam": "Deep, authoritative & grounded",
    "am_echo": "Resonant, distinct narration",
    "am_eric": "Warm, confident & friendly",
    "am_fenrir": "Rich, intense & cinematic",
    "am_liam": "Natural, everyday conversational",
    "am_michael": "Articulate, informative & crisp",
    "am_onyx": "Low, commanding & smooth",
    "am_puck": "Playful, lighthearted tone",
    "am_santa": "Jovial, hearty & warm",
    "bf_alice": "Refined British RP, articulate",
    "bf_emma": "Gentle, melodious British tone",
    "bf_isabella": "Sophisticated, elegant voice",
    "bf_lily": "Clear, youthful British voice",
    "bm_daniel": "Calm, thoughtful British male",
    "bm_fable": "Storyteller, dramatic cadence",
    "bm_george": "Classic broadcast, distinguished",
    "bm_lewis": "Natural, modern British male",
}

THEMES = {
    "light": {
        "bg": "#F1F5F9",
        "card_bg": "#FFFFFF",
        "card_border": "#E2E8F0",
        "text_primary": "#0F172A",
        "text_secondary": "#475569",
        "text_muted": "#526966",
        "accent": "#087F72",
        "accent_hover": "#066558",
        "accent_light": "#CCFBF1",
        "button_bg": "#E8EFEB",
        "button_hover": "#D7E5DE",
        "button_disabled_bg": "#EFF2F0",
        "button_disabled_fg": "#85948E",
        "entry_bg": "#FAFBF8",
        "entry_border": "#DCE5DD",
        "select_bg": "#C7E5D8",
        "trough": "#E1EAE4",
        "header_bg": "#192E31",
        "header_fg": "#FFFFFF",
        "header_sub": "#AFCAC1",
        "badge_bg": "#2B4544",
        "badge_fg": "#D4E9D9",
    },
    "dark": {
        "bg": "#0B0F17",
        "card_bg": "#161F2E",
        "card_border": "#26354A",
        "text_primary": "#F8FAFC",
        "text_secondary": "#CBD5E1",
        "text_muted": "#94A3B8",
        "accent": "#14B8A6",
        "accent_hover": "#2DD4BF",
        "accent_light": "#134E4A",
        "button_bg": "#243347",
        "button_hover": "#33455E",
        "button_disabled_bg": "#161F2E",
        "button_disabled_fg": "#475569",
        "entry_bg": "#0E1524",
        "entry_border": "#26354A",
        "select_bg": "#134E4A",
        "trough": "#243347",
        "header_bg": "#0B0F17",
        "header_fg": "#FFFFFF",
        "header_sub": "#94A3B8",
        "badge_bg": "#1E293B",
        "badge_fg": "#2DD4BF",
    },
}


def voices_for_language(language):
    return [voice for voice in VOICES if voice.startswith(language)] if language in ("a", "b") else []


def error_message(error):
    detail = str(error) or type(error).__name__
    if isinstance(error, ImportError):
        return "A Python dependency is missing. In your activated environment, run:\npython -m pip install -r requirements.txt\n\n" + detail
    if isinstance(error, (ConnectionError, FileNotFoundError)) or any(
        word in detail.lower() for word in ("huggingface", "connection", "offline", "resolve")
    ):
        return "A model or voice asset could not be loaded. Run prepare_offline.py while online, then verify_offline.py.\n\n" + detail
    return detail


class CountLabel(ttk.Label):
    """ttk.Label whose cget() always returns str for Python 3.12 compatibility."""
    def cget(self, key):
        val = super().cget(key)
        return str(val)

    def __getitem__(self, key):
        val = super().__getitem__(key)
        return str(val)


class AudioWaveformCanvas(tk.Canvas):
    """Interactive visual waveform scrubber and timestamp display."""
    def __init__(self, parent, on_seek=None, **kwargs):
        super().__init__(parent, highlightthickness=0, bd=0, **kwargs)
        self.on_seek = on_seek
        self.audio_data = None
        self.bars = []
        self.progress_frac = 0.0
        self.elapsed_sec = 0.0
        self.total_sec = 0.0
        self.palette = THEMES["light"]
        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_click)

    def set_palette(self, palette):
        self.palette = palette
        self.configure(bg=palette["entry_bg"])
        self.redraw()

    def set_audio(self, audio, sample_rate=SAMPLE_RATE):
        self.audio_data = audio
        self.progress_frac = 0.0
        self.elapsed_sec = 0.0
        if audio is not None and len(audio) > 0:
            self.total_sec = len(audio) / sample_rate
            self._compute_bars()
        else:
            self.total_sec = 0.0
            self.bars = []
        self.redraw()

    def set_progress(self, frac: float, elapsed: float = None):
        self.progress_frac = max(0.0, min(1.0, float(frac)))
        if elapsed is not None:
            self.elapsed_sec = max(0.0, float(elapsed))
        elif self.total_sec > 0:
            self.elapsed_sec = self.progress_frac * self.total_sec
        self.redraw()

    def _compute_bars(self):
        if self.audio_data is None or len(self.audio_data) == 0:
            self.bars = []
            return
        num_bars = 90
        import numpy as np
        splits = np.array_split(self.audio_data, num_bars)
        bars = []
        for chunk in splits:
            if len(chunk) > 0:
                bars.append(float(np.max(np.abs(chunk))))
            else:
                bars.append(0.0)
        peak = max(bars) if bars and max(bars) > 0 else 1.0
        self.bars = [max(0.08, b / peak) for b in bars]

    def _on_resize(self, event):
        self.redraw()

    def _on_click(self, event):
        w = self.winfo_width()
        if w > 0 and self.audio_data is not None and len(self.audio_data) > 0:
            frac = max(0.0, min(1.0, event.x / float(w)))
            self.set_progress(frac)
            if self.on_seek:
                self.on_seek(frac)

    def redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 10 or h <= 10:
            return

        if not self.bars:
            self.create_text(
                w / 2, h / 2,
                text="Generated waveform will appear here",
                fill=self.palette.get("text_muted", "#94A3B8"),
                font=("Segoe UI", 9)
            )
            return

        num_bars = len(self.bars)
        gap = 2
        total_gaps = (num_bars - 1) * gap
        bar_w = max(2, (w - total_gaps) / num_bars)
        center_y = h / 2.0
        max_half_h = max(4, (h - 16) / 2.0)

        current_bar_idx = int(self.progress_frac * num_bars)

        for i, norm in enumerate(self.bars):
            bx = i * (bar_w + gap)
            bh = norm * max_half_h
            y0 = center_y - bh
            y1 = center_y + bh

            color = self.palette["accent"] if i <= current_bar_idx else self.palette.get("card_border", "#CBD5E1")
            self.create_line(bx + bar_w / 2, y0, bx + bar_w / 2, y1, width=max(1, int(bar_w)), fill=color)

        # Draw playhead marker
        playhead_x = int(self.progress_frac * w)
        self.create_line(playhead_x, 2, playhead_x, h - 2, fill=self.palette.get("header_fg", "#0F172A"), width=2)

        # Draw time text overlay
        elapsed_m = int(self.elapsed_sec) // 60
        elapsed_s = int(self.elapsed_sec) % 60
        total_m = int(self.total_sec) // 60
        total_s = int(self.total_sec) % 60
        time_str = f"{elapsed_m:02d}:{elapsed_s:02d} / {total_m:02d}:{total_s:02d}"

        self.create_text(
            w - 10, h - 8,
            text=time_str,
            anchor="se",
            fill=self.palette.get("text_primary", "#0F172A"),
            font=("Segoe UI", 8, "bold")
        )


class SpeechWorker:
    """The same speech service used by Gradio; UI updates go through a queue."""
    def generate(self, text, language, voice, events, closing, speed=1.0, secondary_voice=None, blend_ratio=0.0, tone="natural"):
        try:
            res = speech_service.synthesize(
                text, voice, language=language, speed=speed,
                progress=lambda message: events.put(("progress", message)),
                cancelled=closing,
                secondary_voice=secondary_voice,
                blend_ratio=blend_ratio,
                tone=tone,
                return_subtitles=True,
            )
            if not closing.is_set():
                events.put(("done", res))
        except speech_service.GenerationCancelled:
            pass
        except Exception as error:
            logger.exception("Speech generation failed")
            if not closing.is_set():
                events.put(("error", error_message(error)))


class YawYawApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Yaw-Yaw — Speech Studio")
        self.root.geometry("1080x760")
        self.root.minsize(920, 700)
        self.audio = None
        self.sample_rate = SAMPLE_RATE
        self.worker = SpeechWorker()
        self.events = queue.Queue()
        self.closing = threading.Event()
        self.busy = False
        self.autoplay = False
        self.playing = False
        self.sounddevice = None
        self.thread = None
        self.voice_var = tk.StringVar(value="af_heart")
        self.lang_var = tk.StringVar(value="American English")
        self.speed_var = tk.DoubleVar(value=1.0)
        self.speed_label = tk.StringVar(value="1.0× · Natural")
        self.character_count = tk.StringVar()
        self.voice_description = tk.StringVar()
        self.voice_trait = tk.StringVar(value=VOICE_TRAITS.get("af_heart", "Expressive & lifelike"))
        self.clip_info = tk.StringVar(value="Your audio will appear here after generation.")
        self.status = tk.StringVar(value="Ready when you are.")
        self.volume_var = tk.DoubleVar(value=100.0)
        self.volume_label = tk.StringVar(value="100%")
        self.stats_info = tk.StringVar(value="")
        self.secondary_voice_var = tk.StringVar(value="af_bella")
        self.blend_enabled_var = tk.BooleanVar(value=False)
        self.blend_ratio_var = tk.DoubleVar(value=0.30)
        self.blend_ratio_label = tk.StringVar(value="70% af_heart + 30% af_bella")
        self.tone_var = tk.StringVar(value="Natural (Studio)")
        self.last_srt = ""
        self.playback_start_time = 0.0
        self.playback_start_sample = 0
        self.current_theme = "light"
        self.history = []
        self.last_generated_text = ""
        ico_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "yaw_yaw.ico")
        if os.path.isfile(ico_file):
            try:
                self.root.iconbitmap(ico_file)
            except Exception:
                pass
        self.build_ui()
        if os.environ.get("HF_HUB_OFFLINE") == "1":
            from kokoro_tts_local import paths
            required = [paths.get_model_dir() / "kokoro-v1_0.pth", paths.get_config_path(), paths.get_voices_dir() / "af_heart.pt"]
            if any(not p.is_file() or p.stat().st_size == 0 for p in required):
                self.status.set("Some voice files are missing. Run setup to prepare offline speech.")
            else:
                self.status.set("Offline mode. Ready to turn your words into speech.")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.root.after(100, self.poll_events)

    def apply_theme(self, theme_name):
        palette = THEMES[theme_name]
        self.root.configure(background=palette["bg"])
        self.root.option_add("*Font", ("Segoe UI", 10))
        self.root.option_add("*TCombobox*Listbox.background", palette["card_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground", palette["text_primary"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", palette["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")

        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure("TFrame", background=palette["bg"])
        style.configure("Card.TFrame", background=palette["card_bg"])
        style.configure("TLabel", background=palette["bg"], foreground=palette["text_primary"])
        style.configure("Card.TLabel", background=palette["card_bg"], foreground=palette["text_primary"])
        style.configure("Muted.TLabel", background=palette["card_bg"], foreground=palette["text_muted"], font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=palette["card_bg"], foreground=palette["text_primary"], font=("Segoe UI", 15, "bold"))
        style.configure("Section.TLabel", background=palette["card_bg"], foreground=palette["text_secondary"], font=("Segoe UI", 9, "bold"))

        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(10, 6),
                        background=palette["button_bg"], foreground=palette["text_primary"], borderwidth=0)
        style.map("TButton",
                  background=[("active", palette["button_hover"]), ("disabled", palette["button_disabled_bg"])],
                  foreground=[("disabled", palette["button_disabled_fg"])])

        style.configure("Primary.TButton", background=palette["accent"], foreground="white",
                        font=("Segoe UI", 10, "bold"), padding=(14, 8), borderwidth=0)
        style.map("Primary.TButton",
                  background=[("disabled", palette["button_disabled_bg"]), ("active", palette["accent_hover"])],
                  foreground=[("disabled", palette["button_disabled_fg"]), ("!disabled", "white")])

        style.configure("Pill.TButton", font=("Segoe UI", 8, "bold"), padding=(6, 3),
                        background=palette["button_bg"], foreground=palette["text_secondary"], borderwidth=0)
        style.map("Pill.TButton",
                  background=[("active", palette["button_hover"])],
                  foreground=[("active", palette["text_primary"])])

        style.configure("TCombobox", padding=6, foreground=palette["text_primary"], fieldbackground=palette["card_bg"], arrowsize=13)
        style.map("TCombobox",
                  fieldbackground=[("readonly", palette["card_bg"])],
                  selectbackground=[("readonly", palette["card_bg"])],
                  selectforeground=[("readonly", palette["text_primary"])])

        style.configure("Horizontal.TScale", background=palette["card_bg"], troughcolor=palette["trough"])
        style.configure("Horizontal.TProgressbar", background=palette["accent"], troughcolor=palette["trough"], borderwidth=0)
        style.configure("TSeparator", background=palette["card_border"])
        style.configure("TCheckbutton", background=palette["card_bg"], foreground=palette["text_primary"], font=("Segoe UI", 9))

        if hasattr(self, "waveform"):
            self.waveform.set_palette(palette)

        if hasattr(self, "text") and isinstance(self.text, tk.Text):
            self.text.configure(
                background=palette["entry_bg"],
                foreground=palette["text_primary"],
                insertbackground=palette["accent"],
                selectbackground=palette["select_bg"],
                selectforeground=palette["text_primary"],
                highlightbackground=palette["entry_border"],
                highlightcolor=palette["accent"],
            )

        if hasattr(self, "header") and isinstance(self.header, tk.Frame):
            self.header.configure(background=palette["header_bg"])
            for child in self.header.winfo_children():
                tag = getattr(child, "_tag", "")
                if tag == "title":
                    child.configure(bg=palette["header_bg"], fg=palette["header_fg"])
                elif tag == "sub":
                    child.configure(bg=palette["header_bg"], fg=palette["header_sub"])
                elif tag == "badge":
                    child.configure(bg=palette["badge_bg"], fg=palette["badge_fg"])
                elif tag == "button":
                    child.configure(bg=palette["badge_bg"], fg=palette["header_fg"],
                                    activebackground=palette["button_hover"], activeforeground="white")

        if hasattr(self, "theme_button"):
            self.theme_button.configure(text="🌙 Dark" if theme_name == "light" else "☀️ Light")

        if hasattr(self, "text") and hasattr(self, "character_count"):
            self.update_text_count()

    def toggle_theme(self):
        self.current_theme = "dark" if self.current_theme == "light" else "light"
        self.apply_theme(self.current_theme)

    def build_ui(self):
        self.apply_theme(self.current_theme)
        palette = THEMES[self.current_theme]

        # Header Bar
        self.header = tk.Frame(self.root, background=palette["header_bg"], padx=24, pady=14)
        self.header.pack(fill="x")

        title_frame = tk.Frame(self.header, background=palette["header_bg"])
        title_frame.pack(side="left")

        title_lbl = tk.Label(title_frame, text="Yaw-Yaw", font=("Segoe UI", 22, "bold"),
                             fg=palette["header_fg"], bg=palette["header_bg"])
        title_lbl._tag = "title"
        title_lbl.pack(side="left")

        sub_lbl = tk.Label(title_frame, text="Gamiton para mag Yaw-Yaw.", font=("Segoe UI", 9, "bold"),
                           fg=palette["header_sub"], bg=palette["header_bg"])
        sub_lbl._tag = "sub"
        sub_lbl.pack(side="left", padx=(18, 0), pady=(6, 0))

        # Header Right Controls
        header_right = tk.Frame(self.header, background=palette["header_bg"])
        header_right.pack(side="right")

        mode = "🔒 100% OFFLINE" if os.environ.get("HF_HUB_OFFLINE") == "1" else "SPEECH STUDIO"
        mode_lbl = tk.Label(header_right, text=mode, bg=palette["badge_bg"], fg=palette["badge_fg"],
                            padx=12, pady=6, font=("Segoe UI", 8, "bold"), relief="flat")
        mode_lbl._tag = "badge"
        mode_lbl.pack(side="right", padx=(8, 0))

        self.theme_button = tk.Button(header_right, text="🌙 Dark", font=("Segoe UI", 8, "bold"),
                                      bg=palette["badge_bg"], fg=palette["header_fg"],
                                      relief="flat", padx=10, pady=5, cursor="hand2",
                                      activebackground=palette["button_hover"], activeforeground="white",
                                      command=self.toggle_theme)
        self.theme_button._tag = "button"
        self.theme_button.pack(side="right", padx=(8, 0))

        shortcuts_btn = tk.Button(header_right, text="⌨ Shortcuts", font=("Segoe UI", 8),
                                  bg=palette["badge_bg"], fg=palette["header_fg"],
                                  relief="flat", padx=8, pady=5, cursor="hand2",
                                  activebackground=palette["button_hover"], activeforeground="white",
                                  command=self.show_shortcuts)
        shortcuts_btn._tag = "button"
        shortcuts_btn.pack(side="right", padx=(8, 0))

        # Main Layout Grid
        main = ttk.Frame(self.root, padding=(22, 16))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        # Left Column: Script Editor Card
        editor = ttk.Frame(main, style="Card.TFrame", padding=(20, 16))
        editor.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(2, weight=1)

        ttk.Label(editor, text="Ibutang ngadi an imo ig papa yawyaw", style="Title.TLabel").grid(row=0, column=0, sticky="w")

        # Quick Insert & Tools Bar
        tools_bar = ttk.Frame(editor, style="Card.TFrame")
        tools_bar.grid(row=1, column=0, sticky="ew", pady=(6, 6))

        self.pause_05_btn = ttk.Button(tools_bar, text="⏱ +0.5s Pause", style="Pill.TButton",
                                       command=lambda: self.insert_text(" [pause 0.5s] "))
        self.pause_05_btn.pack(side="left", padx=(0, 4))

        self.pause_10_btn = ttk.Button(tools_bar, text="⏱ +1.0s Pause", style="Pill.TButton",
                                       command=lambda: self.insert_text(" [pause 1.0s] "))
        self.pause_10_btn.pack(side="left", padx=(0, 4))

        self.speaker_btn = ttk.Button(tools_bar, text="💬 +Speaker", style="Pill.TButton",
                                      command=self.insert_speaker_tag)
        self.speaker_btn.pack(side="left", padx=(0, 4))

        self.dict_btn = ttk.Button(tools_bar, text="📖 Pronunciations", style="Pill.TButton",
                                   command=self.show_pronunciations)
        self.dict_btn.pack(side="left")

        # Editor Text Frame
        text_frame = ttk.Frame(editor, style="Card.TFrame")
        text_frame.grid(row=2, column=0, sticky="nsew")
        self.text = tk.Text(text_frame, height=8, width=36, wrap="word", font=("Segoe UI", 12),
                            background=palette["entry_bg"], foreground=palette["text_primary"],
                            insertbackground=palette["accent"], selectbackground=palette["select_bg"],
                            selectforeground=palette["text_primary"], relief="flat",
                            padx=14, pady=12, spacing1=2, spacing3=6, undo=True,
                            highlightthickness=1, highlightbackground=palette["entry_border"],
                            highlightcolor=palette["accent"])
        scroll = ttk.Scrollbar(text_frame, command=self.text.yview)
        scroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", "Hello pakyu ka i type ngadi an imo ig papa yawyaw.")
        self.text.bind("<Return>", self.on_enter)
        self.text.bind("<Shift-Return>", self.on_shift_enter)
        self.text.bind("<Control-Return>", self.on_enter)
        self.text.bind("<<Modified>>", self.update_text_count)
        self.text.bind("<Control-l>", lambda e: (self.clear_text(), "break")[1])
        self.text.bind("<Control-L>", lambda e: (self.clear_text(), "break")[1])
        self.text.bind("<Control-o>", lambda e: (self.load_text_file(), "break")[1])
        self.text.bind("<Control-O>", lambda e: (self.load_text_file(), "break")[1])
        self.text.bind("<Control-s>", lambda e: (self.save_script_file(), "break")[1])
        self.text.bind("<Control-S>", lambda e: (self.save_script_file(), "break")[1])

        # Editor Footer Toolbar & Counts
        editor_footer = ttk.Frame(editor, style="Card.TFrame")
        editor_footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        self.count_label = CountLabel(editor_footer, textvariable=self.character_count, style="Muted.TLabel")
        self.count_label.pack(side="left")

        self.stats_label = ttk.Label(editor_footer, textvariable=self.stats_info, style="Muted.TLabel")
        self.stats_label.pack(side="left", padx=(12, 0))

        self.clear_button = ttk.Button(editor_footer, text="Clear text", command=self.clear_text)
        self.clear_button.pack(side="right")

        self.copy_button = ttk.Button(editor_footer, text="📋 Copy", command=self.copy_text)
        self.copy_button.pack(side="right", padx=(0, 6))

        self.load_button = ttk.Button(editor_footer, text="📂 Load file", command=self.load_text_file)
        self.load_button.pack(side="right", padx=(0, 6))

        ttk.Label(editor, text="Enter to generate & play · Shift+Enter for a new line · Ctrl+L to clear",
                  style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=(8, 0))

        # Right Column: Voice & Settings Card
        settings = ttk.Frame(main, style="Card.TFrame", padding=(20, 16))
        settings.grid(row=0, column=1, sticky="nsew")

        ttk.Label(settings, text="ACCENT", style="Section.TLabel").pack(anchor="w", pady=(0, 2))
        self.language_box = ttk.Combobox(settings, textvariable=self.lang_var, values=list(LANGUAGES),
                                         state="readonly", width=22)
        self.language_box.pack(fill="x")
        self.language_box.bind("<<ComboboxSelected>>", self.change_language)

        ttk.Label(settings, text="VOICE", style="Section.TLabel").pack(anchor="w", pady=(6, 2))
        self.voice_box = ttk.Combobox(settings, textvariable=self.voice_var, values=voices_for_language("a"),
                                      state="readonly", width=22)
        self.voice_box.pack(fill="x")
        self.voice_box.bind("<<ComboboxSelected>>", self.update_voice_description)

        ttk.Label(settings, textvariable=self.voice_description, style="Muted.TLabel", wraplength=230).pack(anchor="w", pady=(2, 0))
        self.voice_trait_label = ttk.Label(settings, textvariable=self.voice_trait, style="Muted.TLabel",
                                           font=("Segoe UI", 8, "italic"), wraplength=230)
        self.voice_trait_label.pack(anchor="w", pady=(1, 0))

        # Voice Blending Container
        self.blend_container = ttk.Frame(settings, style="Card.TFrame")
        self.blend_container.pack(fill="x", pady=(4, 0))

        self.blend_toggle = ttk.Checkbutton(
            self.blend_container,
            text="🎛️ Blend 2 Voices",
            variable=self.blend_enabled_var,
            command=self.toggle_blend_ui,
            style="TCheckbutton"
        )
        self.blend_toggle.pack(anchor="w")

        self.blend_frame = ttk.Frame(self.blend_container, style="Card.TFrame")
        ttk.Label(self.blend_frame, text="SECONDARY VOICE", style="Section.TLabel").pack(anchor="w", pady=(3, 1))
        self.secondary_voice_box = ttk.Combobox(
            self.blend_frame,
            textvariable=self.secondary_voice_var,
            values=voices_for_language("a"),
            state="readonly",
            width=22
        )
        self.secondary_voice_box.pack(fill="x")
        self.secondary_voice_box.bind("<<ComboboxSelected>>", self.update_blend_label)

        ttk.Label(self.blend_frame, textvariable=self.blend_ratio_label, style="Muted.TLabel",
                  font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(2, 1))
        self.blend_scale = ttk.Scale(
            self.blend_frame,
            from_=0.0,
            to=1.0,
            variable=self.blend_ratio_var,
            command=self.update_blend_label
        )
        self.blend_scale.pack(fill="x", pady=(0, 2))

        # Tone & Acoustics (EQ)
        ttk.Label(settings, text="TONE & ACOUSTICS", style="Section.TLabel").pack(anchor="w", pady=(6, 2))
        self.tone_box = ttk.Combobox(
            settings,
            textvariable=self.tone_var,
            values=["Natural (Studio)", "Warm & Radio", "Crisp & Bright", "Broadcast Studio"],
            state="readonly",
            width=22
        )
        self.tone_box.pack(fill="x", pady=(0, 4))

        ttk.Separator(settings).pack(fill="x", pady=6)

        ttk.Label(settings, text="SPEAKING SPEED", style="Section.TLabel").pack(anchor="w")
        ttk.Label(settings, textvariable=self.speed_label, style="Card.TLabel",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(2, 2))
        self.speed_scale = ttk.Scale(settings, from_=0.5, to=2.0, variable=self.speed_var, command=self.update_speed)
        self.speed_scale.pack(fill="x")

        # Speed Quick Presets
        speed_btn_row = ttk.Frame(settings, style="Card.TFrame")
        speed_btn_row.pack(fill="x", pady=(2, 8))
        for spd_val, spd_txt in [(0.8, "0.8×"), (1.0, "1.0×"), (1.2, "1.2×"), (1.5, "1.5×")]:
            btn = ttk.Button(speed_btn_row, text=spd_txt, style="Pill.TButton",
                             command=lambda s=spd_val: self.set_speed(s), width=4)
            btn.pack(side="left", padx=(0, 4), expand=True, fill="x")

        self.generate_play_button = ttk.Button(settings, text="Generate & play", style="Primary.TButton",
                                               command=self.generate_and_play)
        self.generate_play_button.pack(fill="x", pady=(2, 4))

        self.generate_button = ttk.Button(settings, text="Generate audio only", command=self.generate_audio)
        self.generate_button.pack(fill="x")

        # Bottom Row: Playback & Export Studio
        playback = ttk.Frame(main, style="Card.TFrame", padding=(16, 10))
        playback.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        # Audio Waveform Display Canvas
        self.waveform = AudioWaveformCanvas(playback, height=36, on_seek=self.seek_audio)
        self.waveform.pack(fill="x", expand=True, pady=(0, 6))

        # Playback Status & Volume Bar
        info_row = ttk.Frame(playback, style="Card.TFrame")
        info_row.pack(fill="x", pady=(0, 6))

        info_left = ttk.Frame(info_row, style="Card.TFrame")
        info_left.pack(side="left", fill="x", expand=True)
        ttk.Label(info_left, text="Your latest audio:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Label(info_left, textvariable=self.clip_info, style="Muted.TLabel").pack(side="left", padx=(6, 0))

        # Volume Slider
        vol_frame = ttk.Frame(info_row, style="Card.TFrame")
        vol_frame.pack(side="right")
        ttk.Label(vol_frame, text="🔊", style="Card.TLabel").pack(side="left", padx=(0, 4))
        self.volume_scale = ttk.Scale(vol_frame, from_=0, to=100, variable=self.volume_var,
                                      command=self.update_volume, length=70)
        self.volume_scale.pack(side="left", padx=(0, 4))
        self.volume_pct_label = ttk.Label(vol_frame, textvariable=self.volume_label,
                                          style="Muted.TLabel", width=4)
        self.volume_pct_label.pack(side="left")

        # Action Buttons Row
        buttons_row = ttk.Frame(playback, style="Card.TFrame")
        buttons_row.pack(fill="x")

        self.play_button = ttk.Button(buttons_row, text="▶ Play", command=self.play_audio, state="disabled")
        self.stop_button = ttk.Button(buttons_row, text="⏹ Stop", command=self.stop_playback, state="disabled")
        self.save_button = ttk.Button(buttons_row, text="Save WAV", command=self.save_wav, state="disabled")
        self.save_mp3_button = ttk.Button(buttons_row, text="Save MP3", command=self.save_mp3, state="disabled")
        self.save_flac_button = ttk.Button(buttons_row, text="Save FLAC", command=self.save_flac, state="disabled")
        self.save_srt_button = ttk.Button(buttons_row, text="Subtitles (.srt)", command=self.save_subtitles, state="disabled")
        self.history_button = ttk.Button(buttons_row, text="🕒 History (0)", command=self.show_history)

        for button in (self.play_button, self.stop_button, self.save_button, self.save_mp3_button,
                       self.save_flac_button, self.save_srt_button, self.history_button):
            button.pack(side="left", padx=(0, 6))

        # Progress and Status
        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 6))

        self.status_label = ttk.Label(main, textvariable=self.status, wraplength=850)
        self.status_label.grid(row=3, column=0, columnspan=2, sticky="w")

        self.update_voice_description()
        self.update_text_count()

    def update_text_count(self, event=None):
        if not hasattr(self, "text") or not hasattr(self, "character_count") or not hasattr(self, "count_label"):
            return
        raw_text = self.text.get("1.0", "end-1c")
        count = len(raw_text.strip())
        limit = int(speech_service.MAX_TEXT_LENGTH * min(1.0, round(self.speed_var.get(), 1)))
        self.character_count.set(f"{count:,} / {limit:,} characters")
        palette = THEMES.get(getattr(self, "current_theme", "light"), THEMES["light"])
        self.count_label.configure(foreground="#AF3D32" if count > limit else palette["text_muted"])

        words = len(raw_text.split())
        spd = max(0.5, round(self.speed_var.get(), 1))
        est_sec = (words / 2.5) / spd if words > 0 else 0.0
        if hasattr(self, "stats_info"):
            self.stats_info.set(f"{words} words · ~{est_sec:.1f}s est.")

        if self.text.edit_modified():
            self.text.edit_modified(False)

    def update_speed(self, value=None):
        speed = round(self.speed_var.get(), 1)
        description = "Natural" if speed == 1 else ("Relaxed" if speed < 1 else "Upbeat")
        self.speed_label.set(f"{speed:.1f}× · {description}")
        self.update_text_count()

    def set_speed(self, speed_value):
        if not self.busy:
            self.speed_var.set(speed_value)
            self.update_speed()

    def update_voice_description(self, event=None):
        voice = self.voice_var.get()
        name = voice.split("_", 1)[-1].replace("_", " ").title()
        kind = "Female" if voice[1:2] == "f" else "Male"
        self.voice_description.set(f"{name} · {kind} voice")
        if hasattr(self, "voice_trait"):
            self.voice_trait.set(VOICE_TRAITS.get(voice, f"{kind} voice model"))

    def clear_text(self):
        if not self.busy:
            self.text.delete("1.0", "end")
            self.text.focus_set()
            self.update_text_count()

    def copy_text(self):
        content = self.text.get("1.0", "end-1c")
        if content.strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.status.set("Script copied to clipboard.")

    def load_text_file(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Open Script File",
            filetypes=[("Text files", "*.txt;*.md"), ("All files", "*.*")]
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                self.text.delete("1.0", "end")
                self.text.insert("1.0", content)
                self.update_text_count()
                self.status.set(f"Loaded: {os.path.basename(path)}")
            except Exception as e:
                self.show_error("Could not open file", e)

    def save_script_file(self):
        content = self.text.get("1.0", "end-1c").strip()
        if not content:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save Script File",
            initialfile="yaw-yaw-script.txt",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")]
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.status.set(f"Script saved: {os.path.basename(path)}")
            except Exception as e:
                self.show_error("Could not save script", e)

    def update_volume(self, val=None):
        v = int(round(self.volume_var.get()))
        self.volume_label.set(f"{v}%")

    def change_language(self, event=None):
        voices = voices_for_language(LANGUAGES[self.lang_var.get()])
        self.voice_box.configure(values=voices)
        if self.voice_var.get() not in voices:
            self.voice_var.set(voices[0])
        if hasattr(self, "secondary_voice_box"):
            self.secondary_voice_box.configure(values=voices)
            if self.secondary_voice_var.get() not in voices:
                self.secondary_voice_var.set(voices[-1] if len(voices) > 1 else voices[0])
        self.update_voice_description()
        self.update_blend_label()

    def toggle_blend_ui(self):
        if hasattr(self, "blend_enabled_var") and self.blend_enabled_var.get():
            if hasattr(self, "blend_frame"):
                self.blend_frame.pack(fill="x", pady=(2, 4))
            self.update_blend_label()
        else:
            if hasattr(self, "blend_frame"):
                self.blend_frame.pack_forget()

    def update_blend_label(self, val=None):
        if not hasattr(self, "blend_ratio_label"):
            return
        ratio = self.blend_ratio_var.get()
        p1 = int(round((1.0 - ratio) * 100))
        p2 = int(round(ratio * 100))
        v1 = self.voice_var.get()
        v2 = self.secondary_voice_var.get() if hasattr(self, "secondary_voice_var") else "voice"
        self.blend_ratio_label.set(f"{p1}% {v1} + {p2}% {v2}")

    def get_tone_internal_name(self):
        if not hasattr(self, "tone_var"):
            return "natural"
        val = self.tone_var.get()
        if "Warm" in val:
            return "warm"
        if "Crisp" in val:
            return "crisp"
        if "Broadcast" in val:
            return "broadcast"
        return "natural"

    def insert_text(self, string_to_insert):
        if not self.busy:
            self.text.insert(tk.INSERT, string_to_insert)
            self.text.focus_set()
            self.update_text_count()

    def insert_speaker_tag(self):
        if not self.busy:
            cur_voice = self.voice_var.get()
            self.insert_text(f"\n[{cur_voice}]: ")

    def show_pronunciations(self):
        palette = THEMES[self.current_theme]
        win = tk.Toplevel(self.root)
        win.title("📖 Pronunciation Dictionary")
        win.geometry("520x430")
        win.minsize(440, 350)
        win.configure(background=palette["bg"])
        win.transient(self.root)

        header = tk.Frame(win, background=palette["header_bg"], padx=16, pady=12)
        header.pack(fill="x")
        tk.Label(header, text="Custom Pronunciation Dictionary", font=("Segoe UI", 12, "bold"),
                 fg=palette["header_fg"], bg=palette["header_bg"]).pack(side="left")

        body = ttk.Frame(win, padding=14)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Replace difficult words or acronyms with phonetic spellings before speech generation.",
                  style="Muted.TLabel", wraplength=460).pack(anchor="w", pady=(0, 8))

        list_frame = ttk.Frame(body)
        list_frame.pack(fill="both", expand=True, pady=(0, 10))

        scroll = ttk.Scrollbar(list_frame)
        scroll.pack(side="right", fill="y")

        items_list = tk.Listbox(
            list_frame,
            yscrollcommand=scroll.set,
            background=palette["entry_bg"],
            foreground=palette["text_primary"],
            selectbackground=palette["accent"],
            selectforeground="#FFFFFF",
            font=("Segoe UI", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=palette["entry_border"]
        )
        items_list.pack(side="left", fill="both", expand=True)
        scroll.config(command=items_list.yview)

        current_dict = speech_service.load_pronunciations()

        def refresh_list():
            items_list.delete(0, tk.END)
            for w, r in sorted(current_dict.items()):
                items_list.insert(tk.END, f"{w}  ➔  {r}")

        refresh_list()

        inp_frame = ttk.Frame(body)
        inp_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(inp_frame, text="Word:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        word_entry = ttk.Entry(inp_frame, width=16)
        word_entry.grid(row=0, column=1, sticky="w", padx=(0, 10))

        ttk.Label(inp_frame, text="Pronounce as:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        pron_entry = ttk.Entry(inp_frame, width=20)
        pron_entry.grid(row=0, column=3, sticky="ew")
        inp_frame.columnconfigure(3, weight=1)

        def on_select(event):
            sel = items_list.curselection()
            if sel:
                line = items_list.get(sel[0])
                if "  ➔  " in line:
                    w, r = line.split("  ➔  ", 1)
                    word_entry.delete(0, tk.END)
                    word_entry.insert(0, w.strip())
                    pron_entry.delete(0, tk.END)
                    pron_entry.insert(0, r.strip())

        items_list.bind("<<ListboxSelect>>", on_select)

        btn_frame = ttk.Frame(body)
        btn_frame.pack(fill="x")

        def add_entry():
            w = word_entry.get().strip()
            r = pron_entry.get().strip()
            if not w or not r:
                messagebox.showwarning("Input missing", "Please enter both word and replacement.", parent=win)
                return
            current_dict[w] = r
            speech_service.save_pronunciations(current_dict)
            refresh_list()
            word_entry.delete(0, tk.END)
            pron_entry.delete(0, tk.END)
            self.status.set(f"Added pronunciation rule: '{w}' -> '{r}'")

        def delete_entry():
            sel = items_list.curselection()
            if not sel:
                return
            line = items_list.get(sel[0])
            if "  ➔  " in line:
                w = line.split("  ➔  ", 1)[0].strip()
                if w in current_dict:
                    del current_dict[w]
                    speech_service.save_pronunciations(current_dict)
                    refresh_list()
                    word_entry.delete(0, tk.END)
                    pron_entry.delete(0, tk.END)
                    self.status.set(f"Removed pronunciation rule: '{w}'")

        ttk.Button(btn_frame, text="➕ Add / Update", style="Primary.TButton", command=add_entry).pack(side="left")
        ttk.Button(btn_frame, text="🗑 Delete", command=delete_entry).pack(side="left", padx=(8, 0))
        ttk.Button(btn_frame, text="Close", command=win.destroy).pack(side="right")

    def on_enter(self, event=None):
        self.generate_and_play()
        return "break"

    def on_shift_enter(self, event=None):
        if not self.busy:
            self.text.insert(tk.INSERT, "\n")
        return "break"

    def set_busy(self, busy):
        self.busy = busy
        for button in (self.generate_button, self.generate_play_button):
            button.configure(state="disabled" if busy else "normal")
        for box in (self.language_box, self.voice_box):
            box.configure(state="disabled" if busy else "readonly")
        self.text.configure(state="disabled" if busy else "normal")
        self.speed_scale.configure(state="disabled" if busy else "normal")
        self.clear_button.configure(state="disabled" if busy else "normal")
        if hasattr(self, "copy_button"):
            self.copy_button.configure(state="disabled" if busy else "normal")
        if hasattr(self, "load_button"):
            self.load_button.configure(state="disabled" if busy else "normal")
        if hasattr(self, "blend_toggle"):
            self.blend_toggle.configure(state="disabled" if busy else "normal")
        if hasattr(self, "secondary_voice_box"):
            self.secondary_voice_box.configure(state="disabled" if busy else "readonly")
        if hasattr(self, "blend_scale"):
            self.blend_scale.configure(state="disabled" if busy else "normal")
        if hasattr(self, "tone_box"):
            self.tone_box.configure(state="disabled" if busy else "readonly")
        for btn_name in ("pause_05_btn", "pause_10_btn", "speaker_btn", "dict_btn"):
            if hasattr(self, btn_name):
                getattr(self, btn_name).configure(state="disabled" if busy else "normal")
        available = not busy and self.audio is not None
        for button in (self.play_button, self.save_button):
            button.configure(state="normal" if available else "disabled")
        if hasattr(self, "save_mp3_button"):
            self.save_mp3_button.configure(state="normal" if available else "disabled")
        if hasattr(self, "save_flac_button"):
            self.save_flac_button.configure(state="normal" if available else "disabled")
        if hasattr(self, "save_srt_button"):
            self.save_srt_button.configure(state="normal" if (available and bool(getattr(self, "last_srt", ""))) else "disabled")
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def generate_and_play(self):
        self.start_generation(autoplay=True)

    def generate_audio(self):
        self.start_generation(autoplay=False)

    def start_generation(self, autoplay=False):
        if self.busy or self.closing.is_set():
            return False
        text = self.text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("No text", "Please enter text first.", parent=self.root)
            return False
        language = LANGUAGES[self.lang_var.get()]
        voice = self.voice_var.get()
        if voice not in voices_for_language(language):
            messagebox.showerror("Invalid voice", "Select a voice matching the language.", parent=self.root)
            return False
        speed = round(self.speed_var.get(), 1)
        try:
            speech_service.validate_request(text, speed)
        except ValueError as error:
            messagebox.showwarning("Check your text", str(error), parent=self.root)
            return False
        self.last_generated_text = text
        self.stop_playback(update_status=False)
        self.autoplay = autoplay
        self.set_busy(True)
        self.status.set("Preparing speech generation...")

        blend_on = bool(getattr(self, "blend_enabled_var", None) and self.blend_enabled_var.get())
        sec_voice = self.secondary_voice_var.get() if (blend_on and hasattr(self, "secondary_voice_var")) else None
        blend_rat = float(self.blend_ratio_var.get()) if (blend_on and hasattr(self, "blend_ratio_var")) else 0.0
        tone_val = self.get_tone_internal_name() if hasattr(self, "get_tone_internal_name") else "natural"

        try:
            self.thread = threading.Thread(
                target=self.worker.generate,
                args=(text, language, voice, self.events, self.closing),
                kwargs={
                    "speed": speed,
                    "secondary_voice": sec_voice,
                    "blend_ratio": blend_rat,
                    "tone": tone_val,
                },
                daemon=True
            )
            self.thread.start()
        except Exception as error:
            self.set_busy(False)
            self.show_error("Could not start generation", error)
            return False
        return True

    def poll_events(self):
        if self.closing.is_set():
            return
        # Bounded draining leaves time for other UI events even for long input.
        for _ in range(100):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.status.set(value)
            elif kind == "done":
                if isinstance(value, tuple) and len(value) == 2:
                    self.audio, self.last_srt = value
                else:
                    self.audio = value
                    self.last_srt = ""
                duration = len(self.audio) / self.sample_rate
                self.clip_info.set(f"{duration:.1f} seconds · Ready to play or save")
                if hasattr(self, "waveform"):
                    self.waveform.set_audio(self.audio, self.sample_rate)
                if hasattr(self, "history"):
                    voice_name = getattr(self, "voice_var", None)
                    v_str = voice_name.get() if voice_name else "voice"
                    snippet = self.last_generated_text[:50] + ("..." if len(self.last_generated_text) > 50 else "")
                    self.history.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "voice": v_str,
                        "text": snippet,
                        "full_text": self.last_generated_text,
                        "duration": f"{duration:.1f}s",
                        "audio": self.audio,
                        "srt": self.last_srt,
                    })
                    if hasattr(self, "history_button"):
                        self.history_button.configure(text=f"🕒 History ({len(self.history)})")
                self.set_busy(False)
                self.status.set("Audio generated. Ready to play or save.")
                if self.autoplay:
                    self.play_audio()
            elif kind == "error":
                self.set_busy(False)
                self.status.set("Generation failed. Previous audio, if any, is still available.")
                messagebox.showerror("Generation failed", value, parent=self.root)
        if self.playing:
            try:
                if not self.sounddevice.get_stream().active:
                    self.playing = False
                    self.stop_button.configure(state="disabled")
                    self.status.set("Playback finished.")
                    if hasattr(self, "waveform") and self.audio is not None and len(self.audio) > 0:
                        self.waveform.set_progress(1.0, len(self.audio) / self.sample_rate)
                else:
                    if hasattr(self, "waveform") and self.audio is not None and len(self.audio) > 0:
                        total_dur = len(self.audio) / self.sample_rate
                        elapsed = (time.time() - self.playback_start_time) + (self.playback_start_sample / self.sample_rate)
                        frac = min(1.0, max(0.0, elapsed / total_dur))
                        self.waveform.set_progress(frac, elapsed)
            except Exception as error:
                self.playing = False
                self.stop_button.configure(state="disabled")
                self.show_error("Playback failed", error)
        if not self.closing.is_set():
            self.poll_id = self.root.after(100, self.poll_events)

    def show_error(self, title, error):
        self.status.set(title)
        messagebox.showerror(title, error_message(error), parent=self.root)

    def play_audio(self, audio_data=None, start_sample=0):
        target_audio = audio_data if audio_data is not None else self.audio
        if target_audio is None or self.busy or self.closing.is_set():
            return
        try:
            if self.sounddevice is None:
                import sounddevice
                self.sounddevice = sounddevice

            start_sample = max(0, min(int(start_sample), len(target_audio) - 1)) if len(target_audio) > 0 else 0
            playable_slice = target_audio[start_sample:]
            if len(playable_slice) == 0:
                playable_slice = target_audio
                start_sample = 0

            vol = getattr(self, "volume_var", None)
            factor = 1.0
            if vol is not None:
                factor = max(0.0, min(1.0, vol.get() / 100.0))
            if factor >= 0.999:
                playable = playable_slice
            else:
                import numpy as np
                playable = (playable_slice * factor).astype(np.float32)

            self.sounddevice.play(playable, self.sample_rate)
            self.playing = True
            self.playback_start_time = time.time()
            self.playback_start_sample = start_sample
            self.stop_button.configure(state="normal")
            self.status.set("Playing...")
        except Exception as error:
            self.playing = False
            self.stop_button.configure(state="disabled")
            self.show_error("Could not play audio; check your output device", error)

    def seek_audio(self, frac):
        if self.audio is None or len(self.audio) == 0 or self.busy:
            return
        sample = int(float(frac) * len(self.audio))
        self.play_audio(start_sample=sample)

    def stop_playback(self, update_status=True):
        try:
            if self.sounddevice is not None:
                self.sounddevice.stop()
        except Exception as error:
            if not self.closing.is_set():
                self.show_error("Could not stop playback", error)
            return
        self.playing = False
        self.stop_button.configure(state="disabled")
        if hasattr(self, "waveform") and self.audio is not None and len(self.audio) > 0:
            self.waveform.set_progress(0.0, 0.0)
        if update_status and not self.busy:
            self.status.set("Playback stopped.")

    def save_wav(self, audio_data=None):
        target_audio = audio_data if audio_data is not None else self.audio
        if target_audio is None or self.busy:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            initialfile="yaw-yaw-speech.wav",
            defaultextension=".wav",
            filetypes=[("WAV files", "*.wav")]
        )
        if not path:
            return
        try:
            import soundfile
            soundfile.write(path, target_audio, self.sample_rate)
            self.status.set(f"Saved: {path}")
        except Exception as error:
            self.show_error("Could not save WAV; check the destination", error)

    def save_mp3(self, audio_data=None):
        target_audio = audio_data if audio_data is not None else self.audio
        if target_audio is None or self.busy:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            initialfile="yaw-yaw-speech.mp3",
            defaultextension=".mp3",
            filetypes=[("MP3 files", "*.mp3")]
        )
        if not path:
            return
        try:
            import soundfile
            try:
                soundfile.write(path, target_audio, self.sample_rate, format="MP3")
            except Exception:
                import io
                from pydub import AudioSegment
                buf = io.BytesIO()
                soundfile.write(buf, target_audio, self.sample_rate, format="WAV")
                buf.seek(0)
                segment = AudioSegment.from_wav(buf)
                segment.export(path, format="mp3", bitrate="192k")
            self.status.set(f"Saved MP3: {path}")
        except Exception as error:
            self.show_error("Could not save MP3; ensure FFmpeg is available or save as WAV", error)

    def save_flac(self, audio_data=None):
        target_audio = audio_data if audio_data is not None else self.audio
        if target_audio is None or self.busy:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            initialfile="yaw-yaw-speech.flac",
            defaultextension=".flac",
            filetypes=[("FLAC Lossless Audio", "*.flac")]
        )
        if not path:
            return
        try:
            import soundfile
            soundfile.write(path, target_audio, self.sample_rate, format="FLAC")
            self.status.set(f"Saved FLAC: {path}")
        except Exception as error:
            self.show_error("Could not save FLAC; check destination", error)

    def save_subtitles(self):
        if not getattr(self, "last_srt", ""):
            messagebox.showinfo("Subtitles", "No subtitle timestamps available for current speech.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            initialfile="yaw-yaw-speech.srt",
            defaultextension=".srt",
            filetypes=[("SRT Subtitles", "*.srt"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.last_srt)
            self.status.set(f"Saved subtitles: {path}")
        except Exception as error:
            self.show_error("Could not save subtitles", error)

    def show_history(self):
        if not hasattr(self, "history") or not self.history:
            messagebox.showinfo("History", "No speech has been generated in this session yet.", parent=self.root)
            return

        palette = THEMES[self.current_theme]
        win = tk.Toplevel(self.root)
        win.title("Recent Speech Takes")
        win.geometry("560x420")
        win.minsize(460, 320)
        win.configure(background=palette["bg"])

        header_frame = tk.Frame(win, background=palette["header_bg"], padx=16, pady=12)
        header_frame.pack(fill="x")
        tk.Label(header_frame, text="Recent Generation History", font=("Segoe UI", 12, "bold"),
                 fg=palette["header_fg"], bg=palette["header_bg"]).pack(side="left")

        list_container = ttk.Frame(win, padding=12)
        list_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(list_container, background=palette["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for idx, take in enumerate(reversed(self.history)):
            card = ttk.Frame(scrollable_frame, style="Card.TFrame", padding=(12, 8))
            card.pack(fill="x", expand=True, pady=4, padx=2)

            info_line = f"[{take['time']}] {take['voice']} · {take['duration']}"
            ttk.Label(card, text=info_line, style="Section.TLabel").pack(anchor="w")
            ttk.Label(card, text=f'"{take["text"]}"', style="Muted.TLabel", wraplength=380).pack(anchor="w", pady=(2, 6))

            btn_row = ttk.Frame(card, style="Card.TFrame")
            btn_row.pack(anchor="w")

            ttk.Button(btn_row, text="▶ Play", style="Pill.TButton",
                       command=lambda t=take["audio"]: self.play_audio(t)).pack(side="left", padx=(0, 4))
            ttk.Button(btn_row, text="💾 Save WAV", style="Pill.TButton",
                       command=lambda t=take["audio"]: self.save_wav(t)).pack(side="left", padx=(0, 4))
            ttk.Button(btn_row, text="📝 Use Text", style="Pill.TButton",
                       command=lambda txt=take["full_text"]: self._restore_text(txt, win)).pack(side="left")

    def _restore_text(self, text, window):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.update_text_count()
        window.destroy()
        self.status.set("Restored text from history.")

    def show_shortcuts(self):
        shortcuts = (
            "Keyboard Shortcuts:\n\n"
            "• Enter or Ctrl+Enter: Generate speech & play\n"
            "• Shift+Enter: Insert a new line in script\n"
            "• Ctrl+L: Clear script text\n"
            "• Ctrl+O: Open and load a text file\n"
            "• Ctrl+S: Save current script to file\n"
        )
        messagebox.showinfo("Shortcuts & Tips", shortcuts, parent=self.root)

    def close(self):
        if self.closing.is_set():
            return
        self.closing.set()
        # Do not join a potentially downloading/generating worker on the UI thread.
        self.stop_playback(update_status=False)
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


# Compatibility for existing scripts importing the original class name.
KokoroDesktopApp = YawYawApp


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        raise SystemExit("This desktop update requires Python 3.10 or newer.")
    logging.basicConfig(level=logging.INFO)
    root = tk.Tk()
    app = YawYawApp(root)
    root.mainloop()

