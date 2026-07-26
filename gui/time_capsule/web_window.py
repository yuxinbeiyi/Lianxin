"""Time Capsule 的 QWebEngine 宿主窗口。"""

import hashlib
import re
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QUrl, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineWidgets import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineView,
)
from PyQt5.QtWidgets import QMainWindow

from .bridge import TimeCapsuleBridge


class TimeCapsulePage(QWebEnginePage):
    def __init__(self, profile, parent=None, *, log_path=None):
        super().__init__(profile, parent)
        self._log_path = Path(log_path) if log_path else None

    def _log(self, message):
        if not self._log_path:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as stream:
                stream.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
        except OSError:
            pass

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        print(f"[时间胶囊Web] {message} ({source_id}:{line_number})")
        self._log(f"JS[{int(level)}] {message} ({source_id}:{line_number})")
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
        self._stable_fullscreen = False
        self._restore_geometry = None
        self._restore_maximized = False
        self._bridge = TimeCapsuleBridge(self, db_path=db_path)
        if generation_callback:
            self._bridge.generation_requested.connect(generation_callback)
        if settings_callback:
            self._bridge.settings_changed.connect(settings_callback)
        self._view = QWebEngineView(self)
        # 时间胶囊只加载本地静态资源，不需要 Cookie 或磁盘缓存。使用独立的
        # off-the-record profile，避免上次异常退出遗留的 GPUCache 锁拖慢新窗口。
        self._profile = QWebEngineProfile(self)
        self._profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        self._web_log = Path(__file__).resolve().parents[2] / "logs" / "time_capsule_web.log"
        page = TimeCapsulePage(self._profile, self._view, log_path=self._web_log)
        self._view.setPage(page)
        self._view.setContextMenuPolicy(Qt.NoContextMenu)
        # Qt 5 WebEngine 在 Windows 原生全屏中与中文输入法候选窗叠加时，
        # 可能触发透明背景的连续重绘。使用不透明绘制配合无边框最大化规避。
        self._view.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._view.setAttribute(Qt.WA_InputMethodEnabled, True)
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
        self._view.loadFinished.connect(self._on_load_finished)
        page.renderProcessTerminated.connect(self._on_render_process_terminated)
        self._load_frontend()

    def _write_web_log(self, message):
        try:
            self._web_log.parent.mkdir(parents=True, exist_ok=True)
            with self._web_log.open("a", encoding="utf-8") as stream:
                stream.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
        except OSError:
            pass

    def _load_frontend(self):
        """一次装入同一版本的 HTML/CSS/JS，避免旧页面与新脚本交叉缓存。"""
        web_dir = self._index.parent
        html = self._index.read_text(encoding="utf-8")
        for asset in ("styles.css", "app.js"):
            digest = hashlib.sha256((web_dir / asset).read_bytes()).hexdigest()[:12]
            html = re.sub(rf'{re.escape(asset)}(?:\?v=[^"\']+)?', f"{asset}?v={digest}", html)
        base_url = QUrl.fromLocalFile(str(web_dir.resolve()) + "/")
        self._view.setHtml(html, base_url)

    def _on_load_finished(self, ok):
        self._write_web_log(f"LOAD finished ok={bool(ok)} source={self._index}")

    def _on_render_process_terminated(self, status, exit_code):
        self._write_web_log(f"RENDER terminated status={int(status)} exit_code={exit_code}")

    def _toggle_fullscreen(self):
        """使用无边框最大化的稳定沉浸模式，避免 Windows IME 在原生全屏闪烁。"""
        if self._stable_fullscreen:
            self.setWindowFlag(Qt.FramelessWindowHint, False)
            if self._restore_maximized:
                self.showMaximized()
            else:
                self.showNormal()
                if self._restore_geometry is not None:
                    self.restoreGeometry(self._restore_geometry)
            self._stable_fullscreen = False
        else:
            self._restore_geometry = self.saveGeometry()
            self._restore_maximized = self.isMaximized()
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.showMaximized()
            self._stable_fullscreen = True
            self._view.setFocus()
        self._is_fullscreen = self._stable_fullscreen

    def refresh(self, day: str | None = None):
        self._bridge.emit_state(day)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._stable_fullscreen:
            self._toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()
