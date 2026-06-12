"""
TachieWindow：莲心 Galgame 模式 — 立绘窗口
无边框、透明背景、可拖拽、始终置顶。
支持两种模式：
  1. 静态立绘：JPG/PNG 图片 + 淡入淡出 + 弹动动画
  2. Live2D：内嵌 QWebEngineView + PixiJS + Cubism 4
自动检测 assets/live2d/models/ 下是否有 Live2D 模型，优先使用 Live2D。
"""
import os
import math
from pathlib import Path
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QPoint, QTimer, pyqtSignal, QPropertyAnimation, QSequentialAnimationGroup, QParallelAnimationGroup, QAbstractAnimation, pyqtProperty, QEasingCurve

from PyQt5.QtGui import QPixmap, QMouseEvent



class TachieWindow(QWidget):
    """Galgame 风格的角色立绘窗口。"""

    # 拖拽时发射当前位置（主窗口用来移动对话框）
    position_changed = pyqtSignal(int, int)
    # 右键点击发射（主窗口用来切换对话框显示）
    toggle_dialog_requested = pyqtSignal()

    def __init__(self, assets_dir: str | Path, parent=None):
        super().__init__(parent)
        self._assets_dir = Path(assets_dir)
        self._pinned = True
        self._window_opacity = 0.95
        self._in_animation = False
        self._scale = 1.0
        self._original_pixmap = None
        self._breath_offset = 0.0
        self._breath_anim = None
        self._bounce_timer = None
        self._bounce_anim = None

        self._init_window()
        self._init_ui()
        self._image_path = str(self._assets_dir / "莲心形象透明背景.png")
        self._load_image()


    @staticmethod
    def _detect_live2d() -> bool:
        return False


    def _init_window(self):
        self.setWindowTitle("莲心 - 立绘")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)

    def _init_ui(self):
        self.setMinimumSize(100, 100)
        self._old_label = QLabel(self)
        self._old_label.setAlignment(Qt.AlignCenter)
        self._old_label.setStyleSheet("background: transparent;")
        self._old_label.hide()

        self._image_label = QLabel(self)
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setStyleSheet("background: transparent;")



    def _load_image(self, pixmap: QPixmap = None):
        """加载并显示立绘图片。"""
        if pixmap is None:
            if not os.path.exists(self._image_path):
                self._image_label.setText("（暂无立绘）")
                self.resize(200, 300)
                return
            pixmap = QPixmap(self._image_path)
            if pixmap.isNull():
                self._image_label.setText("（图片加载失败）")
                self.resize(200, 300)
                return

        self._original_pixmap = pixmap
        # 初始尺寸：占屏幕 1/15 面积
        screen = self.screen().availableGeometry()
        target_area = screen.width() * screen.height() / 15
        orig_w = pixmap.width()
        orig_h = pixmap.height()
        target_w = max(50, int(math.sqrt(target_area * orig_w / orig_h)))
        target_h = max(50, int(target_area / target_w))
        self._scale = target_w / orig_w
        self._apply_scale()


    def _apply_scale(self):
        if self._original_pixmap is None:
            return
        old_center = self.geometry().center()
        effective_scale = self._scale * (1.0 + self._breath_offset * 0.02)

        w = max(50, int(self._original_pixmap.width() * effective_scale))
        h = max(50, int(self._original_pixmap.height() * effective_scale))
        scaled = self._original_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._image_label.setPixmap(scaled)
        self._image_label.resize(scaled.size())
        self.resize(scaled.size())
        delta = old_center - self.geometry().center()
        self.move(self.pos() + delta)


    # ── 呼吸动画 ─────────────────────────────────────────

    def _get_breath_offset(self):
        return self._breath_offset

    def _set_breath_offset(self, value):
        self._breath_offset = value
        self._apply_scale()

    breath_offset = pyqtProperty(float, _get_breath_offset, _set_breath_offset)

    def start_breathing(self):
        if self._breath_anim is not None:
            return
        # 0 → 1 (吸气扩大): 末尾减速
        a1 = QPropertyAnimation(self, b"breath_offset")
        a1.setDuration(1500)
        a1.setStartValue(0.0)
        a1.setEndValue(1.0)
        a1.setEasingCurve(QEasingCurve.OutCubic)

        # 1 → 0 (回中): 开头加速
        a2 = QPropertyAnimation(self, b"breath_offset")
        a2.setDuration(1500)
        a2.setStartValue(1.0)
        a2.setEndValue(0.0)
        a2.setEasingCurve(QEasingCurve.InCubic)

        # 0 → -1 (呼气缩小): 末尾减速
        a3 = QPropertyAnimation(self, b"breath_offset")
        a3.setDuration(1500)
        a3.setStartValue(0.0)
        a3.setEndValue(-1.0)
        a3.setEasingCurve(QEasingCurve.OutCubic)

        # -1 → 0 (回中): 开头加速
        a4 = QPropertyAnimation(self, b"breath_offset")
        a4.setDuration(1500)
        a4.setStartValue(-1.0)
        a4.setEndValue(0.0)
        a4.setEasingCurve(QEasingCurve.InCubic)

        self._breath_anim = QSequentialAnimationGroup(self)
        self._breath_anim.addAnimation(a1)
        self._breath_anim.addAnimation(a2)
        self._breath_anim.addAnimation(a3)
        self._breath_anim.addAnimation(a4)
        self._breath_anim.setLoopCount(-1)   # ← 关键：自动循环，无延迟
        self._breath_anim.start()


    def stop_breathing(self):
        if self._breath_anim:
            self._breath_anim.stop()
            self._breath_anim = None
        self._breath_offset = 0.0
        self._apply_scale()

    # ── 说话跳动 ─────────────────────────────────────────

    def start_talking(self):
        if self._bounce_timer is not None:
            return
        self._bounce_timer = QTimer(self)
        self._bounce_timer.timeout.connect(self._play_bounce)
        self._bounce_timer.start(450)

    def stop_talking(self):
        if self._bounce_timer:
            self._bounce_timer.stop()
            self._bounce_timer = None


    def set_image(self, image_path: str):
        """切换立绘图片。"""
        self._old_label.hide()
        self._image_path = image_path
        new_pixmap = QPixmap(image_path)
        if new_pixmap.isNull():
            return
        self._original_pixmap = new_pixmap
        self._apply_scale()
        self._play_bounce()


    def _play_bounce(self):
        if self._bounce_anim is not None and self._bounce_anim.state() == QAbstractAnimation.Running:
            return
        pos = self._image_label.pos()
        anim = QSequentialAnimationGroup(self)
        up = QPropertyAnimation(self._image_label, b"pos")
        up.setDuration(100)
        up.setStartValue(pos)
        up.setEndValue(pos + QPoint(0, -16))
        down = QPropertyAnimation(self._image_label, b"pos")
        down.setDuration(100)
        down.setStartValue(pos + QPoint(0, -16))
        down.setEndValue(pos)
        anim.addAnimation(up)
        anim.addAnimation(down)
        anim.finished.connect(lambda: setattr(self, '_bounce_anim', None))
        self._bounce_anim = anim
        anim.start()



    # ── Live2D 控制代理 ─────────────────────────────────────

    def is_pinned(self) -> bool:
        return self._pinned

    def set_pinned(self, pinned: bool):
        self._pinned = pinned
        flags = Qt.FramelessWindowHint | Qt.Tool
        if pinned:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    # ── 鼠标拖拽 + 信号 ─────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.RightButton:
            self.toggle_dialog_requested.emit()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if (event.buttons() & (Qt.LeftButton | Qt.MiddleButton)) and hasattr(self, '_drag_pos'):
            self.move(event.globalPos() - self._drag_pos)
            self.position_changed.emit(self.x(), self.y())
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() in (Qt.LeftButton, Qt.MiddleButton) and hasattr(self, '_drag_pos'):
            del self._drag_pos
            event.accept()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self._scale = min(3.0, self._scale * 1.06)
        else:
            self._scale = max(0.3, self._scale / 1.06)
        self._apply_scale()
        event.accept()

    def closeEvent(self, event):
        super().closeEvent(event)
