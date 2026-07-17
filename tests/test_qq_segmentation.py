import threading
import time
import unittest

from utils.text_segmentation import split_semantic_text
from brain.agent import AgentCore
from workers.qq_bridge_worker import QQBridgeWorker


def make_worker():
    worker = QQBridgeWorker.__new__(QQBridgeWorker)
    worker._segment_lock = threading.Lock()
    worker._segment_queue = []
    worker._segment_active = False
    worker._segment_has_sent = False
    worker._segment_clear_count = 0
    worker._segment_session_key = ""
    worker._segment_msg = None
    worker._segment_user = ""
    worker._request_generations = {}
    worker._request_generation_lock = threading.Lock()
    worker._log_messages = []
    worker._log = worker._log_messages.append
    return worker


class SemanticSegmentationTests(unittest.TestCase):
    def test_long_sentence_is_never_cut_by_character_count(self):
        text = "这是一个没有句号但必须作为完整语义保留下来的长句子" * 8
        self.assertEqual([text], split_semantic_text(text))

    def test_long_paragraph_splits_only_after_complete_sentences(self):
        first = "第一句话包含完整说明" * 5 + "。"
        second = "第二句话也必须保持完整" * 5 + "！"
        self.assertEqual([first, second], split_semantic_text(first + second))

    def test_code_fence_remains_one_atomic_segment(self):
        code = "```python\nvalue = '很长的代码内容'\nprint(value)\n```"
        result = split_semantic_text(f"先看代码。\n{code}\n最后说明。")
        self.assertIn(code, result)
        self.assertEqual(1, sum(1 for item in result if item.startswith("```")))

    def test_qq_worker_uses_shared_semantic_splitter(self):
        worker = make_worker()
        text = ("完整句子一。" * 10) + ("完整句子二！" * 10)
        self.assertEqual(split_semantic_text(text), worker._split_response(text))


class QQReplyInterruptionTests(unittest.TestCase):
    def test_new_request_immediately_discards_same_session_segments(self):
        worker = make_worker()
        worker._queue_segmented_response(
            ["第一段", "第二段", "第三段"], {"message_type": "private"},
            "10001", "qq_private_10001",
        )
        old_delivery_generation = worker._segment_clear_count

        request_generation = worker._begin_request("qq_private_10001")

        self.assertEqual([], worker._segment_queue)
        self.assertFalse(worker._segment_active)
        self.assertGreater(worker._segment_clear_count, old_delivery_generation)
        self.assertTrue(worker._is_request_current("qq_private_10001", request_generation))

    def test_other_session_does_not_interrupt_current_delivery(self):
        worker = make_worker()
        worker._queue_segmented_response(
            ["第一段", "第二段"], {"message_type": "private"},
            "10001", "qq_private_10001",
        )

        worker._begin_request("qq_private_20002")

        self.assertEqual(["第一段", "第二段"], worker._segment_queue)
        self.assertTrue(worker._segment_active)

    def test_older_generated_reply_becomes_stale(self):
        worker = make_worker()
        old_generation = worker._begin_request("qq_private_10001")
        new_generation = worker._begin_request("qq_private_10001")

        self.assertFalse(worker._is_request_current("qq_private_10001", old_generation))
        self.assertTrue(worker._is_request_current("qq_private_10001", new_generation))

    def test_segment_worker_drops_popped_segment_when_interrupted_during_typing(self):
        worker = make_worker()
        typing_started = threading.Event()
        sent = []
        worker._running = True
        worker._segment_pending = ".."
        worker._bot_qq = "999"
        worker._segment_interval = (0.01, 0.01)
        worker._calc_typing_time = lambda _text: 1.0
        worker._send_msg = lambda payload: sent.append(payload) or True
        worker._send_qq_emotion_image = lambda _msg: None
        worker._log = lambda message: typing_started.set() if "分段打字" in message else None
        worker._queue_segmented_response(
            ["第一段", "第二段"],
            {"message_type": "private", "user_id": 10001},
            "10001", "qq_private_10001",
        )
        thread = threading.Thread(target=worker._segment_worker, daemon=True)
        thread.start()
        self.assertTrue(typing_started.wait(1.0))

        worker._begin_request("qq_private_10001")
        time.sleep(0.4)
        worker._running = False
        thread.join(timeout=1.0)

        self.assertEqual([], sent)

    def test_stale_agent_response_is_not_written_to_history(self):
        class HistoryStub:
            def __init__(self):
                self.saved = []

            def save_message(self, session_id, role, content):
                self.saved.append((session_id, role, content))

        history = HistoryStub()
        agent = AgentCore.__new__(AgentCore)
        agent.history = []
        agent._session_titled = True
        agent._history_mgr = history
        agent._session_id = 9
        agent._disable_tools = False
        agent._use_local = False
        agent._track_emotion = False
        agent._last_emotion = None
        agent._last_raw_response = None
        agent._auto_extract = False
        agent._function_calling_loop = lambda *args, **kwargs: "这条旧回复不应保存"

        result = agent.chat("旧问题", response_guard=lambda: False)

        self.assertEqual("", result)
        self.assertEqual([{"role": "user", "content": "旧问题"}], agent.history)
        self.assertEqual([(9, "user", "旧问题")], history.saved)


if __name__ == "__main__":
    unittest.main()
