import tempfile
import unittest
import sys
import threading
import types
from datetime import datetime, timedelta
from pathlib import Path

from brain.decision import decide
from memory.history_manager import HistoryManager
from brain import graph_memory


class ConversationHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "conversations.db"
        self.mgr = HistoryManager(self.db_path)

    def tearDown(self):
        self.mgr.close()
        self._tmp.cleanup()

    def _set_message_time(self, session_id: int, timestamp: datetime):
        value = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        conn = self.mgr._conn()
        conn.execute("UPDATE messages SET timestamp=? WHERE session_id=?", (value, session_id))
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (value, session_id))
        conn.commit()

    def test_latest_session_uses_activity_not_creation_order(self):
        older_id = self.mgr.new_session(channel="desktop")
        self.mgr.save_message(older_id, "user", "continued later")
        newer_id = self.mgr.new_session(channel="desktop")
        self.mgr.save_message(newer_id, "user", "created later but inactive")

        self._set_message_time(older_id, datetime.now())
        self._set_message_time(newer_id, datetime.now() - timedelta(days=1))

        self.assertEqual(
            older_id,
            self.mgr.get_latest_session_id(channel="desktop", owner_only=True),
        )

    def test_legacy_database_is_backed_up_before_schema_migration(self):
        legacy_path = Path(self._tmp.name) / "legacy.db"
        import sqlite3
        conn = sqlite3.connect(legacy_path)
        conn.executescript("""
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            INSERT INTO sessions(title, created_at) VALUES ('legacy', '2026-07-16 10:00:00');
            INSERT INTO messages(session_id, role, content, timestamp)
            VALUES (1, 'user', 'legacy message', '2026-07-16 10:00:00');
        """)
        conn.commit()
        conn.close()

        legacy_mgr = HistoryManager(legacy_path)
        legacy_mgr.get_sessions()
        legacy_mgr.close()
        self.assertTrue((Path(self._tmp.name) / "legacy.pre-memory-v3.db").exists())

    def test_recent_search_respects_time_channel_and_owner_scope(self):
        desktop = self.mgr.new_session(channel="desktop", owner_scope=True)
        qq_owner = self.mgr.new_session(
            channel="qq_private", participant_id="owner", owner_scope=True
        )
        qq_friend = self.mgr.new_session(
            channel="qq_private", participant_id="friend", owner_scope=False
        )
        self.mgr.save_message(desktop, "user", "desktop recent")
        self.mgr.save_message(qq_owner, "user", "owner qq recent")
        self.mgr.save_message(qq_friend, "user", "private friend content")

        rows = self.mgr.search_conversation_history(
            mode="recent", time_range="7d", owner_only=True, limit=20
        )
        contents = [row["content"] for row in rows]
        self.assertIn("desktop recent", contents)
        self.assertIn("owner qq recent", contents)
        self.assertNotIn("private friend content", contents)

        qq_rows = self.mgr.search_conversation_history(
            mode="recent", channels=["qq_private"], owner_only=True, limit=20
        )
        self.assertEqual(["owner qq recent"], [row["content"] for row in qq_rows])

    def test_yesterday_is_a_time_filter_not_a_keyword(self):
        session_id = self.mgr.new_session(channel="desktop")
        self.mgr.save_message(session_id, "user", "a message without relative time words")
        yesterday = datetime.now() - timedelta(days=1)
        self._set_message_time(session_id, yesterday)

        rows = self.mgr.search_conversation_history(
            mode="recent", time_range="yesterday", owner_only=True
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("a message without relative time words", rows[0]["content"])

    def test_diary_messages_aggregate_owner_sessions_only(self):
        date_str = datetime.now().strftime("%Y-%m-%d")
        first = self.mgr.new_session(channel="desktop", owner_scope=True)
        second = self.mgr.new_session(channel="qq_private", owner_scope=True)
        outsider = self.mgr.new_session(channel="qq_private", owner_scope=False)
        self.mgr.save_message(first, "user", "desktop diary source")
        self.mgr.save_message(second, "user", "qq diary source")
        self.mgr.save_message(outsider, "user", "must stay private")

        rows = self.mgr.get_messages_by_date(date_str, owner_only=True)
        contents = [row["content"] for row in rows]
        self.assertIn("desktop diary source", contents)
        self.assertIn("qq diary source", contents)
        self.assertNotIn("must stay private", contents)

    def test_recent_chat_question_routes_to_agent(self):
        self.assertEqual("agent", decide("最近我们聊了什么"))
        self.assertEqual("agent", decide("我们昨天说了什么"))


class LongTermMemoryConsistencyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db_path = graph_memory._DB_PATH
        self._old_local = graph_memory._local
        graph_memory._DB_PATH = Path(self._tmp.name) / "memory.db"
        graph_memory._local = threading.local()
        self._old_rag_module = sys.modules.get("brain.memory_rag")
        fake_rag = types.ModuleType("brain.memory_rag")
        fake_rag.embed_bytes = lambda text: f"vec:{text}".encode("utf-8")
        fake_rag.find_similar_memory = lambda *args, **kwargs: None
        sys.modules["brain.memory_rag"] = fake_rag

    def tearDown(self):
        conn = getattr(graph_memory._local, "conn", None)
        if conn is not None:
            conn.close()
        graph_memory._DB_PATH = self._old_db_path
        graph_memory._local = self._old_local
        if self._old_rag_module is None:
            sys.modules.pop("brain.memory_rag", None)
        else:
            sys.modules["brain.memory_rag"] = self._old_rag_module
        self._tmp.cleanup()

    def test_fact_update_refreshes_embedding_and_metadata(self):
        fact_id = graph_memory.add_fact(
            "old fact", "knowledge", source="auto_extracted",
            source_session_id=42, source_channel="desktop",
        )
        self.assertGreater(fact_id, 0)
        self.assertEqual(1, graph_memory.update_facts("old fact", "new fact", "knowledge"))

        row = graph_memory._get_conn().execute(
            """SELECT content, embedding, source_session_id, source_channel,
                      status, updated_at
               FROM memory_facts WHERE id=?""",
            (fact_id,),
        ).fetchone()
        self.assertEqual("new fact", row["content"])
        self.assertEqual(b"vec:new fact", row["embedding"])
        self.assertEqual(42, row["source_session_id"])
        self.assertEqual("desktop", row["source_channel"])
        self.assertEqual("active", row["status"])
        self.assertTrue(row["updated_at"])


if __name__ == "__main__":
    unittest.main()
