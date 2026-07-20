import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from brain import graph_memory


class MemoryQualityMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = graph_memory._DB_PATH
        self.old_local = graph_memory._local
        graph_memory._DB_PATH = Path(self.tmp.name) / "quality.db"
        graph_memory._local = __import__("threading").local()
        self.old_rag = sys.modules.get("brain.memory_rag")
        fake_rag = types.ModuleType("brain.memory_rag")
        fake_rag.embed_bytes = lambda _text: None
        fake_rag.search_similar = lambda *args, **kwargs: []
        sys.modules["brain.memory_rag"] = fake_rag
        self.now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone(timedelta(hours=8)))

    def tearDown(self):
        conn = getattr(graph_memory._local, "conn", None)
        if conn is not None:
            conn.close()
        graph_memory._DB_PATH = self.old_path
        graph_memory._local = self.old_local
        if self.old_rag is None:
            sys.modules.pop("brain.memory_rag", None)
        else:
            sys.modules["brain.memory_rag"] = self.old_rag
        self.tmp.cleanup()

    def test_quality_score_explains_evidence_and_access(self):
        from brain.memory_quality import (
            calculate_memory_quality, record_memory_access,
            recalculate_memory_quality,
        )

        fact_id = graph_memory.add_fact(
            "用户喜欢爵士乐", "preferences", source="user_saved"
        )
        graph_memory.add_memory_fragment(
            fact_id, "用户喜欢爵士乐", "preferences",
            source="user_saved", confidence=0.95,
        )
        before = calculate_memory_quality(fact_id, now=self.now)
        self.assertGreater(before["score"], 0.65)
        self.assertEqual(1, before["breakdown"]["evidence_count"])

        self.assertEqual(1, record_memory_access([fact_id]))
        persisted = recalculate_memory_quality(now=self.now)
        row = graph_memory.get_fact_by_id(fact_id)
        self.assertEqual(1, row["access_count"])
        self.assertEqual("normal", row["review_status"])
        self.assertEqual(1, persisted["updated"])

    def test_low_evidence_auto_fact_is_marked_without_deletion(self):
        from brain.memory_quality import recalculate_memory_quality

        fact_id = graph_memory.add_fact(
            "自动推断用户可能喜欢某种音乐", "preferences",
            source="auto_extracted",
        )
        recalculate_memory_quality(now=self.now)
        row = graph_memory.get_fact_by_id(fact_id)
        self.assertEqual("low_evidence", row["review_status"])
        self.assertEqual("active", row["status"])

    def test_maintenance_is_idempotent_and_expires_state_and_source_refs(self):
        from brain.current_state import set_current_state
        from brain.memory_maintenance import (
            get_last_maintenance_run, run_memory_maintenance,
            should_run_maintenance,
        )

        conn = graph_memory._get_conn()
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO messages(id) VALUES (1)")
        fact_id = graph_memory.add_fact("用户今天需要开会", "events")
        graph_memory.add_memory_fragment(
            fact_id, "用户今天需要开会", "events", source_message_ids=[1, 999]
        )
        state = set_current_state("用户今天需要开会", "plan", duration_days=1, now=self.now)

        result = run_memory_maintenance(
            trigger="test", conflict_scan_batch=2,
            now=self.now + timedelta(days=2),
        )

        self.assertEqual("success", result["status"])
        self.assertEqual(1, result["current_states_expired"])
        fragment = graph_memory.get_fact_fragments(fact_id, include_inactive=True)[0]
        self.assertEqual([1], fragment["source_message_ids"])
        self.assertIsNotNone(get_last_maintenance_run())
        self.assertFalse(should_run_maintenance(6, now=datetime.now().astimezone()))

        second = run_memory_maintenance(trigger="test", conflict_scan_batch=2, now=self.now)
        self.assertEqual("success", second["status"])
        self.assertEqual([], graph_memory._get_conn().execute(
            "SELECT id FROM memory_current_states WHERE status='active'"
        ).fetchall())


class MemoryMaintenanceDutyTests(unittest.TestCase):
    def test_duty_waits_for_idle_and_interval(self):
        from utils.duty_scheduler import MemoryMaintenanceDuty

        duty = MemoryMaintenanceDuty()
        state = SimpleNamespace(
            agent_busy=True, last_user_message_time=0, now=1000,
        )
        self.assertFalse(duty._should_fire(state))
        state.agent_busy = False
        state.last_user_message_time = 950
        self.assertFalse(duty._should_fire(state))

    def test_duty_can_be_disabled_by_memory_config(self):
        from utils.duty_scheduler import MemoryMaintenanceDuty

        duty = MemoryMaintenanceDuty()
        with patch(
            "config.get_memory_config",
            return_value={"maintenance_enabled": False},
        ):
            self.assertFalse(duty._check_enabled(SimpleNamespace()))


if __name__ == "__main__":
    unittest.main()
