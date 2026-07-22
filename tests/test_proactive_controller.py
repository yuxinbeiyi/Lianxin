import tempfile
import unittest
from pathlib import Path

from gui.proactive_controller import ProactivePresentationController


class _SchedulerStub:
    desktop_enabled = True
    qq_enabled = True
    observe_send_to_qq = False

    def __init__(self):
        self.observation = ""
        self.diary_supplements = 0

    def set_last_observation(self, desc):
        self.observation = desc

    def record_diary_supplement(self):
        self.diary_supplements += 1


class _HistoryStub:
    def __init__(self):
        self.messages = []

    def save_message(self, session_id, role, content):
        self.messages.append((session_id, role, content))


class _ChatStub:
    def __init__(self):
        self.ai_messages = []
        self.tips = []
        self.sources = []
        self.images = []

    def add_ai_message(self, text):
        self.ai_messages.append(text)

    def add_system_tip(self, text):
        self.tips.append(text)

    def add_mooyu_data_sources(self, sources):
        self.sources.append(sources)

    def add_image_message(self, path, **kwargs):
        self.images.append((path, kwargs))


class _BridgeStub:
    def __init__(self):
        self.messages = []

    def isRunning(self):
        return True

    def send_to_owner(self, text):
        self.messages.append(text)


class ProactivePresentationControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.scheduler = _SchedulerStub()
        self.history = _HistoryStub()
        self.chat = _ChatStub()
        self.bridge = _BridgeStub()
        self.spoken = []
        self.flashes = []
        self.next_tracks = 0
        self.controller = ProactivePresentationController(
            scheduler=self.scheduler,
            chat_widget=self.chat,
            history_manager_func=lambda: self.history,
            session_id_func=lambda: 7,
            speak_func=self.spoken.append,
            is_minimized_func=lambda: True,
            flash_taskbar_func=lambda **kwargs: self.flashes.append(kwargs),
            qq_bridge_func=lambda: self.bridge,
            dialog_func=lambda: None,
            next_track_func=self._next_track,
            observations_dir=Path(self.temp.name) / "observations",
        )

    def tearDown(self):
        self.temp.cleanup()

    def _next_track(self):
        self.next_tracks += 1

    def test_proactive_response_reaches_desktop_history_voice_and_qq(self):
        self.controller.handle_proactive_response("你好\n\n【表情：开心】")

        self.assertEqual(["你好"], self.chat.ai_messages)
        self.assertEqual([(7, "assistant", "[主动] 你好")], self.history.messages)
        self.assertEqual(["你好"], self.spoken)
        self.assertEqual(["你好"], self.bridge.messages)
        self.assertEqual([{"flash_count": 0}], self.flashes)

    def test_silence_placeholder_is_not_presented_or_sent(self):
        self.controller.handle_proactive_response("（璃弥娜沉默了）")

        self.assertEqual([], self.chat.ai_messages)
        self.assertEqual([], self.history.messages)
        self.assertEqual([], self.spoken)
        self.assertEqual([], self.bridge.messages)

    def test_observation_respects_qq_privacy_switch(self):
        self.controller.set_behavior("observe")
        self.controller.handle_proactive_response("观察消息")
        self.assertEqual([], self.bridge.messages)

    def test_slack_action_runs_success_side_effect(self):
        self.controller.set_slack_action("supplement_diary")
        self.controller.handle_slack_response("日记补充")
        self.assertEqual(1, self.scheduler.diary_supplements)

        self.controller.set_slack_action("next_song")
        self.controller.handle_slack_response("换首歌")
        self.assertEqual(1, self.next_tracks)

    def test_internal_mooyu_prefix_is_not_user_visible(self):
        raw = "[\u6478\u9c7c] \u96e8\u5fc3\u535a\u58eb\uff0c\u8fd9\u662f\u4e00\u6761\u63d2\u8bdd\u3002"
        cleaned = self.controller._clean_text(raw)
        self.assertEqual("\u96e8\u5fc3\u535a\u58eb\uff0c\u8fd9\u662f\u4e00\u6761\u63d2\u8bdd\u3002", cleaned)

    def test_behavior_fallback_discards_stale_data_sources(self):
        self.controller._last_behavior = "bilibili"
        self.controller._pending_mooyu_sources.append("stale")
        self.controller.set_behavior("normal")
        self.controller.handle_proactive_response("回退消息")
        self.assertEqual([], self.chat.sources)

    def test_observation_image_is_copied_and_temp_removed(self):
        source = Path(self.temp.name) / "capture.png"
        source.write_bytes(b"image")
        self.controller.handle_observation_image(str(source), "屏幕内容")

        self.assertFalse(source.exists())
        self.assertEqual(1, len(self.chat.images))
        self.assertTrue(Path(self.chat.images[0][0]).exists())
        self.assertEqual("[观察] 莲心看了一眼屏幕", self.history.messages[0][2])


if __name__ == "__main__":
    unittest.main()
