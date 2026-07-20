import threading
import tempfile
import unittest
from pathlib import Path

from brain import graph_memory


class MemoryCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = graph_memory._DB_PATH
        self.old_local = graph_memory._local
        graph_memory._DB_PATH = Path(self.tmp.name) / "correction.db"
        graph_memory._local = threading.local()

    def tearDown(self):
        conn = getattr(graph_memory._local, "conn", None)
        if conn:
            conn.close()
        graph_memory._DB_PATH = self.old_path
        graph_memory._local = self.old_local
        self.tmp.cleanup()

    def test_update_marks_related_episode_and_entity_for_review(self):
        from brain.memory_corrections import list_correction_events
        from brain.memory_narrative import apply_narrative_result, collect_narrative_candidates

        fact = graph_memory.add_fact("项目使用旧框架", "knowledge")
        graph_memory.add_memory_fragment(fact, "项目使用旧框架", "knowledge", source_message_ids=[1])
        fact2 = graph_memory.add_fact("项目最近进行了架构调整", "events")
        graph_memory.add_memory_fragment(fact2, "项目最近进行了架构调整", "events", source_message_ids=[2])
        candidates = collect_narrative_candidates()
        apply_narrative_result({
            "entities": [],
            "episodes": [{"title": "架构调整", "summary": "项目使用旧框架并进行了架构调整", "fragment_ids": [row["id"] for row in candidates], "entities": [{"name": "项目", "entity_type": "project"}]}],
            "sagas": [],
        }, candidates)
        self.assertEqual(1, graph_memory.update_facts("旧框架", "项目使用新框架", "knowledge"))
        conn = graph_memory._get_conn()
        self.assertEqual("needs_review", conn.execute("SELECT status FROM memory_episodes").fetchone()[0])
        self.assertTrue(conn.execute("SELECT COUNT(*) FROM memory_correction_events").fetchone()[0])
        self.assertEqual("update", list_correction_events()[0]["action"])

    def test_delete_records_correction_before_removing_source_rows(self):
        from brain.memory_corrections import list_correction_events
        fact = graph_memory.add_fact("临时错误事实", "events")
        graph_memory.add_memory_fragment(fact, "临时错误事实", "events", source_message_ids=[3])
        self.assertEqual(1, graph_memory.delete_facts("临时错误事实", "events"))
        event = list_correction_events()[0]
        self.assertEqual("delete", event["action"])
        self.assertEqual([fact], event["fact_ids"])


if __name__ == "__main__":
    unittest.main()
