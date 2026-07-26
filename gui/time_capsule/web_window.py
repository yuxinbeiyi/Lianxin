"""Time Capsule 的 QWebEngine 宿主窗口。"""

from pathlib import Path

from PyQt5.QtCore import QUrl, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineWidgets import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineView,
)
from PyQt5.QtWidgets import QMainWindow

from utils.paths import get_user_data_dir
from .bridge import TimeCapsuleBridge


class TimeCapsulePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        print(f"[时间胶囊Web] {message} ({source_id}:{line_number})")
        super().javaScriptConsoleMessage(level, message, line_number, source_id)


class TimeCapsuleWindow(QMainWindow):
    closed = pyqtSignal()

    def __init__(self, parent=None, *, generation_callback=None, settings_callback=None,
                 db_path=None):
        super().__init__(parent)
        self.setWindowTitle("莲心 Time Capsule")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumSize(1040, 700)
        self.resize(1500, 900)
        self._is_fullscreen = False
        self._bridge = TimeCapsuleBridge(self, db_path=db_path)
        if generation_callback:
            self._bridge.generation_requested.connect(generation_callback)
        if settings_callback:
            self._bridge.settings_changed.connect(settings_callback)
        self._view = QWebEngineView(self)
        self._profile = QWebEngineProfile("LianxinTimeCapsule", self)
        data_dir = get_user_data_dir() / "time_capsule_webengine"
        self._profile.setPersistentStoragePath(str(data_dir))
        self._profile.setCachePath(str(data_dir / "cache"))
        self._profile.setHttpCacheType(QWebEngineProfile.NoCache)
        self._view.setPage(TimeCapsulePage(self._profile, self._view))
        self._view.setContextMenuPolicy(Qt.NoContextMenu)
        self._view.page().setBackgroundColor(QColor("#1F1F21"))
        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        self.setCentralWidget(self._view)
        self._channel = QWebChannel(self._view)
        self._channel.registerObject("capsuleBridge", self._bridge)
        self._view.page().setWebChannel(self._channel)
        self._bridge.close_requested.connect(self.close)
        self._bridge.minimize_requested.connect(self.showMinimized)
        self._bridge.fullscreen_requested.connect(self._toggle_fullscreen)
        self._index = Path(__file__).with_name("web") / "index.html"
        page_url = QUrl.fromLocalFile(str(self._index.resolve()))
        page_url.setQuery(f"v={self._index.stat().st_mtime_ns}")
        self._view.load(page_url)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self._is_fullscreen = self.isFullScreen()

    def refresh(self, day: str | None = None):
        self._bridge.emit_state(day)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self._toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()
