"""Canvas-based Memory Constellations view.

This is a deliberately separate renderer from the native Qt Memory Universe:
it gives Lianxin a browser-style, cached Canvas 2D star map for comparison and
future visual experimentation without changing the underlying memory model.
"""
from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QWidget
from PyQt5.QtWebEngineWidgets import QWebEngineView


class MemoryConstellationWebWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("莲心 · 记忆星图系统")
        self.setMinimumSize(1120, 720)
        self.resize(1500, 920)
        self.setWindowFlags(Qt.Window)
        self._asset_dir = Path(__file__).resolve().parent.parent / "assets" / "memory_constellation"
        self._view = QWebEngineView(self)
        self._view.setContextMenuPolicy(Qt.NoContextMenu)
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)
        self.setCentralWidget(root)
        self._load_map()

    def _load_map(self):
        from brain.memory_narrative import list_entity_profiles, list_episodes, list_sagas

        payload = {
            "entities": list_entity_profiles(300),
            "episodes": list_episodes(300),
            "sagas": list_sagas(100),
        }
        template = (self._asset_dir / "index.html").read_text(encoding="utf-8")
        injected = "<script>window.LIANXIN_MEMORY_DATA=" + json.dumps(
            payload, ensure_ascii=False, default=str
        ) + ";</script>"
        html = template.replace("<!-- LIANXIN_DATA -->", injected)
        self._view.setHtml(html, QUrl.fromLocalFile(str(self._asset_dir) + "/"))

    def refresh(self):
        self._load_map()

