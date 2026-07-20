import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brain import tools as memory_tools
from memory.history_manager import HistoryManager


class MemoryProvenanceToolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.mgr = HistoryManager(Path(self._tmp.name) / "history.db")
        self.session_id = self.mgr.new_session(
            channel="qq_private", participant_id="owner", owner_scope=True
        )
        self.message_id = self.mgr.save_message(
            self.session_id, "user", "the exact source statement"
        )
        self._old_context = getattr(memory_tools._tool_context, "cross_session", None)
        memory_tools.set_cross_session_context(self.session_id, self.mgr)

    def tearDown(self):
        if self._old_context is None:
            try:
                del memory_tools._tool_context.cross_session
            except AttributeError:
                pass
        else:
            memory_tools._tool_context.cross_session = self._old_context
        self.mgr.close()
        self._tmp.cleanup()

    @staticmethod
    def _fact():
        return {"id": 5, "content": "remembered fact"}

    def _fragment(self, source_message_ids):
        return [{
            "id": 8,
            "source_channel": "qq_private",
            "source_message_ids": source_message_ids,
            "confidence": 0.93,
            "status": "active",
            "persona_id": "limina",
        }]

    def test_trace_memory_source_resolves_exact_original_message(self):
        with patch.object(
            memory_tools, "get_fact_by_id", return_value=self._fact()
        ), patch.object(
            memory_tools,
            "get_fact_fragments",
            return_value=self._fragment([self.message_id]),
        ):
            result = memory_tools.trace_memory_source(5)

        self.assertIn("remembered fact", result)
        self.assertIn("the exact source statement", result)
        self.assertIn(f"#{self.message_id}", result)
        self.assertIn("qq_private", result)
        self.assertIn("limina", result)

    def test_trace_memory_source_does_not_invent_nearby_evidence(self):
        with patch.object(
            memory_tools, "get_fact_by_id", return_value=self._fact()
        ), patch.object(
            memory_tools,
            "get_fact_fragments",
            return_value=self._fragment([]),
        ):
            result = memory_tools.trace_memory_source(5)

        self.assertIn("remembered fact", result)
        self.assertNotIn("the exact source statement", result)

    def test_trace_memory_source_is_blocked_for_non_owner_session(self):
        outsider_session_id = self.mgr.new_session(
            channel="qq_private", participant_id="friend", owner_scope=False
        )
        memory_tools.set_cross_session_context(outsider_session_id, self.mgr)
        with patch.object(
            memory_tools, "get_fact_by_id", return_value=self._fact()
        ), patch.object(
            memory_tools,
            "get_fact_fragments",
            return_value=self._fragment([self.message_id]),
        ):
            result = memory_tools.trace_memory_source(5)

        self.assertNotIn("the exact source statement", result)

    def test_trace_tool_is_registered_for_function_calling(self):
        definition_names = {
            item["function"]["name"] for item in memory_tools.TOOL_DEFINITIONS
        }
        self.assertIn("trace_memory_source", definition_names)
        self.assertIn("trace_memory_source", memory_tools.TOOL_EXECUTORS)


if __name__ == "__main__":
    unittest.main()
