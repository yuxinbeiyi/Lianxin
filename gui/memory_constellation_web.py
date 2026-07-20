"""Canvas-based Memory Constellations view.

This is a deliberately separate renderer from the native Qt Memory Universe:
it gives Lianxin a browser-style, cached Canvas 2D star map for comparison and
future visual experimentation without changing the underlying memory model.
"""
from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import QUrl, Qt, QObject, pyqtSlot
from PyQt5.QtWidgets import QDialog, QMainWindow, QVBoxLayout, QTextBrowser, QPushButton, QWidget
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel


class _ConstellationBridge(QObject):
    @pyqtSlot(str)
    def openOriginalMessages(self, raw_ids: str):
        try:
            ids = sorted({int(value) for value in json.loads(raw_ids or "[]") if str(value).isdigit()})
        except (TypeError, ValueError, json.JSONDecodeError):
            ids = []
        dialog = QDialog()
        dialog.setWindowTitle("原始消息来源")
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser(dialog)
        try:
            from brain.graph_memory import _get_conn
            if not ids:
                browser.setPlainText("该记忆没有可定位的原始消息编号。")
            else:
                placeholders = ",".join("?" for _ in ids)
                rows = _get_conn().execute(
                    f"SELECT id,session_id,role,content,timestamp FROM messages WHERE id IN ({placeholders}) ORDER BY timestamp,id",
                    tuple(ids),
                ).fetchall()
                browser.setPlainText("\n\n".join(
                    f"[{row['timestamp'] or ''}] #{row['id']} {row['role'] or ''}\n{row['content'] or ''}"
                    for row in rows
                ) or "原始消息已不存在。")
        except Exception as exc:
            browser.setPlainText(f"读取原始消息失败：{exc}")
        layout.addWidget(browser)
        close = QPushButton("关闭", dialog)
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec_()


class MemoryConstellationWebWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("莲心 · 记忆星图系统")
        self.setMinimumSize(1120, 720)
        self.resize(1500, 920)
        self.setWindowFlags(Qt.Window)
        self._asset_dir = Path(__file__).resolve().parent.parent / "assets" / "memory_constellation"
        self._view = QWebEngineView(self)
        self._bridge = _ConstellationBridge()
        channel = QWebChannel(self._view)
        channel.registerObject("lianxinBridge", self._bridge)
        self._view.page().setWebChannel(channel)
        self._view.setContextMenuPolicy(Qt.NoContextMenu)
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)
        self.setCentralWidget(root)
        self._load_map()

    def _load_map(self):
        from brain.memory_narrative import list_entity_profiles, list_episodes, list_sagas, list_narrative_events, get_last_narrative_run
        from config import get_user_name

        entities = list_entity_profiles(300)
        episodes = list_episodes(300)
        sagas = list_sagas(100)
        source_ids = {}
        try:
            from brain.graph_memory import get_fact_fragments
            for item in entities + episodes:
                fact_ids = []
                for key in ("source_fact_ids", "fragment_ids"):
                    try:
                        values = json.loads(item.get(key, "[]") or "[]")
                        if key == "source_fact_ids": fact_ids.extend(int(v) for v in values)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
                ids = []
                for fact_id in fact_ids:
                    for fragment in get_fact_fragments(fact_id, include_inactive=True):
                        ids.extend(int(v) for v in fragment.get("source_message_ids", []) if str(v).isdigit())
                source_ids[str(item.get("id"))] = sorted(set(ids))
        except Exception:
            pass
        try:
            from brain.persona.manager import PersonaManager
            assistant_name = PersonaManager().get_snapshot().profile.assistant_name or "莲心"
        except Exception:
            assistant_name = "莲心"
        payload = {
            "entities": entities, "episodes": episodes, "sagas": sagas,
            "events": list_narrative_events(80), "source_ids": source_ids,
            "core": {"user": get_user_name() or "主人", "assistant": assistant_name},
            "model": get_last_narrative_run() or {"status": "未运行"},
        }
        template = (self._asset_dir / "index.html").read_text(encoding="utf-8")
        injected = "<script>window.LIANXIN_MEMORY_DATA=" + json.dumps(
            payload, ensure_ascii=False, default=str
        ) + ";</script>"
        html = template.replace("<!-- LIANXIN_DATA -->", injected)
        self._view.setHtml(html, QUrl.fromLocalFile(str(self._asset_dir) + "/"))

    def refresh(self):
        self._load_map()
