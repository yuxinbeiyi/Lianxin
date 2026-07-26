import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from gui.study_room.database import StudyDatabase
from gui.study_room.report_service import StudyReportService


class StudyReportServiceTests(unittest.TestCase):
    def _add_session(self, db, started_at, seconds, completed, task_name):
        ended_at = datetime.fromisoformat(started_at)
        with db._connect() as conn:
            conn.execute(
                """INSERT INTO focus_sessions(task_name, started_at, ended_at, duration_seconds, completed)
                   VALUES (?, ?, ?, ?, ?)""",
                (task_name, started_at, ended_at.isoformat(sep=" "), seconds, int(completed)),
            )

    def _add_event(self, db, event_type, occurred_at, task_name=""):
        with db._connect() as conn:
            conn.execute(
                """INSERT INTO study_events(event_type, task_name, occurred_at, details_json)
                   VALUES (?, ?, ?, '{}')""",
                (event_type, task_name, occurred_at),
            )

    def test_week_report_aggregates_existing_local_data(self):
        with TemporaryDirectory() as directory:
            db = StudyDatabase(Path(directory) / "report.db")
            self._add_session(db, "2026-07-20 09:00:00", 1200, True, "准备简历")
            self._add_session(db, "2026-07-21 20:00:00", 600, True, "准备简历")
            self._add_session(db, "2026-07-21 20:30:00", 300, False, "投递岗位")
            self._add_session(db, "2026-07-13 09:00:00", 900, True, "旧任务")
            self._add_event(db, "task_completed", "2026-07-21 21:00:00", "准备简历")
            report = StudyReportService(db, today_provider=lambda: date(2026, 7, 26)).build("week", "2026-07-20")

            self.assertEqual("week", report["type"])
            self.assertTrue(report["is_current"])
            self.assertEqual(2100, report["metrics"]["focus_seconds"])
            self.assertEqual(1800, report["metrics"]["completed_focus_seconds"])
            self.assertEqual(300, report["metrics"]["interrupted_focus_seconds"])
            self.assertEqual(2, report["metrics"]["active_days"])
            self.assertEqual(67, report["metrics"]["completion_rate"])
            self.assertEqual("准备简历", report["top_tasks"][0]["task_name"])
            self.assertEqual(7, len(report["daily_trend"]))
            self.assertEqual("上周同期", report["comparison"]["previous_label"])
            self.assertEqual(1, report["metrics"]["completed_tasks"])
            self.assertTrue(report["narrative"]["suggestion"])

    def test_month_report_uses_previous_calendar_month_after_close(self):
        with TemporaryDirectory() as directory:
            db = StudyDatabase(Path(directory) / "report.db")
            self._add_session(db, "2026-06-08 10:00:00", 1500, True, "六月任务")
            self._add_session(db, "2026-07-08 10:00:00", 3000, True, "七月任务")
            report = StudyReportService(db, today_provider=lambda: date(2026, 8, 2)).build("month", "2026-07")

            self.assertTrue(report["is_complete"])
            self.assertEqual("2026年7月", report["label"])
            self.assertEqual(3000, report["metrics"]["focus_seconds"])
            self.assertEqual(1500, report["comparison"]["focus_delta_seconds"])
            self.assertEqual("上月", report["comparison"]["previous_label"])

    def test_current_month_compares_same_elapsed_days_of_previous_month(self):
        with TemporaryDirectory() as directory:
            db = StudyDatabase(Path(directory) / "report.db")
            self._add_session(db, "2026-06-03 10:00:00", 1200, True, "六月同期")
            self._add_session(db, "2026-06-28 10:00:00", 3600, True, "六月后段")
            self._add_session(db, "2026-07-03 10:00:00", 1800, True, "七月")
            report = StudyReportService(db, today_provider=lambda: date(2026, 7, 10)).build("month", "2026-07")

            self.assertTrue(report["is_current"])
            self.assertEqual("上月同期", report["comparison"]["previous_label"])
            self.assertEqual(600, report["comparison"]["focus_delta_seconds"])

    def test_empty_report_has_supportive_local_narrative(self):
        with TemporaryDirectory() as directory:
            db = StudyDatabase(Path(directory) / "report.db")
            report = StudyReportService(db, today_provider=lambda: date(2026, 7, 26)).build("week", "2026-07-20")

            self.assertEqual(0, report["metrics"]["sessions"])
            self.assertEqual("从一小段开始就很好", report["narrative"]["title"])
            self.assertFalse(report["comparison"]["has_previous_data"])


if __name__ == "__main__":
    unittest.main()
