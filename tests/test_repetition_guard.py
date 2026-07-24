import unittest

from brain.agent import _recent_assistant_repetition, _system_first_messages
from brain.working_memory import format_working_memory_context, update_working_topic


class RepetitionGuardTests(unittest.TestCase):
    def test_system_messages_are_before_conversation(self):
        messages = [
            {"role": "system", "content": "基础规则"},
            {"role": "user", "content": "问题"},
            {"role": "system", "content": "工具目录"},
            {"role": "assistant", "content": "回答"},
        ]
        ordered = _system_first_messages(messages)
        self.assertEqual(["system", "system", "user", "assistant"], [m["role"] for m in ordered])
        self.assertEqual("问题", ordered[2]["content"])

    def test_recent_duplicate_assistant_output_is_detected(self):
        history = [
            {"role": "user", "content": "第一个问题"},
            {"role": "assistant", "content": "相同回答"},
            {"role": "user", "content": "第二个问题"},
            {"role": "assistant", "content": "相同  回答"},
        ]
        self.assertTrue(_recent_assistant_repetition(history, "当前问题"))
        self.assertFalse(_recent_assistant_repetition(history, "请再说一遍刚才的话"))

    def test_working_memory_marks_itself_as_non_authoritative(self):
        context = format_working_memory_context({
            "topic_label": "当前话题",
            "summary": "莲心：旧回复",
            "model_summary": "",
            "facts": [],
            "model_facts": [],
            "open_loops": [],
        })
        self.assertIn("优先依据本轮用户消息", context)


if __name__ == "__main__":
    unittest.main()
