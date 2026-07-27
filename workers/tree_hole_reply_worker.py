"""Background worker for one durable tree-hole reply job."""

from __future__ import annotations

from PyQt5.QtCore import QThread, pyqtSignal


class TreeHoleReplyWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, *, database_path, job: dict, agent, parent=None):
        super().__init__(parent)
        self.database_path = database_path
        self.job = dict(job or {})
        self.agent = agent

    def run(self) -> None:
        try:
            from gui.time_capsule.database import TimeCapsuleDatabase
            from brain.persona.runtime import active_assistant_name, capture_persona_snapshot

            db = TimeCapsuleDatabase(self.database_path, migrate_legacy=False)
            note_id = int(self.job.get("note_id", 0) or 0)
            note = db.get_tree_note(note_id)
            if not note:
                self.completed.emit({"status": "missing", "note_id": note_id})
                return
            if note.get("reply"):
                self.completed.emit({
                    "status": "already_done", "note_id": note_id,
                    "reply": note.get("reply"),
                })
                return

            persona = capture_persona_snapshot()
            assistant_name = active_assistant_name(persona)
            prompt = (
                f"你是{assistant_name}。主人把下面这段话放进了只属于你们的树洞。\n"
                "请写一段温柔、克制、真诚的纸条背面回应，像你真的读到了这张纸条。\n"
                "不要分析、说教、复述规则或使用标题，控制在80到220个中文字符。\n\n"
                f"纸条：{str(note.get('content', ''))[:1200]}"
            )
            agent = self.agent
            if agent is None:
                raise RuntimeError("当前没有可用的模型代理")
            response = agent._call_api_with_retry([{"role": "user", "content": prompt}])
            text = str(response.choices[0].message.content or "").strip()
            if not text:
                raise ValueError("模型返回了空的树洞回应")
            reply = db.add_tree_reply_if_missing(note_id, text[:800])
            if not reply:
                raise RuntimeError("树洞回应写入失败")
            self.completed.emit({
                "status": "success", "note_id": note_id,
                "reply": reply,
            })
        except Exception as exc:
            self.failed.emit({
                "status": "failed", "note_id": int(self.job.get("note_id", 0) or 0),
                "error": str(exc),
            })
