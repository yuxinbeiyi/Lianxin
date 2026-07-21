"""Compatibility and migration tests for the Ripple v3 replacement."""

import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from brain.emotional.manager import EmotionManager
from brain.emotional.v3_models import EmotionalStateV3
from brain.emotional.v3_store import EmotionStore


class LegacyPersistenceTests(unittest.TestCase):
    """The v2 JSON reader remains covered because it is the migration source."""

    def test_legacy_json_is_read_without_epoch_interaction(self):
        from brain.emotional.state import EmotionalState, NeedsState
        import brain.emotional.state as state_module

        now = time.time()
        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            backup_file = Path(tmpdir) / "state.json.bak"
            state_file.write_text(json.dumps({
                "needs": NeedsState().to_dict(),
                "last_update": now - 3600,
                "enabled": True,
            }), encoding="utf-8")
            with patch.object(state_module, "STATE_FILE", state_file), patch.object(
                state_module, "STATE_BACKUP", backup_file
            ):
                loaded = EmotionalState.load()

        self.assertGreater(loaded._last_interaction, now - 3700)

    def test_legacy_state_concurrent_saves_leave_valid_json(self):
        from brain.emotional.state import EmotionalState
        import brain.emotional.state as state_module

        with TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            backup_file = Path(tmpdir) / "state.json.bak"
            state = EmotionalState(enabled=False)
            with patch.object(state_module, "STATE_FILE", state_file), patch.object(
                state_module, "STATE_BACKUP", backup_file
            ):
                threads = [threading.Thread(target=state.save) for _ in range(6)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
            payload = json.loads(state_file.read_text(encoding="utf-8"))

        self.assertEqual(3, payload["schema_version"])
        self.assertFalse(payload["enabled"])


class RippleV3CompatibilityTests(unittest.TestCase):
    def manager(self):
        return EmotionManager(
            store=EmotionStore(":memory:"),
            semantic_mode="off",
            legacy_state_path=Path("__missing_emotional_state__.json"),
        )

    def test_old_manager_entry_point_updates_state(self):
        manager = self.manager()

        result = manager.analyze_and_update(["谢谢你，辛苦了"])

        self.assertEqual("warm_connection", result.event_type)
        self.assertLess(manager.state.connection, 0.08)

    def test_tool_gate_is_owned_by_security_policy_not_mood(self):
        manager = self.manager()
        manager.set_relationship(rupture=1.0)

        self.assertEqual((True, ""), manager.check_tool_allowed("delete_file"))

    def test_old_event_debug_entry_point_still_persists(self):
        from brain.emotional.events import _make_event

        manager = self.manager()
        manager._apply_event_v2(_make_event("compliment", "调试"))

        self.assertEqual(1, manager.get_debug_info()["event_count"])


class AgentEmotionTrackingTests(unittest.TestCase):
    def _agent(self, track_emotion=True):
        from brain.agent import AgentCore

        agent = AgentCore.__new__(AgentCore)
        agent.history = []
        agent._session_titled = True
        agent._history_mgr = Mock()
        agent._history_mgr.save_message.return_value = 1
        agent._session_id = 1
        agent._disable_tools = False
        agent._use_local = False
        agent._track_emotion = track_emotion
        agent._owner_scope = True
        agent._source_channel = "desktop"
        agent._auto_extract = False
        agent._last_emotion = None
        agent._last_raw_response = None
        agent._last_reply_time = None
        agent._session_memory_writes_blocked = False
        agent._request_memory_writes_blocked = False
        agent._function_calling_loop = lambda *_args, **_kwargs: "好的"
        return agent

    def test_current_turn_is_prepared_before_generation(self):
        agent = self._agent()
        emotion_manager = Mock()

        with patch("brain.emotional.get_manager", return_value=emotion_manager):
            agent.chat("晚上好呀", disable_tools=True)

        emotion_manager.prepare_turn.assert_called_once()
        emotion_manager.record_turn_outcome.assert_called_once()

    def test_tracking_can_be_disabled_for_non_owner_channels(self):
        agent = self._agent(track_emotion=False)
        emotion_manager = Mock()

        with patch("brain.emotional.get_manager", return_value=emotion_manager):
            agent.chat("晚上好呀", disable_tools=True)

        emotion_manager.prepare_turn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
