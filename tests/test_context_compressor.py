import unittest
from types import SimpleNamespace

from brain.context_compressor import (
    build_fallback_summary,
    compact_summary_text,
    compact_tool_result,
    contains_textual_tool_protocol,
    extract_input_tokens,
    memory_persistence_directive,
    merge_summaries_bounded,
    prune_stale_tool_outputs,
    select_history_window,
    split_into_turns,
)


class ContextCompressorTests(unittest.TestCase):
    def test_turn_split_preserves_leading_assistant_and_tool_chain(self):
        history = [
            {"role": "system", "content": "policy"},
            {"role": "assistant", "content": "主动问候"},
            {"role": "user", "content": "查文件"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "content": "结果"},
            {"role": "assistant", "content": "找到了"},
        ]
        turns = split_into_turns(history)
        self.assertEqual(["assistant"], [m["role"] for m in turns[0]])
        self.assertEqual(
            ["user", "assistant", "tool", "assistant"],
            [m["role"] for m in turns[1]],
        )

    def test_window_uses_complete_turns_and_actual_token_trigger(self):
        history = []
        for index in range(4):
            history.extend([
                {"role": "user", "content": f"u{index}"},
                {"role": "assistant", "content": f"a{index}"},
            ])
        by_turns = select_history_window(
            history, keep_turns=2, trigger_turns=3, token_threshold=999_999
        )
        self.assertTrue(by_turns.should_compress)
        self.assertEqual("turns", by_turns.trigger)
        self.assertEqual(["u0", "a0", "u1", "a1"], [m["content"] for m in by_turns.overflow_messages])

        by_tokens = select_history_window(
            history, keep_turns=2, trigger_turns=99,
            last_input_tokens=90_000, token_threshold=80_000,
        )
        self.assertTrue(by_tokens.should_compress)
        self.assertEqual("tokens", by_tokens.trigger)

    def test_fallback_summary_retains_real_content(self):
        summary = build_fallback_summary([
            {"role": "user", "content": "请记住项目代号是青鸟"},
            {"role": "assistant", "content": "已经记录，下一步检查数据库"},
        ])
        self.assertIn("青鸟", summary)
        self.assertIn("检查数据库", summary)
        self.assertNotEqual("（早期对话，含 2 条消息）", summary)

    def test_tool_pruning_preserves_call_ids_and_recent_detail(self):
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "name": "read", "content": "A" * 5_000},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c2"}]},
            {"role": "tool", "tool_call_id": "c2", "name": "search", "content": "B" * 5_000},
        ]
        pruned = prune_stale_tool_outputs(
            messages, keep_recent=1, latest_max_chars=2_000, stale_max_chars=700
        )
        self.assertEqual("c1", pruned[1]["tool_call_id"])
        self.assertEqual("read", pruned[1]["name"])
        self.assertLessEqual(len(pruned[1]["content"]), 700)
        self.assertLessEqual(len(pruned[3]["content"]), 2_000)
        self.assertEqual(5_000, len(messages[1]["content"]))
        self.assertIn("原始 5000 字", compact_tool_result("X" * 5_000, 800))

        all_stale = prune_stale_tool_outputs(
            messages, keep_recent=0, latest_max_chars=2_000, stale_max_chars=700
        )
        self.assertLessEqual(len(all_stale[3]["content"]), 700)

    def test_usage_extraction_supports_multiple_providers(self):
        self.assertEqual(123, extract_input_tokens({"prompt_tokens": 123}))
        self.assertEqual(456, extract_input_tokens(SimpleNamespace(input_tokens=456)))
        self.assertEqual(789, extract_input_tokens({"promptTokenCount": 789}))

    def test_summary_fallback_merge_has_a_hard_budget(self):
        old = "早期事实：青鸟计划使用霁蓝色。" + "A" * 5_000
        new = "最近进展：下一步处理自动备份。" + "B" * 5_000
        merged = merge_summaries_bounded(old, new, max_chars=1_200)
        self.assertLessEqual(len(merged), 1_200)
        self.assertIn("早期事实", merged)
        self.assertIn("最近进展", merged)
        self.assertLessEqual(len(compact_summary_text(merged, 1_000)), 1_000)

    def test_textual_tool_protocol_is_detected_even_when_incomplete(self):
        self.assertTrue(contains_textual_tool_protocol("<tool_call>"))
        self.assertTrue(contains_textual_tool_protocol("<function=read_file>"))
        self.assertTrue(contains_textual_tool_protocol("  <tool"))
        self.assertTrue(contains_textual_tool_protocol('get_weather(city="广州", forecast_type="full")'))
        self.assertFalse(contains_textual_tool_protocol("根据文件内容，结论如下。"))

    def test_explicit_memory_persistence_directives(self):
        self.assertEqual(
            "block_session",
            memory_persistence_directive(
                "测试期间不需要把内容保存为长期记忆，只需要正常聊天。"
            ),
        )
        self.assertEqual(
            "block_request", memory_persistence_directive("这条不要存入长期记忆")
        )
        self.assertEqual(
            "allow", memory_persistence_directive("现在可以恢复保存到长期记忆")
        )
        self.assertEqual("none", memory_persistence_directive("你还记得什么？"))


if __name__ == "__main__":
    unittest.main()
