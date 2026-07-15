import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from brain.agent import AgentCore
from brain.emotional.events import _make_event, detect_events
from brain.emotional.manager import EmotionManager
from brain.emotional.state import EmotionalState, NeedsState


class _HistoryStub:
    def update_title(self, *_args):
        pass

    def save_message(self, *_args):
        pass


def _manager_with_state(state: EmotionalState) -> EmotionManager:
    with patch.object(EmotionalState, "load", return_value=state):
        return EmotionManager()


class EmotionalDecayTests(unittest.TestCase):
    def test_disabled_manager_does_not_decay_or_save(self):
        now = time.time()
        state = EmotionalState(
            needs=NeedsState(security=35, needed=53),
            enabled=False,
            last_update=now - 3600,
            last_interaction=now - 100 * 3600,
        )
        manager = _manager_with_state(state)
        before = state.needs.to_dict()

        with patch.object(state, "save") as save:
            manager.update_decay_only()

        self.assertEqual(before, state.needs.to_dict())
        save.assert_not_called()

    def test_loneliness_drift_is_incremental_not_total_gap(self):
        now = time.time()
        state = EmotionalState(
            needs=NeedsState(security=50, needed=50),
            last_update=now - 3600,
            last_interaction=now - 20 * 3600,
        )

        state._apply_decay(1, now=now)

        self.assertAlmostEqual(state.needs.security, 49.7, places=2)
        self.assertAlmostEqual(state.needs.needed, 49.8, places=2)

        later = now + 300
        state._apply_decay(5 / 60, now=later)
        self.assertGreater(state.needs.security, 49.6)
        self.assertGreater(state.needs.needed, 49.7)

    def test_enabling_starts_from_current_time(self):
        old = time.time() - 7 * 86400
        state = EmotionalState(
            enabled=False,
            last_update=old,
            last_interaction=old,
        )
        manager = _manager_with_state(state)

        with patch.object(state, "save"):
            manager.enabled = True

        self.assertTrue(state.enabled)
        self.assertLess(time.time() - state.last_update, 2)
        self.assertLess(time.time() - state._last_interaction, 2)


class EmotionalPersistenceTests(unittest.TestCase):
    def test_startup_decay_advances_cursor_and_is_not_reapplied(self):
        import brain.emotional.state as state_module

        now = time.time()
        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            backup_file = Path(tmpdir) / "state.json.bak"
            state_file.write_text(
                json.dumps(
                    {
                        "needs": NeedsState(security=50, needed=50).to_dict(),
                        "last_update": now - 20 * 3600,
                        "last_interaction": now - 20 * 3600,
                        "enabled": True,
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(state_module, "STATE_FILE", state_file), patch.object(
                state_module, "STATE_BACKUP", backup_file
            ):
                loaded = EmotionalState.load()
                after_load = loaded.needs.security
                manager = _manager_with_state(loaded)
                manager.update_decay_only()

            self.assertGreater(after_load, 47.0)
            self.assertLess(after_load, 48.0)
            self.assertAlmostEqual(loaded.needs.security, after_load, places=2)
            self.assertLess(time.time() - loaded.last_update, 2)

    def test_session_caps_are_not_restored(self):
        import brain.emotional.state as state_module

        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            backup_file = Path(tmpdir) / "state.json.bak"
            state = EmotionalState(enabled=False)
            state._session_caps["security"] = 12.0

            with patch.object(state_module, "STATE_FILE", state_file), patch.object(
                state_module, "STATE_BACKUP", backup_file
            ):
                state.save()
                loaded = EmotionalState.load()

            self.assertEqual(loaded.get_session_caps()["security"], 0.0)
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertNotIn("session_caps", saved)

    def test_legacy_file_without_interaction_time_does_not_use_epoch(self):
        import brain.emotional.state as state_module

        now = time.time()
        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            backup_file = Path(tmpdir) / "state.json.bak"
            state_file.write_text(
                json.dumps(
                    {
                        "needs": NeedsState().to_dict(),
                        "last_update": now - 3600,
                        "enabled": True,
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(state_module, "STATE_FILE", state_file), patch.object(
                state_module, "STATE_BACKUP", backup_file
            ):
                loaded = EmotionalState.load()

            self.assertGreater(loaded.needs.security, 60)
            self.assertLess(now - loaded._last_interaction, 3700)

    def test_concurrent_saves_leave_valid_json(self):
        import brain.emotional.state as state_module

        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            backup_file = Path(tmpdir) / "state.json.bak"
            state = EmotionalState(enabled=False)

            with patch.object(state_module, "STATE_FILE", state_file), patch.object(
                state_module, "STATE_BACKUP", backup_file
            ):
                threads = [threading.Thread(target=state.save) for _ in range(8)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            data = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 3)
            self.assertFalse(data["enabled"])
            self.assertEqual(list(Path(tmpdir).glob("*.tmp.*")), [])


class EmotionalEventTests(unittest.TestCase):
    def test_ambiguous_words_do_not_trigger_boundary_or_ritual(self):
        event_types = {
            event.type for event in detect_events(["这是假的新闻，帮我测试一下安装流程"])
        }
        self.assertNotIn("boundary_lie", event_types)
        self.assertNotIn("daily_ritual", event_types)

    def test_event_cooldown_suppresses_duplicate_effect(self):
        state = EmotionalState()
        manager = _manager_with_state(state)
        first = _make_event("boundary_lie", "第一次")
        second = _make_event("boundary_lie", "第二次")

        with patch.object(state, "save"):
            self.assertTrue(manager._apply_event_v2(first))
            after_first = state.needs.security
            self.assertFalse(manager._apply_event_v2(second))

        self.assertEqual(after_first, state.needs.security)
        self.assertEqual(len(state.event_history), 1)

    def test_real_camera_tool_is_blocked_in_defensive_state(self):
        state = EmotionalState(needs=NeedsState(security=20))
        manager = _manager_with_state(state)
        allowed, _reason = manager.check_tool_allowed("capture_from_camera")
        self.assertFalse(allowed)


class AgentEmotionTrackingTests(unittest.TestCase):
    def test_tool_disabled_chat_still_updates_emotion(self):
        agent = AgentCore.__new__(AgentCore)
        agent.history = []
        agent._session_titled = True
        agent._history_mgr = _HistoryStub()
        agent._session_id = 1
        agent._disable_tools = False
        agent._use_local = False
        agent._track_emotion = True
        agent._auto_extract = False
        agent._last_emotion = None
        agent._last_raw_response = None
        agent._last_reply_time = None
        agent._function_calling_loop = lambda *_args, **_kwargs: "好的"
        emotion_manager = Mock()

        with patch("brain.emotional.get_manager", return_value=emotion_manager):
            agent.chat("晚上好呀", disable_tools=True)

        emotion_manager.analyze_and_update.assert_called_once()

    def test_tracking_can_be_disabled_for_non_owner_channels(self):
        agent = AgentCore.__new__(AgentCore)
        agent.history = []
        agent._session_titled = True
        agent._history_mgr = _HistoryStub()
        agent._session_id = 1
        agent._disable_tools = True
        agent._use_local = False
        agent._track_emotion = False
        agent._auto_extract = False
        agent._last_emotion = None
        agent._last_raw_response = None
        agent._last_reply_time = None
        agent._function_calling_loop = lambda *_args, **_kwargs: "好的"
        emotion_manager = Mock()

        with patch("brain.emotional.get_manager", return_value=emotion_manager):
            agent.chat("晚上好呀", disable_tools=True)

        emotion_manager.analyze_and_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
