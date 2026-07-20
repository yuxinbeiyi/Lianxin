import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from brain.agent import AgentCore
from brain.tool_router import build_tool_catalog
from workers.qq_bridge_worker import QQBridgeWorker
from workers.wechat_bridge_worker import WeChatBridgeWorker, WeChatMessage


class OwnerMemoryBoundaryTests(unittest.TestCase):
    @staticmethod
    def _cloud_agent(owner_scope: bool) -> AgentCore:
        agent = AgentCore.__new__(AgentCore)
        agent.history = [{"role": "user", "content": "memory topic"}]
        agent._owner_scope = owner_scope
        agent._use_local = False
        agent._track_emotion = False
        agent._prev_session_summary = ""
        agent._request_memory_writes_blocked = not owner_scope
        agent._model = "test-model"
        agent._max_tokens = 200
        agent._api_key = "key"
        agent._api_base = "https://example.invalid"
        agent._last_reasoning = None
        agent._last_input_tokens = 0
        agent._build_request_system_messages = lambda _snapshot: []
        agent._build_realtime_message = lambda: {
            "role": "system", "content": "time"
        }
        agent._get_cross_session_context = lambda: None
        agent._apply_history_window = lambda _snapshot: (None, agent.history)
        agent._should_search_diary = lambda _message: 0
        return agent

    @staticmethod
    def _completion_stream():
        delta = SimpleNamespace(
            content="safe reply", reasoning_content=None, tool_calls=None
        )
        return [SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(delta=delta, finish_reason="stop")],
        )]

    def test_non_owner_cannot_reenable_memory_writes(self):
        agent = AgentCore.__new__(AgentCore)
        agent._owner_scope = False
        agent.history = []
        agent._session_memory_writes_blocked = True

        self.assertTrue(agent._derive_memory_write_policy())
        self.assertTrue(agent._update_memory_write_policy("allow memory again"))
        self.assertTrue(agent._session_memory_writes_blocked)

    def test_non_owner_cross_session_context_stops_before_file_access(self):
        agent = AgentCore.__new__(AgentCore)
        agent._owner_scope = False
        self.assertIsNone(agent._get_cross_session_context())

    def test_non_owner_auto_extraction_stops_before_starting_thread(self):
        agent = AgentCore.__new__(AgentCore)
        agent._owner_scope = False
        agent._use_local = False
        with patch("brain.agent.threading.Thread") as thread_cls:
            agent._trigger_auto_extraction()
        thread_cls.assert_not_called()

    def test_non_owner_memory_tool_is_blocked_at_execution_boundary(self):
        agent = AgentCore.__new__(AgentCore)
        agent._owner_scope = False
        agent._request_memory_writes_blocked = False
        agent._loop_tool_call_history = set()
        messages = []
        tool_call = SimpleNamespace(
            id="privacy-1",
            function=SimpleNamespace(
                name="search_graph_memory",
                arguments='{"keywords":["owner secret"]}',
            ),
        )

        with patch("brain.tools.execute_tool") as execute_tool:
            agent._execute_tool_calls_parallel([tool_call], messages)

        execute_tool.assert_not_called()
        self.assertEqual("tool", messages[0]["role"])
        self.assertIn("privacy-1", messages[0]["tool_call_id"])

    def test_non_owner_request_never_queries_rag_or_owner_graph(self):
        agent = self._cloud_agent(owner_scope=False)
        with patch(
            "brain.agent.get_active_tool_definitions", return_value=[]
        ), patch(
            "brain.agent.get_all_mcp_tool_definitions", return_value=[]
        ), patch(
            "brain.skill_manager.get_active_skill_summary", return_value=""
        ), patch(
            "brain.skill_manager.get_matching_knowledge", return_value=""
        ), patch(
            "brain.memory_rag.search_similar"
        ) as search_similar, patch(
            "brain.graph_memory.get_graph_summary_for_user"
        ) as graph_summary, patch(
            "brain.current_state.format_current_state_context"
        ) as current_state_context, patch(
            "brain.agent.litellm.completion",
            return_value=self._completion_stream(),
        ):
            result = agent._function_calling_loop(
                disable_tools=True, user_message="memory topic"
            )

        self.assertEqual("safe reply", result)
        search_similar.assert_not_called()
        graph_summary.assert_not_called()
        current_state_context.assert_not_called()

    def test_owner_request_still_receives_rag_and_graph_context(self):
        agent = self._cloud_agent(owner_scope=True)
        captured_messages = []

        def completion(**kwargs):
            captured_messages.extend(kwargs["messages"])
            return self._completion_stream()

        with patch(
            "brain.agent.get_active_tool_definitions", return_value=[]
        ), patch(
            "brain.agent.get_all_mcp_tool_definitions", return_value=[]
        ), patch(
            "brain.skill_manager.get_active_skill_summary", return_value=""
        ), patch(
            "brain.skill_manager.get_matching_knowledge", return_value=""
        ), patch(
            "brain.memory_rag.search_similar", return_value=[(0.9, {"content": "x"})]
        ) as search_similar, patch(
            "brain.memory_rag.format_rag_context", return_value="OWNER_RAG_CONTEXT"
        ), patch(
            "brain.graph_memory.get_graph_summary_for_user",
            return_value="OWNER_GRAPH_CONTEXT",
        ) as graph_summary, patch(
            "brain.current_state.format_current_state_context",
            return_value="OWNER_CURRENT_STATE_CONTEXT",
        ) as current_state_context, patch(
            "brain.agent.litellm.completion", side_effect=completion
        ):
            result = agent._function_calling_loop(
                disable_tools=True, user_message="memory topic"
            )

        self.assertEqual("safe reply", result)
        search_similar.assert_called_once()
        graph_summary.assert_called_once_with(depth=2)
        current_state_context.assert_called_once_with()
        contents = [message.get("content", "") for message in captured_messages]
        self.assertIn("OWNER_RAG_CONTEXT", contents)
        self.assertIn("OWNER_GRAPH_CONTEXT", contents)
        self.assertIn("OWNER_CURRENT_STATE_CONTEXT", contents)

    def test_non_owner_current_state_tool_is_blocked_at_execution_boundary(self):
        agent = AgentCore.__new__(AgentCore)
        agent._owner_scope = False
        agent._request_memory_writes_blocked = False
        agent._loop_tool_call_history = set()
        messages = []
        tool_call = SimpleNamespace(
            id="privacy-state-1",
            function=SimpleNamespace(
                name="update_current_state",
                arguments='{"action":"list"}',
            ),
        )

        with patch("brain.tools.execute_tool") as execute_tool:
            agent._execute_tool_calls_parallel([tool_call], messages)

        execute_tool.assert_not_called()
        self.assertEqual("tool", messages[0]["role"])
        self.assertIn("privacy-state-1", messages[0]["tool_call_id"])

    def test_disabled_core_memory_tools_are_hidden_from_catalog(self):
        catalog = build_tool_catalog(
            set(),
            disabled_tool_names={"save_memory", "search_graph_memory"},
        )
        core_line = next(
            line for line in catalog.splitlines() if "core" in line.lower() or "核心" in line
        )
        self.assertNotIn("save_memory", core_line)
        self.assertNotIn("search_graph_memory", core_line)
        self.assertIn("save_memory", catalog)
        self.assertIn("search_graph_memory", catalog)


