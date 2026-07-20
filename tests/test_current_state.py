import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from brain import current_state
from brain import graph_memory
from brain import tools as memory_tools
from memory.history_manager import HistoryManager


class CurrentStateLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db_path = graph_memory._DB_PATH
        self._old_conn = getattr(graph_memory._local, "conn", None)
        graph_memory._local.conn = None
        graph_memory._DB_PATH = Path(self._tmp.name) / "current-state.db"
        self.now = datetime(2026, 7, 20, 10, 0, tzinfo=timezone(timedelta(hours=8)))

    def tearDown(self):
        conn = getattr(graph_memory._local, "conn", None)
        if conn is not None:
            conn.close()
        graph_memory._local.conn = self._old_conn
        graph_memory._DB_PATH = self._old_db_path
        self._tmp.cleanup()

    def test_state_lifecycle_keeps_provenance_and_expires(self):
        state = current_state.set_current_state(
            "用户正在感冒，嗓子疼", "health", duration_days=2,
            source_session_id=17, source_channel="qq_private",
            source_message_ids=[41], persona_id="limina",
            observed_at="2026-07-20 09:59:00", now=self.now,
        )

        self.assertEqual("created", state["operation"])
        self.assertEqual([41], state["source_message_ids"])
        self.assertIn("用户正在感冒", current_state.format_current_state_context(now=self.now))
        events = current_state.get_state_events(state["id"])
        self.assertEqual(["set"], [event["action"] for event in events])
        self.assertEqual([41], events[0]["source_message_ids"])

        count = current_state.expire_current_states(now=self.now + timedelta(days=3))

        self.assertEqual(1, count)
        self.assertEqual([], current_state.list_current_states(now=self.now + timedelta(days=3)))
        events = current_state.get_state_events(state["id"])
        self.assertEqual(["set", "expire"], [event["action"] for event in events])

    def test_expiry_is_validated_capped_and_inference_confidence_is_limited(self):
        state = current_state.set_current_state(
            "用户可能在推进一个短期项目", "project",
            expires_at=(self.now + timedelta(days=120)).isoformat(),
            confidence=0.95, source_quality="inferred", now=self.now,
        )
        expiry = datetime.fromisoformat(state["expires_at"])

        self.assertLessEqual(expiry, self.now + timedelta(days=90))
        self.assertEqual(0.6, state["confidence"])
        with self.assertRaises(ValueError):
            current_state.set_current_state(
                "已经过时的状态",
                expires_at=(self.now - timedelta(minutes=1)).isoformat(),
                now=self.now,
            )

    def test_update_preserves_missing_provenance_then_resolve_audits_reason(self):
        state = current_state.set_current_state(
            "用户在上海出差", "location", source_session_id=9,
            source_channel="desktop", source_message_ids=[10],
            persona_id="lianxin", now=self.now,
        )
        updated = current_state.update_current_state(
            state["id"], content="用户在杭州出差", confidence=0.75,
            source_quality="user_confirmed", now=self.now + timedelta(hours=1)
        )

        self.assertEqual(9, updated["source_session_id"])
        self.assertEqual([10], updated["source_message_ids"])
        self.assertEqual(0.75, updated["confidence"])
        self.assertEqual("user_confirmed", updated["source_quality"])
        resolved = current_state.resolve_current_state(
            state["id"], "用户已回家", source_message_ids=[12],
            now=self.now + timedelta(days=1),
        )

        self.assertEqual("resolved", resolved["status"])
        self.assertEqual([], current_state.list_current_states(now=self.now + timedelta(days=1)))
        events = current_state.get_state_events(state["id"])
        self.assertEqual(["set", "update", "resolve"], [event["action"] for event in events])
        self.assertEqual("用户已回家", events[-1]["reason"])

    def test_near_duplicate_confirms_instead_of_creating_another_state(self):
        first = current_state.set_current_state(
            "用户这周正在准备产品发布", "project", now=self.now
        )
        second = current_state.set_current_state(
            "用户这周正在准备产品发布", "project",
            source_message_ids=[2], now=self.now + timedelta(hours=1),
        )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual("duplicate", second["operation"])
        self.assertEqual(1, len(current_state.list_current_states(now=self.now)))
        self.assertEqual(
            ["set", "confirm"],
            [event["action"] for event in current_state.get_state_events(first["id"])],
        )

    def test_active_state_limit_is_enforced_by_code(self):
        distinct_states = [
            "用户正在感冒并且嗓子疼",
            "用户本周临时住在杭州",
            "用户正在准备产品发布",
            "用户计划周末去爬山",
            "用户最近在照顾生病的猫",
            "用户今天心情有些低落",
            "用户正等待一份面试结果",
            "用户月底之前需要搬家",
            "用户正在学习新的绘画软件",
            "用户与朋友暂时有些误会",
            "用户这几天需要早起开会",
            "用户目前在维修自己的电脑",
        ]
        for content in distinct_states:
            current_state.set_current_state(
                content, "other", now=self.now
            )

        with self.assertRaises(ValueError):
            current_state.set_current_state(
                "超过上限的临时状态", "other", now=self.now
            )


class CurrentStateToolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db_path = graph_memory._DB_PATH
        self._old_conn = getattr(graph_memory._local, "conn", None)
        graph_memory._local.conn = None
        graph_memory._DB_PATH = Path(self._tmp.name) / "current-state.db"
        self.history = HistoryManager(Path(self._tmp.name) / "history.db")
        self.session_id = self.history.new_session(
            channel="qq_private", participant_id="owner", owner_scope=True
        )
        self.message_id = self.history.save_message(
            self.session_id, "user", "我这两天感冒了，嗓子有点痛"
        )
        self._old_context = getattr(memory_tools._tool_context, "cross_session", None)
        memory_tools.set_cross_session_context(self.session_id, self.history)

    def tearDown(self):
        if self._old_context is None:
            try:
                del memory_tools._tool_context.cross_session
            except AttributeError:
                pass
        else:
            memory_tools._tool_context.cross_session = self._old_context
        self.history.close()
        conn = getattr(graph_memory._local, "conn", None)
        if conn is not None:
            conn.close()
        graph_memory._local.conn = self._old_conn
        graph_memory._DB_PATH = self._old_db_path
        self._tmp.cleanup()

    def test_tool_is_registered_and_captures_exact_source_message(self):
        names = {item["function"]["name"] for item in memory_tools.TOOL_DEFINITIONS}
        self.assertIn("update_current_state", names)
        self.assertIn("update_current_state", memory_tools.TOOL_EXECUTORS)

        result = memory_tools.manage_current_state(
            "set", content="用户这两天感冒且嗓子疼",
            state_type="health", duration_days=2,
        )

        self.assertIn("已记录当前状态", result)
        state = current_state.list_current_states()[0]
        self.assertEqual(self.session_id, state["source_session_id"])
        self.assertEqual("qq_private", state["source_channel"])
        self.assertEqual([self.message_id], state["source_message_ids"])


if __name__ == "__main__":
    unittest.main()
