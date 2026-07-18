import io
import json
import sys
import types
import unittest
import wave
from unittest.mock import patch

from brain.stt_aliyun import _extract_result, _wav_to_pcm, transcribe


def _make_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)
    return buf.getvalue()


class _FakeTranscriber:
    instance = None

    def __init__(self, **kwargs):
        type(self).instance = self
        self.kwargs = kwargs
        self.start_kwargs = None
        self.audio = []
        self.stopped = False
        self.shutdown_called = False

    def start(self, **kwargs):
        self.start_kwargs = kwargs

    def send_audio(self, data):
        self.audio.append(data)

    def stop(self, timeout=10):
        self.stopped = True
        message = json.dumps({"payload": {"result": "你好，莲心。"}})
        self.kwargs["on_sentence_end"](message)
        self.kwargs["on_completed"](json.dumps({"payload": {}}))

    def shutdown(self):
        self.shutdown_called = True


class AliyunSttTests(unittest.TestCase):
    def test_extract_result(self):
        self.assertEqual(
            _extract_result('{"payload":{"result":"测试"}}'), "测试"
        )
        self.assertEqual(_extract_result("not-json"), "")

    def test_wav_header_is_removed(self):
        pcm = b"\x01\x02" * 320
        self.assertEqual(_wav_to_pcm(_make_wav(pcm)), pcm)

    def test_transcribe_uses_official_sdk_callbacks_and_pcm_chunks(self):
        pcm = b"\x01\x02" * 800
        fake_nls = types.ModuleType("nls")
        fake_nls.__path__ = []
        fake_nls.NlsSpeechTranscriber = _FakeTranscriber
        fake_token = types.ModuleType("nls.token")
        fake_token.getToken = lambda _ak, _secret: "test-token"
        fake_nls.token = fake_token

        with patch.dict(
            sys.modules, {"nls": fake_nls, "nls.token": fake_token}
        ), patch("brain.stt_aliyun.time.sleep", return_value=None):
            result = transcribe(
                _make_wav(pcm),
                {
                    "access_key_id": "ak",
                    "access_key_secret": "secret",
                    "app_key": "app",
                },
            )

        instance = _FakeTranscriber.instance
        self.assertEqual(result, "你好，莲心。")
        self.assertTrue(instance.stopped)
        self.assertEqual(b"".join(instance.audio), pcm)
        self.assertTrue(all(len(chunk) <= 640 for chunk in instance.audio))
        self.assertEqual(instance.start_kwargs["aformat"], "pcm")
        self.assertEqual(instance.start_kwargs["sample_rate"], 16000)
        self.assertTrue(instance.start_kwargs["enable_intermediate_result"])


if __name__ == "__main__":
    unittest.main()