class QQOwnerScopeRefreshTests(unittest.TestCase):
    def test_cached_agent_is_rebuilt_when_owner_identity_changes(self):
        worker = QQBridgeWorker.__new__(QQBridgeWorker)
        worker._lock = threading.RLock()
        worker._owner_qq = "new-owner"
        worker._owner_name = "Owner"
        worker._member_info_cache = {}
        worker._session_map = {"qq_private_old-owner": 41}
        worker._sessions = {
            "qq_private_old-owner": SimpleNamespace(_owner_scope=True)
        }
        worker._log = lambda _message: None
        replacement = SimpleNamespace(_owner_scope=False, _session_id=41)

        with patch(
            "workers.qq_bridge_worker.AgentCore", return_value=replacement
        ) as agent_cls:
            result = worker._get_or_create_agent(
                "qq_private_old-owner", user_id="old-owner"
            )

        self.assertIs(replacement, result)
        self.assertFalse(agent_cls.call_args.kwargs["owner_scope"])
        self.assertTrue(agent_cls.call_args.kwargs["disable_tools"])
        user_desc = agent_cls.call_args.kwargs["user_desc"]
        self.assertNotIn("Owner", user_desc)
        self.assertNotIn("new-owner", user_desc)


class WeChatOwnerScopeRefreshTests(unittest.TestCase):
    def test_cached_agent_is_rebuilt_when_owner_identity_changes(self):
        worker = WeChatBridgeWorker.__new__(WeChatBridgeWorker)
        worker._lock = threading.RLock()
        worker._agents = {
            "private:old-owner": SimpleNamespace(_owner_scope=True)
        }
        worker._session_map = {"private:old-owner": 52}
        worker._is_owner = lambda _sender_id: False
        worker._log = lambda _message: None
        message = WeChatMessage(
            msg_id=1,
            room_id="",
            sender_id="old-owner",
            sender_name="Old Owner",
            content="hello",
            is_at=False,
            timestamp=1,
        )
        replacement = SimpleNamespace(_owner_scope=False, _session_id=52)

        with patch("brain.agent.AgentCore", return_value=replacement) as agent_cls:
            result = worker._get_or_create_agent(
                message, "private:old-owner", "private prompt"
            )

        self.assertIs(replacement, result)
        self.assertFalse(agent_cls.call_args.kwargs["owner_scope"])
        self.assertTrue(agent_cls.call_args.kwargs["disable_tools"])


if __name__ == "__main__":
    unittest.main()
