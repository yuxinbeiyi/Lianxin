import threading
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from brain import graph_memory


class NarrativeHybridTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = graph_memory._DB_PATH
        self.old_local = graph_memory._local
        graph_memory._DB_PATH = Path(self.tmp.name) / "narrative.db"
        graph_memory._local = threading.local()

    def tearDown(self):
        conn = getattr(graph_memory._local, "conn", None)
        if conn:
            conn.close()
        graph_memory._DB_PATH = self.old_path
        graph_memory._local = self.old_local
        self.tmp.cleanup()

    def test_model_result_creates_episode_and_entity_without_deleting_fragments(self):
        from brain.memory_narrative import (
            apply_narrative_result, collect_narrative_candidates,
            list_entity_profiles, list_episodes,
        )
        fact_id = graph_memory.add_fact("莲心项目使用 Python", "knowledge", source="auto_extracted")
        graph_memory.add_memory_fragment(fact_id, "莲心项目使用 Python", "knowledge", source="auto_extracted")
        fact_id2 = graph_memory.add_fact("莲心项目正在重构记忆系统", "events", source="auto_extracted")
        graph_memory.add_memory_fragment(fact_id2, "莲心项目正在重构记忆系统", "events", source="auto_extracted")
        candidates = collect_narrative_candidates()
        result = apply_narrative_result({
            "entities": [{"name": "莲心项目", "entity_type": "project", "summary": "正在重构记忆系统", "confidence": .9}],
            "episodes": [{"title": "莲心记忆系统重构", "summary": "莲心项目使用 Python 并正在重构记忆系统。", "fragment_ids": [c["id"] for c in candidates], "entities": [{"name": "莲心项目", "entity_type": "project"}], "confidence": .85}],
            "sagas": [],
        }, candidates)
        self.assertEqual(1, result["episodes_created"])
        self.assertEqual(1, len(list_episodes()))
        self.assertTrue(list_entity_profiles())
        self.assertEqual("active", graph_memory._get_conn().execute("SELECT status FROM memory_fragments").fetchone()[0])

    def test_hybrid_retrieval_uses_keyword_channel_when_embedding_unavailable(self):
        from brain.memory_rag import search_similar
        graph_memory.add_fact("用户喜欢手冲咖啡", "preferences", source="user_saved")
        with patch("brain.memory_rag._get_model", return_value=None), patch("brain.memory_rag._load_attempted", True):
            results = search_similar("咖啡", top_k=3)
        self.assertTrue(results)
        self.assertIn("用户喜欢手冲咖啡", results[0][1]["content"])
        self.assertEqual("general", results[0][1]["retrieval_intent"])

    def test_working_memory_archives_topic_switch_and_keeps_open_loop(self):
        from brain.working_memory import get_working_topic, update_working_topic
        first = update_working_topic(
            user_message="我们继续讨论记忆系统的 Episode 设计？",
            recent_messages=[{"role": "user", "content": "我们继续讨论记忆系统的 Episode 设计？"}],
            session_id=1,
        )
        self.assertTrue(first["open_loops"])
        second = update_working_topic(
            user_message="今天天气怎么样",
            recent_messages=[{"role": "user", "content": "今天天气怎么样"}],
            session_id=1,
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual("archived", graph_memory._get_conn().execute("SELECT status FROM memory_working_topics WHERE id=?", (first["id"],)).fetchone()[0])
        self.assertEqual(second["id"], get_working_topic()["id"])

    def test_working_memory_isolated_between_sessions(self):
        from brain.working_memory import update_working_topic
        desktop = update_working_topic(user_message="讨论莲心记忆", session_id=11)
        qq = update_working_topic(user_message="讨论莲心记忆", session_id=22)
        self.assertNotEqual(desktop["id"], qq["id"])
        rows = graph_memory._get_conn().execute("SELECT COUNT(*) FROM memory_working_topics WHERE status='active'").fetchone()[0]
        self.assertEqual(2, rows)

    def test_entity_query_uses_entity_profile_channel(self):
        from brain.memory_narrative import apply_narrative_result, collect_narrative_candidates
        from brain.memory_rag import search_similar
        fact_id = graph_memory.add_fact("莲心项目正在升级", "events")
        graph_memory.add_memory_fragment(fact_id, "莲心项目正在升级", "events")
        candidate = collect_narrative_candidates()[0]
        apply_narrative_result({"entities": [{"name": "莲心项目", "entity_type": "project", "summary": "正在升级"}], "episodes": [], "sagas": []}, [candidate])
        with patch("brain.memory_rag._get_model", return_value=None), patch("brain.memory_rag._load_attempted", True):
            results = search_similar("莲心项目是谁", top_k=5)
        self.assertTrue(any(item[1].get("source_table") == "memory_entity_profiles" for item in results))

    def test_cross_batch_episode_merge_preserves_all_fragment_ids(self):
        from brain.memory_narrative import apply_narrative_result, collect_narrative_candidates, list_episodes, merge_narrative_duplicates
        candidates = []
        for content in ("旅行计划去杭州", "旅行计划安排西湖", "旅行计划准备相机", "旅行计划查看天气"):
            fact_id = graph_memory.add_fact(content, "events")
            graph_memory.add_memory_fragment(fact_id, content, "events")
        all_candidates = collect_narrative_candidates()
        first, second = all_candidates[:2], all_candidates[2:]
        apply_narrative_result({"entities": [{"name": "杭州旅行", "entity_type": "event"}], "episodes": [{"title": "杭州旅行计划", "summary": "计划去杭州并安排西湖", "fragment_ids": [x["id"] for x in first], "entities": [{"name": "杭州旅行", "entity_type": "event"}]}], "sagas": []}, first)
        apply_narrative_result({"entities": [{"name": "杭州旅行", "entity_type": "event"}], "episodes": [{"title": "杭州旅行安排", "summary": "准备相机并查看天气", "fragment_ids": [x["id"] for x in second], "entities": [{"name": "杭州旅行", "entity_type": "event"}]}], "sagas": []}, second)
        stats = merge_narrative_duplicates()
        self.assertEqual(1, stats["episodes_merged"])
        active = [episode for episode in list_episodes() if episode["status"] == "active"]
        self.assertEqual(1, len(active))


if __name__ == "__main__":
    unittest.main()
