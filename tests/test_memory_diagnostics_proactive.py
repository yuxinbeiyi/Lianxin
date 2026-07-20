import tempfile, threading, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from brain import graph_memory

class MemoryDiagnosticsProactiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old_path=graph_memory._DB_PATH; self.old_local=graph_memory._local
        graph_memory._DB_PATH=Path(self.tmp.name)/"memory-debug.db"; graph_memory._local=threading.local()
        self.now=datetime(2026,7,20,12,0,tzinfo=timezone(timedelta(hours=8)))
    def tearDown(self):
        conn=getattr(graph_memory._local,"conn",None)
        if conn: conn.close()
        graph_memory._DB_PATH=self.old_path; graph_memory._local=self.old_local; self.tmp.cleanup()

    def test_request_trace_keeps_recall_reason_and_tool_audit(self):
        from brain.memory_diagnostics import start_memory_trace, record_memory_event, finish_memory_trace, get_memory_traces, get_trace_events
        trace=start_memory_trace(session_id=7,channel="qq",persona_id="limina",persona_revision=3,user_message="你还记得吗")
        record_memory_event(trace,"rag_memory_injected",memory_id=12,score=.81,reason="综合排序",payload={"quality_score":.9,"source":"qq"})
        record_memory_event(trace,"memory_tool_call",reason="save_memory",payload={"tool":"save_memory"})
        finish_memory_trace(trace,status="success",response="记得",duration_ms=22)
        row=get_memory_traces()[0]; events=get_trace_events(trace)
        self.assertEqual("limina",row["persona_id"]); self.assertEqual("success",row["status"])
        self.assertEqual(["rag_memory_injected","memory_tool_call"],[e["event_type"] for e in events])
        self.assertEqual(.9,events[0]["payload"]["quality_score"])

    def test_model_decision_becomes_due_cue_and_delivers_once(self):
        from brain.current_state import set_current_state
        from brain.memory_proactive import collect_candidates, apply_evaluations, get_due_cue, mark_cue_delivered
        set_current_state("用户明天下午参加面试","plan",expires_at=self.now+timedelta(days=2),now=self.now)
        candidate=collect_candidates()[0]
        apply_evaluations([{"fingerprint":candidate["fingerprint"],"decision":{"action":"check_in","due_at":self.now.isoformat(),"window_end":(self.now+timedelta(hours=4)).isoformat(),"confidence":.92,"rationale":"适合关心结果","message_instruction":"自然询问面试感受"}}], now=self.now)
        cue=get_due_cue(self.now); self.assertIsNotNone(cue); self.assertEqual("check_in",cue["action"])
        mark_cue_delivered(cue["id"],"面试怎么样？")
        self.assertIsNone(get_due_cue(self.now))

    def test_suppression_is_model_decision_and_has_time_window(self):
        from brain.current_state import set_current_state
        from brain.memory_proactive import collect_candidates, apply_evaluations, get_active_suppression
        set_current_state("用户正在发烧休息","health",expires_at=self.now+timedelta(days=1),now=self.now)
        candidate=collect_candidates()[0]
        apply_evaluations([{"fingerprint":candidate["fingerprint"],"decision":{"action":"suppress","due_at":self.now.isoformat(),"window_end":(self.now+timedelta(hours=8)).isoformat(),"confidence":.9}}], now=self.now)
        self.assertIsNotNone(get_active_suppression(self.now))

if __name__ == "__main__": unittest.main()
