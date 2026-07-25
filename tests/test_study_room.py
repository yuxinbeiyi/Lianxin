import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from gui.study_room.database import StudyDatabase
from gui.study_room.bridge import StudyRoomBridge
from gui.study_room.timer import FocusTimer


class StudyRoomDatabaseTests(unittest.TestCase):
    def test_tasks_visits_and_focus_stats_persist(self):
        with TemporaryDirectory() as directory:
            db = StudyDatabase(Path(directory) / "study.db")
            task_id = db.add_task("完成测试", 25, 10, True)
            self.assertEqual(task_id, db.tasks()[0]["id"])
            self.assertEqual(10, db.tasks()[0]["break_minutes"])
            self.assertEqual(1, db.tasks()[0]["repeat_enabled"])
            self.assertTrue(db.update_task(task_id, "编辑后的任务", 30, 15, False))
            edited = db.tasks()[0]
            self.assertEqual("编辑后的任务", edited["title"])
            self.assertEqual(30, edited["estimate_minutes"])
            self.assertEqual(15, edited["break_minutes"])
            self.assertEqual(0, edited["repeat_enabled"])
            db.toggle_task(task_id)
            self.assertEqual(1, db.stats_range("today")["completed_tasks"])
            db.toggle_task(task_id)

            visit_id = db.open_visit()
            db.close_visit(visit_id)
            db.add_focus_session(
                task_id, "完成测试", datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                1500, True,
            )

            stats = db.stats()
            self.assertEqual(1500, stats["focus_seconds"])
            self.assertEqual(1, stats["completed"])
            self.assertEqual(1, stats["visits"])
            self.assertEqual(1, db.streak())
            db.add_focus_session(task_id, "完成测试", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 120, False)
            db.add_focus_session(
                task_id, "昨天的记录", (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                600, False,
            )
            ranged = db.stats_range("today")
            self.assertEqual(1, ranged["completed_sessions"])
            self.assertEqual(1, ranged["interrupted_sessions"])
            self.assertEqual(1620, ranged["focus_seconds"])
            self.assertEqual(600, ranged["previous_focus_seconds"])
            self.assertEqual("昨天", ranged["previous_label"])
            week = db.week_trend()
            self.assertEqual(7, len(week))
            self.assertEqual(0, week[0]["date"].weekday())
            self.assertEqual(6, week[-1]["date"].weekday())

    def test_web_bridge_exposes_state_without_global_data(self):
        with TemporaryDirectory() as directory:
            bridge = StudyRoomBridge(db_path=Path(directory) / "bridge.db")
            state = bridge._state_payload()
            self.assertIn("tasks", state)
            self.assertIn("stats", state)
            self.assertIn("auto_fullscreen", state["settings"])
            bridge.add_task("桥接任务")
            self.assertEqual("桥接任务", bridge.db.tasks()[0]["title"])
            bridge.add_task("循环任务", 2, 10, True)
            task = next(item for item in bridge.db.tasks() if item["title"] == "循环任务")
            self.assertEqual(2, task["estimate_minutes"])
            self.assertEqual(10, task["break_minutes"])
            self.assertEqual(1, task["repeat_enabled"])
            bridge.update_task(task["id"], "修改后的循环任务", 3, 12, False)
            edited = next(item for item in bridge.db.tasks() if item["id"] == task["id"])
            self.assertEqual("修改后的循环任务", edited["title"])
            self.assertEqual(3, edited["estimate_minutes"])
            self.assertEqual(12, edited["break_minutes"])
            self.assertEqual(0, edited["repeat_enabled"])
            bridge.shutdown()

    def test_focus_fullscreen_request_is_explicit(self):
        with TemporaryDirectory() as directory:
            bridge = StudyRoomBridge(db_path=Path(directory) / "fullscreen.db")
            requests = []
            bridge.focus_fullscreen_requested.connect(requests.append)
            bridge.set_focus_fullscreen(True)
            bridge.set_focus_fullscreen(False)
            self.assertEqual([True, False], requests)
            bridge.shutdown()

    def test_task_estimate_overrides_default_focus_duration(self):
        with TemporaryDirectory() as directory:
            bridge = StudyRoomBridge(db_path=Path(directory) / "estimate.db")
            task_id = bridge.db.add_task("两分钟任务", 2)
            bridge.start_focus(25, 5, task_id)
            self.assertEqual(120, bridge.timer.remaining)
            bridge.shutdown()

    def test_repeat_timer_starts_next_focus_after_break(self):
        timer = FocusTimer()
        phases = []
        timer.phase_changed.connect(phases.append)
        timer.start_focus(60, 1, "循环", True)
        timer.remaining = 1
        timer._on_tick()
        self.assertEqual("break", timer.phase)
        timer.remaining = 1
        timer._on_tick()
        self.assertEqual("focus", timer.phase)

    def test_clock_payload_contains_calendar_fields(self):
        payload = StudyRoomBridge._clock_payload()
        self.assertRegex(payload["time"], r"^\d{2}:\d{2}$")
        self.assertTrue(payload["date"])
        self.assertTrue(payload["weekday"])
        self.assertIn("农历", payload["lunar"])


if __name__ == "__main__":
    unittest.main()
