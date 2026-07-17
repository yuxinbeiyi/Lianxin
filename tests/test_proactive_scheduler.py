import unittest
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.duty_scheduler import ProactiveDuty, SlackDuty
from utils.proactive_chat import ProactiveChatScheduler
from workers.slack_worker import SlackWorker


def make_scheduler():
    scheduler = ProactiveChatScheduler.__new__(ProactiveChatScheduler)
    scheduler._settings = scheduler._default_settings()
    scheduler._last_fire_time = None
    scheduler._defer_until = None
    return scheduler


class ProactiveBehaviorSchedulerTests(unittest.TestCase):
    def test_old_settings_gain_new_defaults_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "proactive_settings.json"
            path.write_text(json.dumps({"desktop_enabled": True, "frequency": 37}),
                            encoding="utf-8")
            with patch("utils.proactive_chat._SETTINGS_PATH", path):
                scheduler = ProactiveChatScheduler()

        self.assertTrue(scheduler.desktop_enabled)
        self.assertEqual(37, scheduler.frequency)
        self.assertEqual(30, scheduler.behavior_weights["normal"])
        self.assertTrue(scheduler.fallback_on_failure)

    def test_behavior_choice_reduces_immediate_repeat(self):
        scheduler = make_scheduler()
        scheduler._settings["_behavior_history"] = ["normal"]
        captured = {}

        def fake_choices(items, weights, k):
            captured["items"] = items
            captured["weights"] = weights
            return [items[1]]

        with patch("utils.proactive_chat.random.choices", fake_choices):
            self.assertEqual("observe", scheduler.choose_behavior(["normal", "observe"]))
        self.assertEqual(["normal", "observe"], captured["items"])
        self.assertLess(captured["weights"][0], captured["weights"][1])

    def test_success_records_global_and_behavior_cooldowns(self):
        scheduler = make_scheduler()
        scheduler.save_settings = lambda: None

        scheduler.record_behavior_success("bilibili")

        self.assertIsNotNone(scheduler._last_fire_time)
        self.assertTrue(scheduler._settings["_last_global_success"])
        self.assertEqual(["bilibili"], scheduler._settings["_behavior_history"])
        self.assertFalse(scheduler.is_behavior_ready("bilibili"))
        old = datetime.now() - timedelta(minutes=181)
        scheduler._settings["_behavior_last_success"]["bilibili"] = old.isoformat()
        self.assertTrue(scheduler.is_behavior_ready("bilibili"))

    def test_observation_source_is_one_weighted_draw(self):
        scheduler = make_scheduler()
        scheduler.desktop_enabled = True
        scheduler.observe_enabled = True
        scheduler.screenshot_prob = 12
        scheduler.camera_prob = 10
        calls = []

        def fake_choices(items, weights, k):
            calls.append((items, weights))
            return ["camera"]

        with patch("utils.proactive_chat.random.choices", fake_choices):
            self.assertEqual("camera", scheduler.should_observe())
        self.assertEqual([(["screenshot", "camera"], [12, 10])], calls)

    def test_unified_duty_filters_unavailable_behaviors(self):
        scheduler = make_scheduler()
        scheduler.desktop_enabled = True
        scheduler.observe_enabled = True
        scheduler.bilibili_enabled = True
        scheduler.slack_enabled = True
        scheduler.slack_idle_minutes = 20
        state = SimpleNamespace(
            proactive_scheduler=scheduler,
            is_shoulder_available=lambda: False,
            last_user_message_time=1000,
            now=1000 + 5 * 60,
        )
        duty = ProactiveDuty()

        with patch.object(duty, "_bilibili_available", return_value=False):
            candidates = duty._eligible_behaviors(state)

        self.assertIn("normal", candidates)
        self.assertIn("observe", candidates)
        self.assertNotIn("bilibili", candidates)
        self.assertNotIn("slack", candidates)

    def test_legacy_slack_duty_never_runs_its_own_random_gate(self):
        self.assertFalse(SlackDuty()._should_fire(SimpleNamespace()))

    def test_unified_duty_accepts_slack_worker_signal_set(self):
        duty = ProactiveDuty()
        duty._wire_worker(SlackWorker("random_question", "context"))


if __name__ == "__main__":
    unittest.main()
