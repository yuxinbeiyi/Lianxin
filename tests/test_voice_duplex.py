import builtins
import unittest
from unittest.mock import patch

from brain.vad_webrtc import WebRTCVADWorker
from brain.voice_duplex import STATE_STOPPED, VoiceDuplexManager


class VoiceDuplexTests(unittest.TestCase):
    def test_voice_segment_is_queued_once(self):
        manager = VoiceDuplexManager()

        manager._on_voice_end(b"wav-data")

        self.assertEqual(manager._audio_queue.qsize(), 1)
        self.assertEqual(manager._audio_queue.get_nowait(), b"wav-data")

    def test_vad_import_reports_missing_transitive_dependency(self):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "webrtcvad":
                raise ModuleNotFoundError(
                    "No module named 'pkg_resources'", name="pkg_resources"
                )
            return real_import(name, *args, **kwargs)

        worker = WebRTCVADWorker()
        with patch.object(builtins, "__import__", side_effect=fake_import):
            with self.assertLogs("lianxin.vad_webrtc", level="ERROR") as logs:
                self.assertFalse(worker._load_vad())

        output = "\n".join(logs.output)
        self.assertIn("缺少依赖 pkg_resources", output)
        self.assertNotIn("webrtcvad 未安装", output)

    def test_manager_does_not_enter_listening_when_vad_init_fails(self):
        manager = VoiceDuplexManager()
        with patch.object(WebRTCVADWorker, "_load_vad", return_value=False):
            with self.assertLogs("VoiceDuplex", level="ERROR"):
                self.assertFalse(manager.start())

        self.assertEqual(manager.state, STATE_STOPPED)
        self.assertIsNone(manager._vad_worker)


if __name__ == "__main__":
    unittest.main()
