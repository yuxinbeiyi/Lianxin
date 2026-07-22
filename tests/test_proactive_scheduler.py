import unittest
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.duty_scheduler import DutyScheduler, ProactiveDuty, SlackDuty
from utils.proactive_chat import ProactiveChatScheduler
from workers.slack_worker import SlackWorker
from workers.proactive_worker import ProactiveWorker


def make_scheduler():
    scheduler = ProactiveChatScheduler.__new__(ProactiveChatScheduler)
    scheduler._settings = scheduler._default_settings()
    scheduler._last_fire_time = None
    scheduler._defer_until = None
    scheduler._empty_session_started_at = None
    scheduler._empty_session_waiting = False
    return scheduler


class ProactiveBehaviorSchedulerTests(unittest.TestCase):
    def test_empty_desktop_session_gets_guaranteed_icebreaker_after_wait(self):
        scheduler = make_scheduler()
        scheduler.desktop_enabled = True
        scheduler.weights = [10] * 24
        scheduler.user_defer_minutes = 10
        scheduler.notify_session_started()
        scheduler._empty_session_started_at = datetime.now() - timedelta(minutes=11)

        with patch("utils.proactive_chat.random.random", return_value=0.999):
            self.assertTrue(scheduler.should_fire())

    def test_user_message_cancels_empty_session_icebreaker(self):
        scheduler = make_scheduler()
        scheduler.desktop_enabled = True
        scheduler.weights = [10] * 24
        scheduler.user_defer_minutes = 10
        scheduler.notify_session_started()
        scheduler._empty_session_started_at = datetime.now() - timedelta(minutes=11)

        scheduler.notify_user_active()

        with patch("utils.proactive_chat.random.random", return_value=0.999):
            self.assertFalse(scheduler.should_fire())
        self.assertFalse(scheduler._empty_session_waiting)

    def test_duty_scheduler_arms_new_session_and_resets_idle_baseline(self):
        class SchedulerStub:
            def __init__(self):
                self.calls = 0

            def notify_session_started(self):
                self.calls += 1

        proactive = SchedulerStub()
        duty_scheduler = DutyScheduler()
        duty_scheduler._proactive_scheduler = proactive

        duty_scheduler.on_session_started()

        self.assertEqual(1, proactive.calls)
        self.assertGreater(duty_scheduler._last_user_message_time, 0)

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

    def test_unified_duty_exposes_selected_slack_action(self):
        class SignalStub:
            def __init__(self):
                self.values = []

            def emit(self, *values):
                self.values.append(values)

        scheduler = make_scheduler()
        signal = SignalStub()
        duty_scheduler = SimpleNamespace(
            proactive_behavior_selected=SignalStub(),
            slack_action_selected=signal,
            mooyu_data_sources=SignalStub(),
        )
        state = SimpleNamespace(
            proactive_scheduler=scheduler,
            history_manager=None,
            is_shoulder_available=lambda: False,
            last_user_message_time=0,
            now=1000,
            todo_manager=None,
            agent=None,
            chat_widget=None,
            proactive_dialog=None,
        )
        duty = ProactiveDuty()
        duty._scheduler = duty_scheduler

        worker = duty._create_worker(
            state, force_behavior="slack", force_action="remind_water"
        )

        self.assertIsInstance(worker, SlackWorker)
        self.assertEqual([("remind_water",)], signal.values)

    def test_forced_bilibili_worker_disables_regular_fallback(self):
        duty = ProactiveDuty()
        duty._fallback_allowed = False
        self.assertFalse(duty._try_fallback())

    def test_bilibili_details_are_appended_when_model_omits_them(self):
        videos = [
            {"title": "测试视频", "link": "https://www.bilibili.com/video/BVTEST"},
        ]
        message = ProactiveWorker._ensure_bilibili_details("我找到一个视频", videos)
        self.assertIn("测试视频", message)
        self.assertIn("https://www.bilibili.com/video/BVTEST", message)

    def test_bilibili_generation_uses_local_title_link_fallback(self):
        worker = ProactiveWorker.__new__(ProactiveWorker)
        videos = [
            {"title": "本地兜底视频", "link": "https://www.bilibili.com/video/BVLOCAL"},
        ]
        with patch.object(worker, "_get_client", side_effect=RuntimeError("model unavailable")):
            message = worker._generate_bilibili_message("测试", videos, "rec_test")
        self.assertIn("本地兜底视频", message)
        self.assertIn("https://www.bilibili.com/video/BVLOCAL", message)

    def test_bilibili_fallback_has_a_human_recommendation_reason(self):
        worker = ProactiveWorker.__new__(ProactiveWorker)
        videos = [{
            "title": "标题线索",
            "link": "https://www.bilibili.com/video/BVREASON",
        }]
        message = worker._format_bilibili_fallback("测试", videos)
        self.assertIn("标题线索", message)
        self.assertIn("可能对你的口味", message)
        self.assertIn("https://www.bilibili.com/video/BVREASON", message)

    def test_bilibili_run_emits_titles_and_links_without_model(self):
        class BilibiliStub:
            def __init__(self):
                self.recorded = []

            def can_search(self):
                return False

            def get_weighted_tags(self, limit=3):
                return ["测试"]

            def filter_seen(self, results):
                return results

            def mark_tag_searched(self, keyword):
                pass

            def mark_searched(self):
                pass

            def add_record(self, keyword, results):
                self.recorded.append(results)
                return "rec_test"

            def save(self):
                pass

        manager = BilibiliStub()
        worker = ProactiveWorker(None, bilibili_mode=True, bilibili_ignore_cooldown=True)
        worker._get_client = lambda: (_ for _ in ()).throw(RuntimeError("model unavailable"))
        received = []
        worker.response_ready.connect(received.append)
        videos = [{
            "title": "真实视频标题",
            "author": "测试UP主",
            "play_count": 12,
            "bvid": "BVREAL",
            "link": "https://www.bilibili.com/video/BVREAL",
        }, {
            "title": "不应被选中的第二个视频",
            "author": "测试UP主",
            "play_count": 8,
            "bvid": "BVSECOND",
            "link": "https://www.bilibili.com/video/BVSECOND",
        }]
        with patch("utils.bilibili_history.get_bilibili_history", return_value=manager), \
             patch("brain.tools.bilibili_search", return_value=videos):
            worker._run_bilibili()
        self.assertEqual(1, len(received))
        self.assertEqual(1, len(manager.recorded[0]))
        self.assertIn("真实视频标题", received[0])
        self.assertIn("https://www.bilibili.com/video/BVREAL", received[0])
        self.assertNotIn("不应被选中的第二个视频", received[0])


if __name__ == "__main__":
    unittest.main()
