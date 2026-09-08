"""Regression tests for the new shared inference and offline workflows."""
import ast
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
import uuid
import numpy as np
from phase14_bootstrap import configure, ROOT

configure()
from kokoro_tts_local import speech_service as service
from kokoro_tts_local import paths
from prepare_offline import copy_missing


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "af_heart.pt"
        self.path.write_bytes(b"test")
        self.models = types.ModuleType("kokoro_tts_local.models")
        self.models.get_language_code_from_voice = lambda voice: voice[0]
        self.models.get_safe_voice_path = lambda voice: self.path
        self.models.OFFLINE_MODE = True
        self.models.build_model = Mock()
        self.models.download_voice_files = Mock()
        self.modules = patch.dict(sys.modules, {"kokoro_tts_local.models": self.models, "torch": types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.pipeline = Mock()
        self.pipeline.iter_speech.side_effect = lambda *a, **k: iter([(None, None, np.ones(2)), (None, None, np.zeros(2))])
        # A generator is required because the engine always closes it.
        def generate(*a, **k):
            yield None, None, np.ones(2)
            yield None, None, np.zeros(2)
        self.pipeline.iter_speech.side_effect = generate
        self.models.build_model.return_value = self.pipeline

    def test_shared_engine_returns_mono_float32_and_local_voice(self):
        result = service.synthesize("hello", "af_heart", language="a")
        np.testing.assert_array_equal(result, [1, 1, 0, 0])
        self.assertEqual(result.dtype, np.float32)
        self.pipeline.iter_speech.assert_called_once_with("hello", voice=str(self.path), speed=1.0, split_pattern=r'\n+')
        self.models.build_model.assert_called_once_with(None, "cpu", lang_code="a")

    def test_language_switch_uses_shared_registry_language_key(self):
        service.synthesize("hello", "af_heart")
        service.synthesize("hello", "bf_emma")
        self.assertEqual([c.kwargs["lang_code"] for c in self.models.build_model.call_args_list], ["a", "b"])

    def test_offline_missing_voice_never_downloads(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            service.synthesize("hello", "af_heart")
        self.models.download_voice_files.assert_not_called()

    def test_online_missing_voice_requests_selected_voice(self):
        self.models.OFFLINE_MODE = False
        self.path.unlink()
        service.synthesize("hello", "af_heart")
        self.models.download_voice_files.assert_called_once_with(["af_heart.pt"], required_count=1)

    def test_mismatched_language_rejected(self):
        with self.assertRaises(ValueError):
            service.synthesize("hello", "bf_emma", language="a")
        self.models.build_model.assert_not_called()

    def test_bad_requests_rejected(self):
        for text, speed in [("", 1), ("hello", 0), ("hello", float("nan")), ("x" * 5001, 1), ("x" * 1000, .1)]:
            with self.subTest(text=text[:10], speed=speed), self.assertRaises(ValueError):
                service.synthesize(text, "af_heart", speed=speed)

    def test_cancellation_closes_generator(self):
        closed, cancelled = threading.Event(), threading.Event()
        def generate(*a, **k):
            try:
                cancelled.set()
                yield None, None, np.ones(2)
            finally:
                closed.set()
        self.pipeline.iter_speech.side_effect = generate
        with self.assertRaises(service.GenerationCancelled):
            service.synthesize("hello", "af_heart", cancelled=cancelled)
        self.assertTrue(closed.is_set())

    def test_audio_limit_and_nonfinite_rejected(self):
        for audio in [np.array([float("nan")]), np.ones((2, 2)), np.ones(5)]:
            def generate(*a, **k):
                yield None, None, audio
            self.pipeline.iter_speech.side_effect = generate
            with patch.object(service, "MAX_SAMPLES", 4), self.assertRaises(ValueError):
                service.synthesize("hello", "af_heart")

    def test_empty_audio_rejected(self):
        def generate(*a, **k):
            yield None, None, None
        self.pipeline.iter_speech.side_effect = generate
        with self.assertRaisesRegex(ValueError, "No audio"):
            service.synthesize("hello", "af_heart")

    def test_web_wav_path_calls_shared_service(self):
        source = ast.parse((ROOT / "src/kokoro_tts_local/gradio_interface.py").read_text())
        function = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "generate_tts_with_logs")
        compiled = compile(ast.Module(body=[function], type_ignores=[]), "web", "exec")
        generate = Mock(return_value=np.ones(240))
        fake_torch = types.SimpleNamespace(Tensor=type("Tensor", (), {}), cuda=types.SimpleNamespace(is_available=lambda: False))
        namespace = {"Tuple": tuple, "Optional": __import__('typing').Optional, "PathLike": Path, "sf": Mock(), "torch": fake_torch, "np": np, "datetime": datetime, "uuid": uuid, "DEFAULT_OUTPUT_DIR": Path(self.temp.name), "MAX_TEXT_LENGTH": 5000, "MIN_SPEED": .1, "MAX_SPEED": 3, "MAX_COST_CHARS": 5000, "SAMPLE_RATE": 24000, "device": "cpu", "synthesize": generate, "enforce_output_retention": lambda: None, "_status": lambda headline, notes: headline}
        exec(compiled, namespace)
        with patch.dict(sys.modules, {"psutil": types.SimpleNamespace(virtual_memory=lambda: types.SimpleNamespace(available=8*1024**3))}):
            path, status = namespace["generate_tts_with_logs"]("af_heart", "Hello", "wav")
        self.assertIsNotNone(path)
        self.assertIn("seconds", status)
        generate.assert_called_once_with("Hello", "af_heart", speed=1.0, device="cpu")
        namespace["sf"].write.assert_called_once()


class OfflineSetupTests(unittest.TestCase):
    def test_copy_never_overwrites_existing_assets(self):
        with tempfile.TemporaryDirectory() as d:
            source, target = Path(d)/"old", Path(d)/"new"
            source.write_bytes(b"source")
            target.write_bytes(b"existing")
            self.assertFalse(copy_missing(source, target))
            self.assertEqual(target.read_bytes(), b"existing")
            other = Path(d)/"assets"/"new"
            self.assertTrue(copy_missing(source, other))
            self.assertEqual(other.read_bytes(), b"source")

    def test_paths_are_independent_of_working_directory(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"KOKORO_BASE_DIR": d}):
            self.assertEqual(paths.get_model_dir(), Path(d))
            self.assertEqual(paths.get_voices_dir(), Path(d)/"voices")

    def test_network_guard_denies_socket_and_child_process(self):
        code = "from verify_offline import block_network; import socket,subprocess; block_network(); assert isinstance(subprocess.Popen,type); import asyncio; blocked=0\nfor call in [lambda:socket.create_connection(('example.com',443)),lambda:subprocess.Popen(['echo','test'])]:\n try: call()\n except RuntimeError: blocked+=1\nassert blocked==2"
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_assets_produce_failed_report(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, KOKORO_BASE_DIR=d)
            result = subprocess.run([sys.executable, str(ROOT/"verify_offline.py")], env=env, cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1)
            report = json.loads((Path(d)/"offline-verification.json").read_text())
            self.assertFalse(report["passed"])
            self.assertIn("Missing assets", report["error"])


if __name__ == "__main__":
    unittest.main()
