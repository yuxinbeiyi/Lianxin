import unittest
from types import SimpleNamespace
from unittest.mock import patch

from brain.agent import AgentCore, _normalize_memory_provenance


def _history(turns: int) -> list[dict]:
    result = []
    for index in range(turns):
        result.extend([
            {"role": "user", "content": f"用户-{index}"},
            {"role": "assistant", "content": f"助手-{index}"},
        ])
    return result


class _SnapshotStore:
    def __init__(self, latest=None):
        self.latest = latest
        self.saved = []

    def get_latest_compression_snapshot(self, session_id):
        return self.latest

    def save_compression_snapshot(self, *args, **kwargs):
        self.saved.append((args, kwargs))
        return len(self.saved)


class AgentContextWindowTests(unittest.TestCase):
    def _agent(self, turns=4):
        agent = AgentCore.__new__(AgentCore)
        agent.history = _history(turns)
        agent._conversation_summary = ""
        agent._summarized_history_idx = 0
        agent._last_input_tokens = 0
        agent._history_mgr = _SnapshotStore()
        agent._session_id = 7
        agent._model = "test-model"
        return agent

    @staticmethod
    def _config(batch=6):
        return {
            "enable_conversation_summary": True,
            "context_keep_loops": 2,
            "context_summary_trigger": 2,
            "context_summary_token_threshold": 80_000,
            "context_summary_batch_messages": batch,
        }

    def test_small_pending_batch_is_not_dropped_or_marked_summarized(self):
        agent = self._agent(turns=4)  # 溢出 2 turn / 4 message，小于默认批次
        with patch("brain.agent.get_memory_config", return_value=self._config()):
            summary, recent = agent._apply_history_window()
        self.assertIsNone(summary)
        self.assertEqual(0, agent._summarized_history_idx)
        self.assertEqual(agent.history, recent)
        self.assertEqual([], agent._history_mgr.saved)

    def test_memory_provenance_accepts_only_persisted_user_messages(self):
        rows = [
            {"id": 10, "role": "user", "timestamp": "2026-07-20 09:00:00"},
            {"id": 11, "role": "assistant", "timestamp": "2026-07-20 09:00:01"},
            {"id": 12, "role": "user", "timestamp": "2026-07-20 09:00:02"},
        ]
        ids, confidence, occurred_at = _normalize_memory_provenance(
            {
                "source_message_ids": [10, 11, 12, 10, 999],
                "confidence": 0.92,
                "occurred_at": "",
            },
            rows,
        )
        self.assertEqual([10, 12], ids)
        self.assertEqual(0.92, confidence)
        self.assertEqual("2026-07-20 09:00:02", occurred_at)

    def test_uncited_memory_confidence_is_capped(self):
        ids, confidence, occurred_at = _normalize_memory_provenance(
            {"source_message_ids": [404], "confidence": 0.99},
            [{"id": 10, "role": "user", "timestamp": "2026-07-20 09:00:00"}],
        )
        self.assertEqual([], ids)
        self.assertEqual(0.5, confidence)
        self.assertEqual("", occurred_at)

    def test_successful_summary_advances_cursor_and_persists_snapshot(self):
        agent = self._agent(turns=5)  # 溢出 3 turn / 6 message
        agent._generate_history_summary = lambda chunk: "保留事实与待办"
        with patch("brain.agent.get_memory_config", return_value=self._config()):
            summary, recent = agent._apply_history_window(
                SimpleNamespace(profile=SimpleNamespace(id="calm"), revision=2)
            )
        self.assertIn("保留事实与待办", summary)
        self.assertEqual(6, agent._summarized_history_idx)
        self.assertEqual(agent.history[6:], recent)
        self.assertEqual(1, len(agent._history_mgr.saved))
        _, metadata = agent._history_mgr.saved[0]
        self.assertEqual("calm", metadata["persona_id"])
        self.assertEqual(2, metadata["persona_revision"])

    def test_summary_failure_uses_content_preserving_fallback(self):
        agent = self._agent(turns=5)
        agent._generate_history_summary = lambda chunk: None
        with patch("brain.agent.get_memory_config", return_value=self._config()):
            summary, _ = agent._apply_history_window()
        self.assertIn("用户-0", summary)
        self.assertEqual(6, agent._summarized_history_idx)

    def test_snapshot_restore_rejects_cursor_beyond_history(self):
        agent = self._agent(turns=2)
        agent._history_mgr.latest = {
            "summary": "不应加载", "covered_message_count": 99
        }
        agent._restore_context_snapshot()
        self.assertEqual("", agent._conversation_summary)
        self.assertEqual(0, agent._summarized_history_idx)

    def test_snapshot_restore_compacts_legacy_oversized_summary(self):
        agent = self._agent(turns=2)
        agent._history_mgr.latest = {
            "summary": "早期事实" + "A" * 6_000 + "最新进展",
            "covered_message_count": 2,
        }
        with patch(
            "brain.agent.get_memory_config",
            return_value={"context_summary_max_chars": 1_200},
        ):
            agent._restore_context_snapshot()
        self.assertLessEqual(len(agent._conversation_summary), 1_200)
        self.assertIn("早期事实", agent._conversation_summary)
        self.assertIn("最新进展", agent._conversation_summary)
        self.assertEqual(2, agent._summarized_history_idx)

    def test_usage_only_stream_chunk_is_accepted(self):
        agent = AgentCore.__new__(AgentCore)
        agent._last_input_tokens = 0
        usage_chunk = SimpleNamespace(usage={"prompt_tokens": 12_345}, choices=[])
        delta = SimpleNamespace(content="完成", reasoning_content=None, tool_calls=None)
        text_chunk = SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(delta=delta, finish_reason="stop")],
        )
        content, _, _, finish = agent._collect_stream(
            [usage_chunk, text_chunk], max_retries=0
        )
        self.assertEqual("完成", content)
        self.assertEqual("stop", finish)
        self.assertEqual(12_345, agent._last_input_tokens)

    def test_summary_stream_uses_content_chunks(self):
        agent = AgentCore.__new__(AgentCore)
        agent._model = "test-model"
        agent._api_key = "key"
        agent._api_base = "https://example.invalid"
        chunks = [
            SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content="事实摘要")
            )]),
        ]
        with patch("brain.agent.litellm.completion", return_value=chunks) as completion:
            result = agent._stream_summary_text([{"role": "user", "content": "内容"}])
        self.assertEqual("事实摘要", result)
        self.assertTrue(completion.call_args.kwargs["stream"])

    def test_failed_summary_merge_remains_bounded(self):
        agent = AgentCore.__new__(AgentCore)
        agent._stream_summary_text = lambda messages: None
        with patch(
            "brain.agent.get_memory_config",
            return_value={"context_summary_max_chars": 1_200},
        ):
            merged = agent._merge_summaries(
                "最早事实" + "A" * 5_000,
                "最新进展" + "B" * 5_000,
            )
        self.assertLessEqual(len(merged), 1_200)
        self.assertIn("最早事实", merged)
        self.assertIn("最新进展", merged)

    def test_session_memory_opt_out_survives_history_restore(self):
        agent = AgentCore.__new__(AgentCore)
        agent.history = [
            {"role": "user", "content": "测试期间不要把内容保存为长期记忆"},
            {"role": "assistant", "content": "好的"},
        ]
        self.assertTrue(agent._derive_memory_write_policy())
        agent._session_memory_writes_blocked = True
        self.assertTrue(agent._update_memory_write_policy("继续聊天"))
        self.assertFalse(agent._update_memory_write_policy("现在允许恢复长期记忆保存"))

    def test_memory_write_tool_is_blocked_at_execution_boundary(self):
        agent = AgentCore.__new__(AgentCore)
        agent._request_memory_writes_blocked = True
        agent._loop_tool_call_history = set()
        messages = []
        tool_call = SimpleNamespace(
            id="memory-1",
            function=SimpleNamespace(
                name="save_memory",
                arguments='{"fact":"不应保存"}',
            ),
        )
        agent._execute_tool_calls_parallel([tool_call], messages)
        self.assertEqual("tool", messages[0]["role"])
        self.assertEqual("memory-1", messages[0]["tool_call_id"])
        self.assertIn("代码层阻止", messages[0]["content"])

    def test_textual_tool_protocol_is_retried_and_never_returned(self):
        agent = AgentCore.__new__(AgentCore)
        agent.history = [{"role": "user", "content": "总结文件"}]
        agent._use_local = True
        agent._prev_session_summary = ""
        agent._request_memory_writes_blocked = False
        agent._model = "test-model"
        agent._max_tokens = 200
        agent._api_key = "key"
        agent._api_base = "https://example.invalid"
        agent._last_reasoning = None
        agent._build_request_system_messages = lambda snapshot: []
        agent._build_realtime_message = lambda: {"role": "system", "content": "time"}

        def stream(text):
            delta = SimpleNamespace(
                content=text, reasoning_content=None, tool_calls=None
            )
            return [SimpleNamespace(
                usage=None,
                choices=[SimpleNamespace(delta=delta, finish_reason="stop")],
            )]

        with patch(
            "brain.agent.litellm.completion",
            side_effect=[stream("<tool_call><function=read_file>"), stream("最终自然语言总结")],
        ) as completion:
            result = agent._function_calling_loop(
                disable_tools=True, user_message="总结文件"
            )
        self.assertEqual("最终自然语言总结", result)
        self.assertNotIn("tool_call", result)
        self.assertEqual(2, completion.call_count)


if __name__ == "__main__":
    unittest.main()
