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
from PyQt5.QtCore import Qt, QPoint, QTimer, pyqtSignal, QPropertyAnimation, QSequentialAnimationGroup, QParallelAnimationGroup
from PyQt5.QtGui import QPixmap, QMouseEvent
from PyQt5.QtCore import QAbstractAnimation
from PyQt5.QtWidgets import QGraphicsOpacityEffect


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
        """按当前缩放比例渲染图片（以图像中心为原点）。"""
        if self._original_pixmap is None:
            return
        old_center = self.geometry().center()
        w = max(50, int(self._original_pixmap.width() * self._scale))
        h = max(50, int(self._original_pixmap.height() * self._scale))
        scaled = self._original_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._image_label.setPixmap(scaled)
        self._image_label.resize(scaled.size())
        self.resize(scaled.size())
        delta = old_center - self.geometry().center()
        self.move(self.pos() + delta)



    def set_image(self, image_path: str):
        """切换立绘图片。"""


        current_pixmap = self._image_label.pixmap()
        if current_pixmap and not current_pixmap.isNull():
            self._old_label.setPixmap(current_pixmap)
            self._old_label.resize(self._image_label.size())
            self._old_label.show()
        else:
            self._old_label.hide()

        self._image_path = image_path
        new_pixmap = QPixmap(image_path)
        self._load_image(new_pixmap)

        # ── 淡入淡出动画 ──
        opacity_new = QGraphicsOpacityEffect(self._image_label)
        self._image_label.setGraphicsEffect(opacity_new)
        opacity_new.setOpacity(0.0)

        opacity_old = QGraphicsOpacityEffect(self._old_label)
        self._old_label.setGraphicsEffect(opacity_old)
        opacity_old.setOpacity(1.0)

        self._in_animation = True

        fade_in = QPropertyAnimation(opacity_new, b"opacity")
        fade_in.setDuration(250)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)

        fade_out = QPropertyAnimation(opacity_old, b"opacity")
        fade_out.setDuration(250)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)

        group = QParallelAnimationGroup()
        group.addAnimation(fade_in)
        group.addAnimation(fade_out)
        group.finished.connect(self._on_fade_done)
        group.start(QAbstractAnimation.DeleteWhenStopped)

    def _on_fade_done(self):
        """淡入淡出完成后播放弹动动画。"""
        self._old_label.hide()
        self._image_label.setGraphicsEffect(None)
        self._in_animation = False
        self._play_bounce()

    def _play_bounce(self):
        """轻微的上下弹动，模拟 ZcChat 的二次动画效果。"""
        pos = self._image_label.pos()
        anim = QSequentialAnimationGroup(self)

        up = QPropertyAnimation(self._image_label, b"pos")
        up.setDuration(120)
        up.setStartValue(pos)
        up.setEndValue(pos + QPoint(0, -8))

        down = QPropertyAnimation(self._image_label, b"pos")
        down.setDuration(120)
        down.setStartValue(pos + QPoint(0, -8))
        down.setEndValue(pos)

        anim.addAnimation(up)
        anim.addAnimation(down)
        anim.start(QAbstractAnimation.DeleteWhenStopped)

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
