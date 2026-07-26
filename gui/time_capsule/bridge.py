"""Time Capsule Web 前端与 Python 数据层之间的稳定桥接。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from threading import Lock, Thread

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QFileDialog

from config import get_user_name
from config import get_diary_config, save_diary_config
from .database import TimeCapsuleDatabase


class TimeCapsuleBridge(QObject):
    state_changed = pyqtSignal(str)
    generation_requested = pyqtSignal(str)
    close_requested = pyqtSignal()
    minimize_requested = pyqtSignal()
    fullscreen_requested = pyqtSignal()
    settings_changed = pyqtSignal()
    companion_ready = pyqtSignal(str)

    def __init__(self, parent=None, db_path=None):
        super().__init__(parent)
        self.db = TimeCapsuleDatabase(db_path)
        self._memory_linking = set()
        self._memory_linking_lock = Lock()
        self._companion_running = False
        self._companion_lock = Lock()

    @staticmethod
    def _json(payload) -> str:
        return json.dumps(payload, ensure_ascii=False)

    def _state(self, day: str | None = None) -> dict:
        payload = self.db.initial_state(day or date.today().isoformat())
        payload["user_name"] = get_user_name()
        return payload

    def emit_state(self, day: str | None = None) -> None:
        self.state_changed.emit(self._json(self._state(day)))

    @pyqtSlot(result=str)
    def get_initial_state(self):
        return self._json(self._state())

    @pyqtSlot(str, result=str)
    def get_day(self, day):
        return self._json(self.db.get_day(str(day)))

    @pyqtSlot(str, str, result=str)
    def save_user_content(self, day, content):
        result = self.db.save_user_content(str(day), str(content))
        self.emit_state(str(day))
        return self._json(result)

    @pyqtSlot(str, str, result=str)
    def seal_day(self, day, user_content):
        day = str(day)
        self.db.save_user_content(day, str(user_content))
        result = self.db.seal_day(day)
        self._start_memory_link(day, result)
        if not str(result.get("lianxin_content", "")).strip():
            self.generation_requested.emit(day)
        self.emit_state(day)
        return self._json(result)

    def _start_memory_link(self, day: str, result: dict) -> None:
        """封存先完成；较慢的向量记忆写入在后台继续。"""
        if int((result.get("source") or {}).get("memory_fact_id", 0) or 0):
            return
        with self._memory_linking_lock:
            if day in self._memory_linking:
                return
            self._memory_linking.add(day)
        Thread(
            target=self._register_sealed_memory,
            args=(day, result),
            name=f"capsule-memory-{day}",
            daemon=True,
        ).start()

    def _register_sealed_memory(self, day: str, result: dict) -> None:
        """Explicit sealing is the consent boundary for long-term memory linking."""
        if int((result.get("source") or {}).get("memory_fact_id", 0) or 0):
            return
        user_text = str(result.get("user_content", "")).strip()
        lianxin_text = str(result.get("lianxin_content", "")).strip()
        if not user_text and not lianxin_text:
            return
        run_id = 0
        try:
            from brain.workflow import get_workflow_store
            workflow = get_workflow_store()
            run = workflow.begin_run(
                kind="time_capsule_seal", title=f"封存 {day} 的时间胶囊",
                channel="desktop", metadata={"date": day},
            )
            run_id = int(run["id"])
            from brain.graph_memory import add_fact
            shared_parts = []
            if user_text:
                shared_parts.append(f"主人留下：{user_text}")
            if lianxin_text:
                shared_parts.append(f"莲心留下：{lianxin_text}")
            compact = " ".join("；".join(shared_parts).split())[:700]
            fact_id = add_fact(
                f"时间胶囊 {day}：{compact}", "events", source="time_capsule",
                source_channel="desktop", occurred_at=f"{day} 23:59:00",
            )
            self.db.link_memory_fact(day, fact_id)
            workflow.finish_run(
                run_id, status="completed",
                result_summary=f"sealed capsule linked to memory fact {fact_id}",
            )
        except Exception as exc:
            if run_id:
                try:
                    from brain.workflow import get_workflow_store
                    get_workflow_store().finish_run(run_id, status="failed", error=str(exc))
                except Exception:
                    pass
        finally:
            with self._memory_linking_lock:
                self._memory_linking.discard(day)

    @pyqtSlot(str, str, str, result=str)
    def add_trace(self, day, author, content):
        result = self.db.add_trace(str(day), str(author), str(content))
        self.emit_state(str(day))
        return self._json(result)

    @pyqtSlot(str, str, str, str, result=str)
    def add_collection(self, day, kind, title, uri):
        result = self.db.add_collection(str(day), str(kind), str(title), str(uri))
        self.emit_state(str(day))
        return self._json(result)

    @pyqtSlot(str, result=str)
    def choose_collection_file(self, kind):
        kind = str(kind)
        filters = {
            "photo": "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp)",
            "music": "音频文件 (*.mp3 *.wav *.flac *.m4a *.ogg)",
            "file": "所有文件 (*)",
        }
        path, _ = QFileDialog.getOpenFileName(
            None, "选择要一起收藏的内容", "", filters.get(kind, "所有文件 (*)")
        )
        if not path:
            return ""
        return str(Path(path).resolve())

    @pyqtSlot(int, result=str)
    def toggle_collection_favorite(self, collection_id):
        self.db.toggle_collection_favorite(int(collection_id))
        self.emit_state()
        return self._json({"ok": True})

    @pyqtSlot(str, result=str)
    def add_tree_note(self, content):
        note_id = self.db.add_tree_note("user", str(content))
        self.emit_state()
        return self._json({"ok": bool(note_id), "id": note_id})

    @pyqtSlot(int, result=str)
    def toggle_tree_favorite(self, note_id):
        self.db.toggle_tree_favorite(int(note_id))
        self.emit_state()
        return self._json({"ok": True})

    @pyqtSlot(str, result=str)
    def search(self, query):
        return self._json(self.db.search(str(query)))

    @pyqtSlot(result=str)
    def get_settings(self):
        return self._json(get_diary_config())

    @pyqtSlot(bool, str, int, str, result=str)
    def save_settings(self, scheduled_enabled, scheduled_time, max_messages, direction):
        payload = get_diary_config()
        payload.update({
            "scheduled_enabled": bool(scheduled_enabled),
            "scheduled_time": str(scheduled_time or "23:55"),
            "max_messages": max(1, min(200, int(max_messages))),
            "direction": "earliest" if direction == "earliest" else "latest",
        })
        save_diary_config(payload)
        self.settings_changed.emit()
        return self._json(payload)

    @pyqtSlot(int, result=str)
    def visit_memory(self, memory_id):
        memories = self.db.memories(300)
        memory = next((item for item in memories if int(item["id"]) == int(memory_id)), {})
        if not memory:
            return self._json({})
        self.db.record_visit(int(memory_id), memory.get("source_date", ""))
        return self._json(memory)

    @pyqtSlot(str, result=str)
    def invite_lianxin(self, source_date):
        source_date = str(source_date or "")
        with self._companion_lock:
            if self._companion_running:
                return self._json({"pending": True, "date": source_date})
            self._companion_running = True
        Thread(
            target=self._prepare_companion_memory,
            args=(source_date,),
            name="capsule-companion",
            daemon=True,
        ).start()
        return self._json({"pending": True, "date": source_date})

    def _prepare_companion_memory(self, source_date: str) -> None:
        """用已有 RAG 找相关回忆；不调用聊天模型，不增加生成 Token。"""
        try:
            day = self.db.get_day(source_date) if source_date else {}
            content = str(
                day.get("user_content") or day.get("lianxin_content") or ""
            ).strip()
            if not content:
                message = "这一页还没有写满。不过我愿意陪你慢慢看，等它以后长成一段回忆。"
            else:
                related = []
                try:
                    from brain.memory_rag import search_similar
                    related = search_similar(
                        content[:600], top_k=3, threshold=0.28,
                        track_access=False, hybrid=True,
                    )
                except Exception:
                    related = []
                memory_text = ""
                for _, memory in related:
                    candidate = " ".join(str(memory.get("content", "")).split())
                    if candidate and source_date not in candidate:
                        memory_text = candidate[:120]
                        break
                day_excerpt = " ".join(content.split())[:100]
                if memory_text:
                    message = (
                        f"陪你翻到这一页时，我又想起了：{memory_text}"
                        f"。它和这一天的「{day_excerpt}」像是隔着时间轻轻照应。"
                    )
                else:
                    message = (
                        f"我记得这一页里的「{day_excerpt}」。"
                        "当时看起来很普通的片刻，现在再看，已经有了回忆的光。"
                    )
            try:
                self.companion_ready.emit(self._json({
                    "message": message, "date": source_date,
                }))
            except RuntimeError:
                # 窗口可能在后台检索完成前已经关闭。
                pass
        finally:
            with self._companion_lock:
                self._companion_running = False

    @pyqtSlot()
    def request_close(self):
        self.close_requested.emit()

    @pyqtSlot()
    def request_minimize(self):
        self.minimize_requested.emit()

    @pyqtSlot()
    def request_fullscreen(self):
        self.fullscreen_requested.emit()
