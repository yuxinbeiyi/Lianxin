"""Low-frequency model summarization for the active topic pool."""
from __future__ import annotations

import json
from PyQt5.QtCore import QThread, pyqtSignal
from openai import OpenAI
from config import get_api_config, get_agnes_config


class WorkingMemorySummaryWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, history_manager, session_id: int, parent=None):
        super().__init__(parent)
        self.history_manager = history_manager
        self.session_id = session_id

    def run(self):
        try:
            from brain.working_memory import apply_model_summary, get_working_topic
            topic = get_working_topic(session_id=self.session_id)
            if not topic or topic.get("session_id") != self.session_id:
                self.completed.emit({"status": "skipped"})
                return
            messages = self.history_manager.get_messages(self.session_id)[-16:]
            cfg = get_api_config()
            if cfg.get("provider") == "agnes":
                cfg = get_agnes_config()
            client = OpenAI(api_key=cfg.get("api_key", ""), base_url=cfg.get("base_url", ""))
            prompt = f"""请整理当前对话的临时工作记忆。它不是长期记忆，不能编造信息。
返回 JSON：{{"summary":"不超过1200字的当前任务摘要","facts":["稳定事实"],"open_loops":["未完成事项"],"task_state":"none|exploring|planning|executing|waiting|done"}}
当前主题：{topic.get('topic_label','')}
对话：{json.dumps(messages, ensure_ascii=False)}"""
            response = client.chat.completions.create(
                model=cfg.get("model", ""), temperature=0.1, max_tokens=1200,
                messages=[{"role": "system", "content": "你是工作记忆整理器，只输出 JSON。"}, {"role": "user", "content": prompt}],
                timeout=45,
            )
            raw=(response.choices[0].message.content or "{}").strip()
            if raw.startswith("```"):
                raw=raw.split("\n",1)[-1].rsplit("```",1)[0].strip()
            start,end=raw.find("{"),raw.rfind("}")
            data=json.loads(raw[start:end+1] if start>=0 and end>=start else "{}")
            apply_model_summary(topic["id"], summary=data.get("summary", ""), facts=data.get("facts", []), open_loops=data.get("open_loops", []), task_state=data.get("task_state", "none"))
            self.completed.emit({"status": "success", "topic_id": topic["id"]})
        except Exception as exc:
            self.failed.emit(str(exc))
