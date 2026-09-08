import tempfile
import threading
import types
import unittest
import queue
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

import desktop_app
from kokoro_tts_local import mms_engine, speech_service


class LanguagePackTests(unittest.TestCase):
    def test_all_philippine_languages_have_one_seamless_voice(self):
        expected = {"tgl", "ceb", "ilo", "hil", "war"}
        self.assertEqual(set(mms_engine.LANGUAGE_PACKS), expected)
        for language in expected:
            self.assertEqual(desktop_app.voices_for_language(language), [f"mms_{language}"])
            self.assertEqual(speech_service.engine_for(language, f"mms_{language}"), "mms")
            self.assertEqual(speech_service.language_for_voice(f"mms_{language}"), language)

    def test_pack_status_is_local_and_does_not_load_transformers(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"YAW_YAW_LANGUAGE_PACKS_DIR": directory}
        ):
            status = mms_engine.pack_status("tgl")
            self.assertFalse(status["ready"])
            self.assertIn("model.safetensors", status["missing"])
            pack = Path(directory) / "tgl"
            pack.mkdir()
            for name in mms_engine._MODEL_FILES:
                (pack / name).write_text("test", encoding="utf-8")
            self.assertTrue(mms_engine.pack_status("tgl")["ready"])

    def test_shared_service_routes_mms_and_preserves_subtitles(self):
        fake_audio = np.ones(2400, dtype=np.float32)
        with patch.object(mms_engine, "synthesize", return_value=fake_audio) as generate:
            audio, subtitles = speech_service.synthesize(
                "Maayong buntag.", "mms_ceb", language="ceb", return_subtitles=True
            )
        np.testing.assert_array_equal(audio, fake_audio)
        generate.assert_called_once()
        self.assertIn("Maayong buntag.", subtitles)

    def test_mms_backend_normalizes_sample_rate(self):
        tensor = Mock()
        tensor.squeeze.return_value.detach.return_value.cpu.return_value.numpy.return_value = np.ones(1600)
        model = Mock(config=types.SimpleNamespace(sampling_rate=16000))
        model.return_value = types.SimpleNamespace(waveform=tensor)
        tokenizer = Mock(return_value={})
        with patch.object(mms_engine, "_load", return_value=(tokenizer, model)):
            result = mms_engine.synthesize("Kumusta", "tgl")
        self.assertEqual(result.dtype, np.float32)
        self.assertEqual(len(result), 2400)
        model.assert_called_once_with(speaking_rate=1.0)

    def test_ui_installer_uses_a_separate_online_process(self):
        ui = desktop_app.YawYawApp.__new__(desktop_app.YawYawApp)
        ui.events = queue.Queue()
        ui.closing = threading.Event()
        ui.pack_process = None
        process = Mock()
        process.stdout = ["Downloading Ilocano...\n", "Ready: Ilocano\n"]
        process.wait.return_value = 0
        with patch.object(desktop_app.subprocess, "Popen", return_value=process) as popen:
            ui._run_pack_installer(["ilo"])
        command = popen.call_args.args[0]
        environment = popen.call_args.kwargs["env"]
        self.assertEqual(command[-2:], ["install", "ilo"])
        self.assertEqual(environment["HF_HUB_OFFLINE"], "0")
        self.assertEqual(environment["TRANSFORMERS_OFFLINE"], "0")
        events = []
        while not ui.events.empty():
            events.append(ui.events.get_nowait())
        self.assertEqual(events[-1], ("pack_done", ["ilo"]))


if __name__ == "__main__":
    unittest.main()
