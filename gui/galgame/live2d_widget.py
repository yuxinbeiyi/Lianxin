"""
Live2DWidget：基于 QWebEngineView + PixiJS + Cubism 4 的 Live2D 渲染组件。
内嵌本地 HTTP 服务器（守护线程），加载 HTML 页面渲染 Live2D 模型。
通过 QWebChannel 实现 Python <-> JavaScript 双向通信。
"""
import os
import socket
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal, QUrl, Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel


class _Live2DBridge(QObject):
    """Python <-> JavaScript 桥接对象（QWebChannel）。"""

    model_ready = pyqtSignal()
    window_drag_started = pyqtSignal(int, int)   # screenX, screenY
    window_drag_moved = pyqtSignal(int, int)     # screenX, screenY
    window_drag_ended = pyqtSignal()
    right_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ready = False

    # 以下方法由 JS 调用（pyqtSlot）

    @pyqtSlot()
    def onModelReady(self):
        if not self._ready:
            self._ready = True
            self.model_ready.emit()

    @pyqtSlot(int, int)
    def onDragStart(self, screenX: int, screenY: int):
        self.window_drag_started.emit(screenX, screenY)

    @pyqtSlot(int, int)
    def onDragMove(self, screenX: int, screenY: int):
        self.window_drag_moved.emit(screenX, screenY)

    @pyqtSlot()
    def onDragEnd(self):
        self.window_drag_ended.emit()

    @pyqtSlot()
    def onRightClick(self):
        self.right_clicked.emit()

    def is_ready(self) -> bool:
        return self._ready


class Live2DWidget(QWidget):
    """基于 WebEngine 的 Live2D 渲染组件。"""

    # 窗口拖拽信号（由桥转发）
    window_drag_started = pyqtSignal(int, int)
    window_drag_moved = pyqtSignal(int, int)
    window_drag_ended = pyqtSignal()
    right_clicked = pyqtSignal()

    def __init__(self, assets_dir: str | Path, parent=None):
        super().__init__(parent)
        self._assets_dir = Path(assets_dir)
        self._server = None
        self._server_thread = None
        self._port = self._find_free_port()
        self._bridge = _Live2DBridge()
        self._view = None

        # 转发桥信号
        self._bridge.model_ready.connect(self._on_model_ready)
        self._bridge.window_drag_started.connect(self.window_drag_started)
        self._bridge.window_drag_moved.connect(self.window_drag_moved)
        self._bridge.window_drag_ended.connect(self.window_drag_ended)
        self._bridge.right_clicked.connect(self.right_clicked)

        self._start_server()
        self._init_ui()

    # ── HTTP 服务器（守护线程） ────────────────────────────────

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _start_server(self):
        from functools import partial

        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # 不打印请求日志

        assets_dir = str(self._assets_dir)
        handler = partial(QuietHandler, directory=assets_dir)
        self._server = HTTPServer(("127.0.0.1", self._port), handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._server_thread.start()

    # ── UI ────────────────────────────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._view = QWebEngineView(self)
        self._view.setAttribute(Qt.WA_TranslucentBackground, True)
        self._view.setStyleSheet("background: transparent;")
        page = self._view.page()
        page.setBackgroundColor(Qt.transparent)

        # QWebChannel
        channel = QWebChannel(self._view)
        channel.registerObject("bridge", self._bridge)
        page.setWebChannel(channel)

        self._view.load(QUrl(f"http://127.0.0.1:{self._port}/live2d.html"))
        layout.addWidget(self._view)

        self.setLayout(layout)

    @property
    def bridge(self) -> _Live2DBridge:
        return self._bridge

    # ── 模型就绪回调 ──────────────────────────────────────────

    def _on_model_ready(self):
        """模型加载完成后的后续处理。"""

    # ── 公共 API ──────────────────────────────────────────────

    def is_model_ready(self) -> bool:
        return self._bridge.is_ready()

    def set_mouth_value(self, value: float):
        """设置嘴部张开值（0.0 ~ 1.0），用于唇形同步。"""
        self._view.page().runJavaScript(f"window._live2d?.setMouthValue({value})")

    def set_scale(self, scale: float):
        """缩放模型（相对值相乘）。"""
        self._view.page().runJavaScript(f"window._live2d?.setScaleRelative({scale})")

    def reset_view(self):
        """重置模型位置和缩放。"""
        self._view.page().runJavaScript("window._live2d?.resetView()")

    def resize_window(self, w: int, h: int):
        """通知 JS 窗口大小变化。"""
        self._view.page().runJavaScript(f"window._live2d?.onResize({w},{h})")

    # ── 释放 ──────────────────────────────────────────────────

    def shutdown(self):
        """关闭 HTTP 服务器，销毁 WebEngine 页面。"""
        if self._view:
            self._view.page().runJavaScript("window._live2d?.destroy()")
        if self._server:
            self._server.shutdown()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
