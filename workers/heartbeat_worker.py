"""
HeartbeatWorker：心跳自检后台线程
对话结束延迟后触发，调用 LLM 回顾对话 + 待办清单，检查遗漏事项。
"""

from PyQt5.QtCore import QThread, pyqtSignal

from memory.history_manager import HistoryManager
from brain.heartbeat import perform_heartbeat


class HeartbeatWorker(QThread):
    """在后台执行心跳自检，完成或失败时发射信号。"""

    response_ready = pyqtSignal(str)  # 有提醒内容
    finished_silent = pyqtSignal()    # 静默（无需提醒或失败）

    def __init__(self, session_id: int, parent=None):
        super().__init__(parent)
        self._session_id = session_id

    def run(self):
        try:
            hm = HistoryManager()
            msgs = hm.get_messages(self._session_id)
        except Exception:
            self.finished_silent.emit()
            return

        result = perform_heartbeat(msgs)
        if result:
            self.response_ready.emit(result)
        else:
            self.finished_silent.emit()
