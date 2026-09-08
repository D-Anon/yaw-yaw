import json
import os
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np

import desktop_app as app
from kokoro_tts_local import speech_service as service


class AdvancedSpeechFeaturesTests(unittest.TestCase):
    def test_parse_pause_segments(self):
        text = "Hello [pause 0.5s] world! [pause 1200ms] Have a break [pause 2s]."
        segments = service.parse_pause_segments(text)
        self.assertEqual(len(segments), 7)
        self.assertEqual(segments[0], ("speech", "Hello"))
        self.assertEqual(segments[1], ("pause", 0.5))
        self.assertEqual(segments[2], ("speech", "world!"))
        self.assertEqual(segments[3], ("pause", 1.2))
        self.assertEqual(segments[4], ("speech", "Have a break"))
        self.assertEqual(segments[5], ("pause", 2.0))
        self.assertEqual(segments[6], ("speech", "."))

    def test_parse_dialogue_brackets_and_colons(self):
        script = """[af_heart]: Welcome to the studio!
[bm_george]: Thanks, glad to be here.
[af_bella] Let's begin."""
        dialogue = service.parse_dialogue(script, default_voice="af_heart")
        self.assertEqual(len(dialogue), 3)
        self.assertEqual(dialogue[0], ("af_heart", "Welcome to the studio!"))
        self.assertEqual(dialogue[1], ("bm_george", "Thanks, glad to be here."))
        self.assertEqual(dialogue[2], ("af_bella", "Let's begin."))

    def test_parse_dialogue_plain_text(self):
        script = "This is a simple one-character script without any speaker tags."
        dialogue = service.parse_dialogue(script, default_voice="af_heart")
        self.assertIsNone(dialogue)

    def test_pronunciation_dictionary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dict_file = Path(tmpdir) / "pronunciations.json"
            test_dict = {"LLM": "Large Language Model", "Yaw-Yaw": "Yow-Yow"}
            with patch.object(service, "get_pronunciations_path", return_value=dict_file):
                service.save_pronunciations(test_dict)
                loaded = service.load_pronunciations()
                self.assertEqual(loaded, test_dict)

                replaced = service.apply_pronunciations("Testing the LLM with Yaw-Yaw.")
                self.assertEqual(replaced, "Testing the Large Language Model with Yow-Yow.")

    def test_tone_shaping_filters(self):
        audio = np.sin(np.linspace(0, 100 * np.pi, 24000)).astype(np.float32)
        for tone in ("natural", "warm", "warmth", "crisp", "clarity", "broadcast"):
            filtered = service.apply_tone_shaping(audio, tone=tone)
            self.assertEqual(filtered.dtype, np.float32)
            self.assertEqual(len(filtered), len(audio))
            self.assertTrue(np.all(np.isfinite(filtered)))
            self.assertTrue(np.max(np.abs(filtered)) <= 1.0)

    def test_generate_subtitles_srt(self):
        subs = [
            (0.0, 1.45, "Hello and welcome!"),
            (1.60, 3.20, "This is synchronized speech.")
        ]
        srt = service.generate_subtitles_srt(subs)
        self.assertIn("00:00:00,000 --> 00:00:01,450", srt)
        self.assertIn("Hello and welcome!", srt)
        self.assertIn("00:00:01,600 --> 00:00:03,200", srt)
        self.assertIn("This is synchronized speech.", srt)

    def test_synthesize_with_dialogue_pause_and_subtitles(self):
        script = "[af_heart]: Hello! [pause 0.5s] How are you?\n[af_bella]: I am doing well."
        pipeline_mock = Mock()
        def dummy_iter(text, voice, speed=1.0, split_pattern=r'\n+'):
            yield None, None, np.ones(2400, dtype=np.float32) * 0.1
        pipeline_mock.iter_speech.side_effect = dummy_iter

        with patch.object(service, "get_pipeline_for_voice", return_value=pipeline_mock), \
             patch("kokoro_tts_local.models.get_safe_voice_path", return_value=Path("dummy.pt")):
            audio, srt = service.synthesize(
                script,
                voice="af_heart",
                return_subtitles=True,
                tone="crisp"
            )
            self.assertIsInstance(audio, np.ndarray)
            self.assertEqual(audio.dtype, np.float32)
            self.assertTrue(len(audio) > 0)
            self.assertIn("-->", srt)
            self.assertIn("Hello!", srt)


class DesktopAppFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.ui = app.KokoroDesktopApp.__new__(app.KokoroDesktopApp)
        for name in ("root", "status", "text", "voice_box", "language_box", "generate_button",
                     "generate_play_button", "play_button", "stop_button", "save_button",
                     "save_mp3_button", "save_flac_button", "save_srt_button", "progress",
                     "sounddevice", "speed_scale", "clear_button", "clip_info",
                     "voice_description", "blend_toggle", "secondary_voice_box",
                     "blend_scale", "tone_box", "waveform"):
            setattr(self.ui, name, Mock())
        self.ui.lang_var = Mock(get=Mock(return_value="American English"))
        self.ui.voice_var = Mock(get=Mock(return_value="af_heart"))
        self.ui.secondary_voice_var = Mock(get=Mock(return_value="af_bella"))
        self.ui.blend_enabled_var = Mock(get=Mock(return_value=True))
        self.ui.blend_ratio_var = Mock(get=Mock(return_value=0.35))
        self.ui.blend_ratio_label = Mock()
        self.ui.tone_var = Mock(get=Mock(return_value="Crisp & Bright"))
        self.ui.speed_var = Mock(get=Mock(return_value=1.1))
        self.ui.text.get.return_value = "Test speech"
        self.ui.worker = Mock()
        self.ui.events = queue.Queue()
        self.ui.closing = threading.Event()
        self.ui.busy = False
        self.ui.playing = False
        self.ui.autoplay = False
        self.ui.audio = np.ones(2400, dtype=np.float32)
        self.ui.sample_rate = 24000
        self.ui.poll_id = "poll"

    def test_tone_extraction(self):
        self.ui.tone_var.get.return_value = "Warm & Radio"
        self.assertEqual(self.ui.get_tone_internal_name(), "warm")
        self.ui.tone_var.get.return_value = "Crisp & Bright"
        self.assertEqual(self.ui.get_tone_internal_name(), "crisp")
        self.ui.tone_var.get.return_value = "Broadcast Studio"
        self.assertEqual(self.ui.get_tone_internal_name(), "broadcast")
        self.ui.tone_var.get.return_value = "Natural (Studio)"
        self.assertEqual(self.ui.get_tone_internal_name(), "natural")

    def test_update_blend_label(self):
        self.ui.update_blend_label()
        self.ui.blend_ratio_label.set.assert_called_with("65% af_heart + 35% af_bella")

    def test_start_generation_passes_blending_and_tone(self):
        self.assertTrue(self.ui.start_generation())
        self.ui.thread.join(timeout=2)
        self.ui.worker.generate.assert_called_once()
        kwargs = self.ui.worker.generate.call_args.kwargs
        self.assertEqual(kwargs["speed"], 1.1)
        self.assertEqual(kwargs["secondary_voice"], "af_bella")
        self.assertAlmostEqual(kwargs["blend_ratio"], 0.35)
        self.assertEqual(kwargs["tone"], "crisp")

    def test_poll_events_handles_subtitles_tuple(self):
        self.ui.busy = True
        fake_audio = np.ones(12000, dtype=np.float32)
        fake_srt = "1\n00:00:00,000 --> 00:00:00,500\nHello"
        self.ui.events.put(("done", (fake_audio, fake_srt)))
        self.ui.sounddevice.get_stream.return_value.active = True
        self.ui.poll_events()
        self.assertFalse(self.ui.busy)
        np.testing.assert_array_equal(self.ui.audio, fake_audio)
        self.assertEqual(self.ui.last_srt, fake_srt)
        self.ui.waveform.set_audio.assert_called_once_with(fake_audio, 24000)

    def test_save_flac(self):
        soundfile = Mock()
        with patch.dict("sys.modules", {"soundfile": soundfile}), \
             patch.object(app.filedialog, "asksaveasfilename", return_value="out.flac"):
            self.ui.save_flac()
            soundfile.write.assert_called_once_with("out.flac", self.ui.audio, 24000, format="FLAC")

    def test_save_subtitles(self):
        self.ui.last_srt = "1\n00:00:00,000 --> 00:00:01,000\nHello"
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "test.srt")
            with patch.object(app.filedialog, "asksaveasfilename", return_value=out_file):
                self.ui.save_subtitles()
                self.assertTrue(os.path.isfile(out_file))
                with open(out_file, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read(), self.ui.last_srt)


if __name__ == "__main__":
    unittest.main()
