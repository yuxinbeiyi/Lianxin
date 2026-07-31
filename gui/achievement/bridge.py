from __future__ import annotations

import json
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
from config import get_user_name
from .service import AchievementService


class AchievementBridge(QObject):
    close_requested = pyqtSignal()
    minimize_requested = pyqtSignal()
    fullscreen_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.service = AchievementService()

    @pyqtSlot(result=str)
    def get_initial_state(self):
        state = self.service.state(); state["user_name"] = get_user_name()
        return json.dumps(state, ensure_ascii=False)

    @pyqtSlot(result=str)
    def refresh(self):
        return self.get_initial_state()

    @pyqtSlot(int, int, str, str, result=str)
    def get_journey_page(self, offset=0, limit=20, categories="[]", day=""):
        try:
            parsed = json.loads(str(categories or "[]"))
            if not isinstance(parsed, list):
                parsed = []
            payload = self.service.journey_page(offset, limit, parsed, str(day or ""))
            return json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return json.dumps({"items": [], "total": 0, "error": str(exc)}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def export_metrics(self, export_format="json"):
        try:
            path = self.service.export_metrics(str(export_format or "json"))
            return json.dumps({"ok": True, "path": path}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def mark_unlocks_read(self, raw_ids):
        try:
            ids = json.loads(str(raw_ids or "[]"))
            if not isinstance(ids, list):
                raise ValueError("achievement ids must be a list")
            self.service.mark_unlocks_read(ids)
            return json.dumps({"ok": True}, ensure_ascii=False)
        except (ValueError, TypeError, json.JSONDecodeError):
            return json.dumps({"ok": False}, ensure_ascii=False)

    @pyqtSlot()
    def request_close(self): self.close_requested.emit()
    @pyqtSlot()
    def request_minimize(self): self.minimize_requested.emit()
    @pyqtSlot()
    def request_fullscreen(self): self.fullscreen_requested.emit()
