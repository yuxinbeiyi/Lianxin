from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class AchievementUnlockToast(QWidget):
    """主窗口级成就解锁提示，独立于数据潮汐网页显示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet(
            "AchievementUnlockToast { background: #183842; border: 1px solid #6ea6aa; border-radius: 7px; }"
            "QLabel { color: #f6eee1; font-family: 'Microsoft YaHei UI'; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 13, 18, 13)
        layout.setSpacing(12)
        self._art = QLabel("✦", self)
        self._art.setStyleSheet("font-size: 30px; color: #e7c37b;")
        layout.addWidget(self._art)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        self._headline = QLabel("成就解锁", self)
        self._headline.setStyleSheet("font-size: 16px; font-weight: 700;")
        self._detail = QLabel(self)
        self._detail.setStyleSheet("font-size: 16px; color: #c7e0df;")
        text_layout.addWidget(self._headline)
        text_layout.addWidget(self._detail)
        layout.addLayout(text_layout)
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self.hide)

    def show_achievements(self, achievements: list[dict]) -> None:
        """展示本批新解锁成就，并合并同一轮的多条提示。"""
        if not achievements:
            return
        first = achievements[0]
        art_map = {"shell": "◔", "star": "✦", "bottle": "◒", "boat": "△", "scope": "◉", "anchor": "⚓", "pearl": "○", "music": "♫"}
        self._art.setText(art_map.get(str(first.get("art") or ""), "✦"))
        self._detail.setText(
            str(first.get("title") or "新的贝壳")
            if len(achievements) == 1
            else f"{first.get('title') or '新的贝壳'}，另有 {len(achievements) - 1} 项"
        )
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)
        self.show()
        self.raise_()
        self._close_timer.start(6500)

    def mousePressEvent(self, event):
        """允许用户点击提示立即关闭。"""
        self.hide()
        super().mousePressEvent(event)
