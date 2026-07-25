"""基于 QWebEngine 的莲心自习室窗口宿主。"""

from pathlib import Path

from PyQt5.QtCore import QUrl, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineView
from PyQt5.QtWidgets import QMainWindow, QMessageBox

from .bridge import StudyRoomBridge
from utils.paths import get_user_data_dir


class StudyRoomPage(QWebEnginePage):
    """把前端加载错误带回终端，避免 Web 页面静默失效。"""

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        print(f"[自习室Web] {message} ({source_id}:{line_number})")
        super().javaScriptConsoleMessage(level, message, line_number, source_id)


class StudyRoomWebWindow(QMainWindow):
    closed = pyqtSignal()
    focus_completed = pyqtSignal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("莲心自习室")
        self.setMinimumSize(980, 680)
        self.resize(1380, 860)
        self._is_fullscreen = False
        self._focus_owns_fullscreen = False
        self._bridge = StudyRoomBridge(self)
        self._view = QWebEngineView(self)
        # 使用独立 Profile，避免复用其它窗口或旧版本的 Chromium 资源缓存。
        self._profile = QWebEngineProfile("LianxinStudyRoom", self)
        web_data_dir = get_user_data_dir() / "study_room_webengine"
        self._profile.setPersistentStoragePath(str(web_data_dir))
        self._profile.setCachePath(str(web_data_dir / "cache"))
        self._profile.setHttpCacheType(QWebEngineProfile.NoCache)
        self._view.setPage(StudyRoomPage(self._profile, self._view))
        self._view.setContextMenuPolicy(Qt.NoContextMenu)
        self._view.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._view.page().setBackgroundColor(QColor("#F7EFE6"))
        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        self.setCentralWidget(self._view)
        self._channel = QWebChannel(self._view)
        self._channel.registerObject("studyBridge", self._bridge)
        self._view.page().setWebChannel(self._channel)
        self._bridge.focus_completed.connect(self._on_focus_completed)
        self._bridge.minimize_requested.connect(self.showMinimized)
        self._bridge.fullscreen_requested.connect(self._toggle_fullscreen)
        self._bridge.focus_fullscreen_requested.connect(self._set_focus_fullscreen)
        self._bridge.close_requested.connect(self.close)
        self._index = Path(__file__).with_name("web") / "index.html"
        page_url = QUrl.fromLocalFile(str(self._index.resolve()))
        page_url.setQuery(f"v={self._index.stat().st_mtime_ns}")
        print(f"[自习室Web] 加载页面: {self._index.resolve()}")
        self._view.loadFinished.connect(self._on_load_finished)
        self._view.load(page_url)

    def _on_load_finished(self, success):
        state = "成功" if success else "失败"
        print(f"[自习室Web] 页面加载{state}: {self._index.resolve()}")

    def _on_focus_completed(self, payload):
        import json
        data = json.loads(payload)
        self.focus_completed.emit(data.get("task_name", ""), int(data.get("duration", 0)))

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self._focus_owns_fullscreen = False
        else:
            self.showFullScreen()
        self._is_fullscreen = self.isFullScreen()

    def _set_focus_fullscreen(self, enabled):
        """只撤销由专注模式主动进入的全屏，不覆盖用户原本的窗口状态。"""
        enabled = bool(enabled)
        if enabled and not self.isFullScreen():
            self.showFullScreen()
            self._focus_owns_fullscreen = True
        elif not enabled and self._focus_owns_fullscreen:
            self.showNormal()
            self._focus_owns_fullscreen = False
        self._is_fullscreen = self.isFullScreen()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self._toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._bridge.timer.active:
            answer = QMessageBox.question(
                self, "结束专注", "当前专注还在进行，关闭自习室会保存已进行的时间。确定关闭吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self._bridge.shutdown()
        self.closed.emit()
        event.accept()

    def shutdown(self):
        self._bridge.shutdown()
        self.hide()
        self.closed.emit()
