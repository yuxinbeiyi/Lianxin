import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

from voice.speaker import VoiceSpeaker


class VoiceSpeakerTtsTests(unittest.TestCase):
    def setUp(self):
        self.speaker = VoiceSpeaker()

    def tearDown(self):
        for path in getattr(self, "_temp_paths", []):
            try:
                os.unlink(path)
            except OSError:
                pass

    @staticmethod
    def _gpt_engine(success=True):
        engine = Mock()
        engine.gpt_sovits_available = True
        engine.synthesize_gpt_wav.return_value = success
        return engine

    def test_gpt_sentence_keeps_wav_and_does_not_call_edge(self):
        engine = self._gpt_engine()
        self.speaker._async_synthesize = AsyncMock()

        path = self.speaker._synthesize_sentence("你好，我是莲心。", engine, "casual", 1.0)
        self._temp_paths = [path]

        self.assertIsNotNone(path)
        self.assertTrue(path.endswith(".wav"))
        engine.synthesize_gpt_wav.assert_called_once()
        self.speaker._async_synthesize.assert_not_awaited()

    def test_gpt_failure_falls_back_to_edge_mp3(self):
        engine = self._gpt_engine(success=False)
        self.speaker._async_synthesize = AsyncMock()

        path = self.speaker._synthesize_sentence("请稍等一下。", engine, "casual", 1.0)
        self._temp_paths = [path]

        self.assertIsNotNone(path)
        self.assertTrue(path.endswith(".mp3"))
        engine.synthesize_gpt_wav.assert_called_once()
        self.speaker._async_synthesize.assert_awaited_once()

    @patch("brain.tts_engine._is_gpt_sovits_available", return_value=True)
    def test_engine_explicit_gpt_wav_never_invokes_edge_fallback(self, _available):
        from brain.tts_engine import TtsEngine

        engine = TtsEngine()
        with patch.object(engine, "_synthesize_gpt_sovits", side_effect=RuntimeError("boom")):
            with patch("brain.tts_engine._fallback_edge_tts") as edge_fallback:
                result = engine.synthesize_gpt_wav("测试", "unused.wav")

        self.assertFalse(result)
        edge_fallback.assert_not_called()

    @patch("voice.speaker.VoiceSpeaker.init_player")
    @patch("brain.tts_engine.TtsEngine")
    @patch("config.get_tts_config", return_value={"engine": "auto", "speed": 1.0})
    def test_multi_sentence_chat_uses_wav_for_every_segment(
        self, _config, engine_cls, _init_player
    ):
        engine = self._gpt_engine()
        engine_cls.return_value = engine
        self.speaker._play = Mock()

        self.speaker.speak(
            "这是第一句足够长的测试内容。这里是第二句也足够长的测试内容。"
        )

        self.assertEqual(engine.synthesize_gpt_wav.call_count, 2)
        played_paths = [call.args[0] for call in self.speaker._play.call_args_list]
        self.assertEqual(len(played_paths), 2)
        self.assertTrue(all(path.endswith(".wav") for path in played_paths))


if __name__ == "__main__":
    unittest.main()
