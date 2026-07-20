import sys
import tempfile
import types
import unittest
from pathlib import Path

from brain import graph_memory


class MemoryConflictTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = graph_memory._DB_PATH
        self.old_local = graph_memory._local
        graph_memory._DB_PATH = Path(self.tmp.name) / "conflicts.db"
        graph_memory._local = __import__("threading").local()
        self.old_rag = sys.modules.get("brain.memory_rag")
        fake_rag = types.ModuleType("brain.memory_rag")
        fake_rag.embed_bytes = lambda text: None
        fake_rag.search_similar = lambda *args, **kwargs: []
        sys.modules["brain.memory_rag"] = fake_rag

        # Imported after the DB swap so all functions use the isolated connection.
        from brain import memory_conflicts
        self.conflicts = memory_conflicts

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

    def _related_facts(self):
        old_id = graph_memory.add_fact("用户目前居住在上海市", "profile")
        graph_memory.add_memory_fragment(
            old_id, "用户目前居住在上海市", "profile",
            source_message_ids=[10], confidence=0.95,
        )
        new_id = graph_memory.add_fact("用户目前居住在杭州市", "profile")
        graph_memory.add_memory_fragment(
            new_id, "用户目前居住在杭州市", "profile",
            source_message_ids=[20], confidence=0.95,
        )
        candidates = self.conflicts.list_conflict_candidates(status="pending")
        self.assertEqual(1, len(candidates))
        return old_id, new_id, candidates[0]

    def test_semantic_similarity_creates_candidate_without_rule_based_merge(self):
        old_id, new_id, candidate = self._related_facts()

        self.assertNotEqual(old_id, new_id)
        self.assertEqual(old_id, candidate["existing_fact_id"])
        self.assertEqual(new_id, candidate["new_fact_id"])
        self.assertEqual("active", graph_memory.get_fact_by_id(old_id)["status"])
        self.assertEqual("active", graph_memory.get_fact_by_id(new_id)["status"])

    def test_high_confidence_supersedes_is_atomic_and_audited(self):
        old_id, new_id, candidate = self._related_facts()

        result = self.conflicts.resolve_conflict_candidate(
            candidate["id"], "supersedes", confidence=0.94,
            rationale="用户明确说明已经从上海搬到杭州，新地点取代旧地点",
            review_model="test-model", source_session_id=7,
            source_channel="desktop", source_message_ids=[20], persona_id="limina",
        )

        self.assertTrue(result["applied"])
        self.assertEqual("resolved", result["status"])
        self.assertEqual("superseded", graph_memory.get_fact_by_id(old_id)["status"])
        self.assertEqual("active", graph_memory.get_fact_by_id(new_id)["status"])
        old_fragments = graph_memory.get_fact_fragments(old_id, include_inactive=True)
        self.assertTrue(old_fragments)
        self.assertTrue(all(item["status"] == "superseded" for item in old_fragments))
        relations = self.conflicts.get_fact_relations(new_id)
        self.assertEqual("supersedes", relations[0]["relation"])
        self.assertEqual(old_id, relations[0]["target_fact_id"])
        self.assertEqual([20], result["source_message_ids"])
        visible_profile = graph_memory.list_all_facts()["profile"]
        self.assertEqual([new_id], [item["id"] for item in visible_profile])

    def test_low_confidence_destructive_decision_never_changes_facts(self):
        old_id, new_id, candidate = self._related_facts()

        result = self.conflicts.resolve_conflict_candidate(
            candidate["id"], "supersedes", confidence=0.61,
            rationale="句子相似，但无法确定时间关系",
        )

        self.assertFalse(result["applied"])
        self.assertEqual("needs_confirmation", result["status"])
        self.assertEqual("active", graph_memory.get_fact_by_id(old_id)["status"])
        self.assertEqual("active", graph_memory.get_fact_by_id(new_id)["status"])
        self.assertEqual([], self.conflicts.get_fact_relations(new_id))
        first_events = self.conflicts.get_conflict_events(candidate["id"])
        self.assertEqual(1, len(first_events))
        self.assertFalse(first_events[0]["applied"])

        confirmed = self.conflicts.resolve_conflict_candidate(
            candidate["id"], "supersedes", confidence=0.96,
            rationale="用户随后明确确认杭州已经取代上海",
            source_message_ids=[21],
        )
        self.assertTrue(confirmed["applied"])
        self.assertEqual("superseded", graph_memory.get_fact_by_id(old_id)["status"])
        events = self.conflicts.get_conflict_events(candidate["id"])
        self.assertEqual([False, True], [item["applied"] for item in events])
        self.assertEqual([21], events[-1]["source_message_ids"])

    def test_duplicate_moves_evidence_but_keeps_audit_fact(self):
        old_id = graph_memory.add_fact("用户目前住在上海", "profile")
        graph_memory.add_memory_fragment(
            old_id, "用户目前住在上海", "profile", source_message_ids=[30]
        )
        new_id = graph_memory.add_fact("用户现在居住在上海", "profile")
        graph_memory.add_memory_fragment(
            new_id, "用户现在居住在上海", "profile", source_message_ids=[31]
        )
        candidate = self.conflicts.list_conflict_candidates(status="pending")[0]

        result = self.conflicts.resolve_conflict_candidate(
            candidate["id"], "duplicate", confidence=0.91,
            rationale="两条内容表达同一居住事实，只是措辞不同",
        )

        self.assertTrue(result["applied"])
        self.assertEqual("duplicate", graph_memory.get_fact_by_id(new_id)["status"])
        self.assertEqual(2, len(graph_memory.get_fact_fragments(old_id)))
        self.assertEqual([], graph_memory.get_fact_fragments(new_id))
        self.assertEqual("duplicate", self.conflicts.get_fact_relations(new_id)[0]["relation"])

    def test_complements_keeps_both_facts_active(self):
        old_id, new_id, candidate = self._related_facts()

        result = self.conflicts.resolve_conflict_candidate(
            candidate["id"], "complements", confidence=0.88,
            rationale="两条事实描述不同时间范围，可以同时成立",
        )

        self.assertTrue(result["applied"])
        self.assertEqual("active", graph_memory.get_fact_by_id(old_id)["status"])
        self.assertEqual("active", graph_memory.get_fact_by_id(new_id)["status"])
        self.assertEqual("complements", self.conflicts.get_fact_relations(new_id)[0]["relation"])

    def test_exact_duplicate_is_strengthened_without_conflict_candidate(self):
        first_id = graph_memory.add_fact("用户喜欢爵士乐", "preferences")
        second_id = graph_memory.add_fact("用户喜欢爵士乐", "preferences")

        self.assertEqual(first_id, second_id)
        self.assertEqual([], self.conflicts.list_conflict_candidates(status="pending"))
        self.assertEqual(2, graph_memory.get_fact_by_id(first_id)["strength"])

    def test_save_tool_surfaces_candidate_and_review_tool_is_registered(self):
        from brain import tools as memory_tools

        memory_tools.save_memory("用户目前居住在上海市", "profile")
        result = memory_tools.save_memory("用户目前居住在杭州市", "profile")
        definition_names = {
            item["function"]["name"] for item in memory_tools.TOOL_DEFINITIONS
        }

        self.assertIn("可能相关的旧记忆", result)
        self.assertIn("候选#", result)
        self.assertIn("review_memory_conflict", result)
        self.assertIn("review_memory_conflict", definition_names)
        self.assertIn("review_memory_conflict", memory_tools.TOOL_EXECUTORS)


if __name__ == "__main__":
    unittest.main()
