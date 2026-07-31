from __future__ import annotations

import hashlib
import re
from pathlib import Path
from PyQt5.QtCore import QUrl, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineView
from PyQt5.QtWidgets import QMainWindow
from .bridge import AchievementBridge


class AchievementWindow(QMainWindow):
    closed = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("莲心 · 数据潮汐")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumSize(1040, 700); self.resize(1500, 900)
        self._bridge = AchievementBridge(self)
        self._view = QWebEngineView(self); self.setCentralWidget(self._view)
        self._profile = QWebEngineProfile(self); self._profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        page = QWebEnginePage(self._profile, self._view); page.setBackgroundColor(QColor("#f8f1e7")); self._view.setPage(page)
        settings = self._view.settings(); settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True); settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True); settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        self._channel = QWebChannel(self._view); self._channel.registerObject("achievementBridge", self._bridge); page.setWebChannel(self._channel)
        self._bridge.close_requested.connect(self.close); self._bridge.minimize_requested.connect(self.showMinimized); self._bridge.fullscreen_requested.connect(self._toggle_fullscreen)
        self._index = Path(__file__).with_name("web") / "index.html"; self._fullscreen = False; self._load()

    def _load(self):
        root = self._index.parent; html = self._index.read_text(encoding="utf-8")
        for asset in ("styles.css", "app.js"):
            digest = hashlib.sha256((root / asset).read_bytes()).hexdigest()[:12]
            html = re.sub(rf'{re.escape(asset)}(?:\?v=[^"\']+)?', f"{asset}?v={digest}", html)
        self._view.setHtml(html, QUrl.fromLocalFile(str(root.resolve()) + "/"))

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self.setWindowFlag(Qt.FramelessWindowHint, self._fullscreen)
        self.showMaximized() if self._fullscreen else self.showNormal()

    def closeEvent(self, event):
        self.closed.emit(); super().closeEvent(event)
