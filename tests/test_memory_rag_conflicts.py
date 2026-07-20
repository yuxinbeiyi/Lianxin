import unittest

from brain.memory_rag import format_rag_context


class MemoryRagConflictFormattingTests(unittest.TestCase):
    def test_known_contradiction_is_explicitly_exposed_to_model(self):
        context = format_rag_context([(
            0.9,
            {
                "memory_id": 2,
                "content": "用户住在杭州",
                "source": "user_saved",
                "semantic_similarity": 0.91,
                "evidence_count": 1,
                "fact_relations": [{
                    "relation": "contradicts",
                    "source_fact_id": 2,
                    "target_fact_id": 1,
                    "source_content": "用户住在杭州",
                    "target_content": "用户住在上海",
                }],
            },
        )])

        self.assertIn("已识别的语义矛盾", context)
        self.assertIn("记忆#1", context)
        self.assertIn("不得擅自选择", context)


if __name__ == "__main__":
    unittest.main()
