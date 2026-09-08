"""Headless regression tests; no model downloads or audio device required."""
import queue
import threading
import unittest
from unittest.mock import Mock, patch
import numpy as np
import desktop_app as app


class WorkerTests(unittest.TestCase):
    def test_worker_routes_to_shared_service(self):
        events, closing = queue.Queue(), threading.Event()
        with patch.object(app.speech_service, "synthesize", return_value=np.ones(4)) as generate:
            app.SpeechWorker().generate("Hello", "b", "bf_emma", events, closing)
        self.assertEqual(events.get_nowait()[0], "done")
        self.assertEqual(generate.call_args.kwargs["language"], "b")

    def test_worker_handles_cancellation_without_error_dialog(self):
        events, closing = queue.Queue(), threading.Event()
        with patch.object(app.speech_service, "synthesize", side_effect=app.speech_service.GenerationCancelled):
            app.SpeechWorker().generate("Hello", "a", "af_heart", events, closing)
        self.assertTrue(events.empty())

    def test_worker_reports_failure(self):
        events, closing = queue.Queue(), threading.Event()
        with patch.object(app.speech_service, "synthesize", side_effect=ValueError("bad input")):
            app.SpeechWorker().generate("Hello", "a", "af_heart", events, closing)
        self.assertEqual(events.get_nowait(), ("error", "bad input"))

    def test_worker_discards_late_result(self):
        events, closing = queue.Queue(), threading.Event()
        closing.set()
        with patch.object(app.speech_service, "synthesize", return_value=np.ones(4)):
            app.SpeechWorker().generate("Hello", "a", "af_heart", events, closing)
        self.assertTrue(events.empty())


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.ui = app.KokoroDesktopApp.__new__(app.KokoroDesktopApp)
        for name in ("root", "status", "text", "voice_box", "language_box", "generate_button", "generate_play_button", "play_button", "stop_button", "save_button", "progress", "sounddevice", "speed_scale", "clear_button", "clip_info", "voice_description"):
            setattr(self.ui, name, Mock())
        self.ui.lang_var = Mock(get=Mock(return_value="American English"))
        self.ui.voice_var = Mock(get=Mock(return_value="af_heart"))
        self.ui.speed_var = Mock(get=Mock(return_value=1.0))
        self.ui.text.get.return_value = "Hello"
        self.ui.worker = Mock()
        self.ui.events = queue.Queue()
        self.ui.closing = threading.Event()
        self.ui.busy = False
        self.ui.playing = False
        self.ui.autoplay = False
        self.ui.audio = np.ones(4)
        self.ui.sample_rate = 24000
        self.ui.poll_id = "poll"

    def test_generation_runs_on_background_thread(self):
        self.assertTrue(self.ui.start_generation())
        self.ui.thread.join(timeout=2)
        self.ui.worker.generate.assert_called_once()
        self.assertTrue(self.ui.thread.daemon)
        self.assertTrue(self.ui.busy)

    def test_duplicate_requests_rejected(self):
        self.ui.busy = True
        with patch.object(app.threading, "Thread") as thread:
            self.assertFalse(self.ui.start_generation())
            self.ui.on_enter()
            thread.assert_not_called()

    def test_selected_speed_reaches_worker(self):
        self.ui.speed_var.get.return_value = 1.4
        self.assertTrue(self.ui.start_generation())
        self.ui.thread.join(timeout=2)
        self.assertEqual(self.ui.worker.generate.call_args.kwargs['speed'], 1.4)
        self.ui.speed_scale.configure.assert_called_with(state="disabled")

    def test_slow_speed_text_limit_rejected_before_starting(self):
        self.ui.speed_var.get.return_value = 0.5
        self.ui.text.get.return_value = "x" * 2501
        with patch.object(app.messagebox, "showwarning") as warning, patch.object(app.threading, "Thread") as thread:
            self.assertFalse(self.ui.start_generation())
            warning.assert_called_once()
            thread.assert_not_called()

    def test_empty_input_does_not_start(self):
        self.ui.text.get.return_value = " "
        with patch.object(app.messagebox, "showwarning") as warning:
            self.assertFalse(self.ui.start_generation())
            warning.assert_called_once()
        self.assertFalse(self.ui.busy)

    def test_language_change_corrects_voice(self):
        self.ui.lang_var.get.return_value = "British English"
        self.ui.change_language()
        self.ui.voice_var.set.assert_called_once_with("bf_alice")
        self.ui.voice_box.configure.assert_called_once_with(values=app.voices_for_language("b"))

    def test_done_restores_buttons_and_autoplays(self):
        self.ui.busy = True
        self.ui.autoplay = True
        self.ui.events.put(("done", np.ones(8)))
        self.ui.sounddevice.get_stream.return_value.active = True
        self.ui.poll_events()
        self.assertFalse(self.ui.busy)
        self.ui.sounddevice.play.assert_called_once()
        self.ui.generate_button.configure.assert_called_with(state="normal")

    def test_error_preserves_previous_audio(self):
        old = self.ui.audio
        self.ui.busy = True
        self.ui.events.put(("error", "failed"))
        with patch.object(app.messagebox, "showerror") as error:
            self.ui.poll_events()
            error.assert_called_once()
        self.assertIs(self.ui.audio, old)
        self.assertFalse(self.ui.busy)

    def test_stop_playback(self):
        self.ui.playing = True
        self.ui.stop_playback()
        self.ui.sounddevice.stop.assert_called_once()
        self.assertFalse(self.ui.playing)

    def test_playback_completion(self):
        self.ui.playing = True
        self.ui.sounddevice.get_stream.return_value.active = False
        self.ui.poll_events()
        self.ui.status.set.assert_called_with("Playback finished.")
        self.assertFalse(self.ui.playing)

    def test_audio_device_failure_is_handled(self):
        self.ui.sounddevice.play.side_effect = RuntimeError("No output device")
        with patch.object(app.messagebox, "showerror") as error:
            self.ui.play_audio()
            error.assert_called_once()
        self.assertFalse(self.ui.playing)

    def test_save_failure_is_handled(self):
        soundfile = Mock()
        soundfile.write.side_effect = PermissionError("Denied")
        with patch.dict("sys.modules", {"soundfile": soundfile}), patch.object(app.filedialog, "asksaveasfilename", return_value="/not-writable/output.wav"), patch.object(app.messagebox, "showerror") as error:
            self.ui.save_wav()
            error.assert_called_once()

    def test_close_stops_playback_and_polling(self):
        self.ui.close()
        self.assertTrue(self.ui.closing.is_set())
        self.ui.sounddevice.stop.assert_called_once()
        self.ui.root.after_cancel.assert_called_once_with("poll")
        self.ui.root.destroy.assert_called_once()
        self.ui.root.after.reset_mock()
        self.ui.poll_events()
        self.ui.root.after.assert_not_called()


if __name__ == "__main__":
    unittest.main()
