import threading
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from brain import graph_memory


class MemoryLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = graph_memory._DB_PATH
        self.old_local = graph_memory._local
        graph_memory._DB_PATH = Path(self.tmp.name) / "lifecycle.db"
        graph_memory._local = threading.local()
        self.now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone(timedelta(hours=8)))

    def tearDown(self):
        conn = getattr(graph_memory._local, "conn", None)
        if conn:
            conn.close()
        graph_memory._DB_PATH = self.old_path
        graph_memory._local = self.old_local
        self.tmp.cleanup()

    def test_emotional_weight_changes_decay_horizon_and_retire_can_restore(self):
        from brain.memory_quality import calculate_memory_quality, restore_memory, retire_memory, set_memory_emotional_weight
        fact_id = graph_memory.add_fact("一条重要的长期计划", "events", source="user_saved")
        graph_memory.add_memory_fragment(fact_id, "一条重要的长期计划", "events", source="user_saved", confidence=1.0)
        conn = graph_memory._get_conn()
        old = (self.now - timedelta(days=500)).isoformat()
        conn.execute("UPDATE memory_facts SET created_at=?,updated_at=? WHERE id=?", (old, old, fact_id))
        conn.commit()
        low = set_memory_emotional_weight(fact_id, 0.1)
        high = set_memory_emotional_weight(fact_id, 1.0)
        self.assertGreater(high["breakdown"]["decay_horizon_days"], low["breakdown"]["decay_horizon_days"])
        self.assertTrue(retire_memory(fact_id, "用户确认不再适用"))
        self.assertEqual("retired", graph_memory.get_fact_by_id(fact_id)["status"])
        self.assertTrue(restore_memory(fact_id))
        self.assertEqual("active", graph_memory.get_fact_by_id(fact_id)["status"])

    def test_model_working_summary_is_used_but_code_fallback_remains(self):
        from brain.working_memory import apply_model_summary, format_working_memory_context, update_working_topic
        topic = update_working_topic(user_message="继续设计记忆检索", session_id=4)
        apply_model_summary(topic["id"], summary="正在完成 FTS5 检索接入", facts=["数据库迁移需要兼容旧版本"], open_loops=["补充回归测试"], task_state="executing")
        refreshed = update_working_topic(user_message="继续设计记忆检索", session_id=4)
        context = format_working_memory_context(refreshed)
        self.assertIn("正在完成 FTS5 检索接入", context)
        self.assertIn("executing", context)
        self.assertIn("补充回归测试", context)


if __name__ == "__main__":
    unittest.main()
