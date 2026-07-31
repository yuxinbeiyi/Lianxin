"""Unified Ripple emotion + Memory Constellation inspector."""

from __future__ import annotations

from pathlib import Path
import json

from PyQt5.QtCore import QTimer
from gui.memory_constellation_web import MemoryConstellationWebWindow


class RippleConstellationWebWindow(MemoryConstellationWebWindow):
    """Interactive star map for live affect, relationships, and memories."""

    def __init__(self, parent=None):
        self._ripple_asset_dir = (
            Path(__file__).resolve().parent.parent / "assets" / "ripple_constellation"
        )
        super().__init__(parent)
        self._asset_dir = self._ripple_asset_dir
        self.setWindowTitle("涟漪情感系统")
        self._load_map()
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(5000)
        self._sync_timer.timeout.connect(self._push_snapshot)
        self._sync_timer.start()

    def _push_snapshot(self):
        payload = json.dumps(self._snapshot(), ensure_ascii=False, default=str)
        self._view.page().runJavaScript(
            "window.rippleApplySnapshot && window.rippleApplySnapshot(" + payload + ");"
        )

    def closeEvent(self, event):
        if getattr(self, "_sync_timer", None) is not None:
            self._sync_timer.stop()
        super().closeEvent(event)

    def _snapshot(self):
        payload = super()._snapshot()
        try:
            from brain.emotional import get_manager

            manager = get_manager()
            emotion = manager.get_debug_info()
            emotion["motive"] = manager.get_proactive_motive()
            emotion["tone_guidance"] = manager.build_prompt_snippet()
            payload["emotion"] = emotion
        except Exception as exc:
            payload["emotion"] = {"error": str(exc), "version": 3}
        payload["ripple"] = {
            "schema": 1,
            "title": "涟漪星图",
            "description": "情绪状态、关系变化与长期记忆的可追溯视图",
        }
        return payload
