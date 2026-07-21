"""Compact Jiwen-style five-axis status view for the chat sidebar."""

from __future__ import annotations

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class _AxisBar(QWidget):
    def __init__(self, label: str, key: str, color: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.color = QColor(color)
        self.value = 0.0
        self.setMinimumHeight(22)
        self._label = QLabel(label)
        self._label.setFixedWidth(62)
        self._label.setStyleSheet("color:#B8C1D8; background:transparent;")
        self._label.setFont(QFont("Microsoft YaHei UI", 8))
        self._value = QLabel("0.00")
        self._value.setFixedWidth(36)
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setStyleSheet("color:#F1F4FF; background:transparent;")
        self._value.setFont(QFont("Consolas", 8))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._label)
        self._canvas = QWidget(self)
        self._canvas.paintEvent = self._paint_bar
        layout.addWidget(self._canvas, 1)
        layout.addWidget(self._value)

    def set_value(self, value: float):
        self.value = max(-1.0, min(1.0, float(value))) if self.key in {"valence", "arousal", "guardedness"} else max(0.0, min(1.0, float(value)))
        self._value.setText(f"{self.value:+.2f}" if self.key in {"valence", "arousal", "guardedness"} else f"{self.value:.2f}")
        self._canvas.update()

    def _paint_bar(self, event):
        painter = QPainter(self._canvas)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self._canvas.rect().adjusted(0, 7, 0, -7)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(34, 43, 65, 180))
        painter.drawRoundedRect(rect, 3, 3)
        signed = self.key in {"valence", "arousal", "guardedness"}
        if signed:
            mid = rect.left() + rect.width() / 2
            width = abs(self.value) * rect.width() / 2
            x = mid if self.value >= 0 else mid - width
            painter.setBrush(self.color)
            painter.drawRoundedRect(int(x), rect.top(), max(1, int(width)), rect.height(), 3, 3)
            painter.setPen(QColor(160, 174, 205, 100))
            painter.drawLine(int(mid), rect.top() - 2, int(mid), rect.bottom() + 2)
        else:
            painter.setBrush(self.color)
            painter.drawRoundedRect(rect.left(), rect.top(), int(rect.width() * self.value), rect.height(), 3, 3)


class JiwenStatusWidget(QWidget):
    """A low-cost live view; it polls the persisted v3 state, not the LLM."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(164)
        self.setStyleSheet("background:rgba(22,27,46,235); border:1px solid #3D4668; border-radius:14px;")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 9, 12, 9)
        root.setSpacing(4)
        header = QHBoxLayout()
        title = QLabel("AI 主动意识 · 五轴状态")
        title.setStyleSheet("color:#F0F3FF; background:transparent; font-weight:600;")
        title.setFont(QFont("Microsoft YaHei UI", 9))
        header.addWidget(title)
        header.addStretch()
        self._mood = QLabel("中性")
        self._mood.setStyleSheet("color:#8ED6E8; background:transparent;")
        self._mood.setFont(QFont("Microsoft YaHei UI", 8))
        header.addWidget(self._mood)
        root.addLayout(header)
        self._bars = {}
        for label, key, color in (("连接需求", "connection", "#F3C878"), ("骄傲/防御", "guardedness", "#A992FF"), ("愉悦度", "valence", "#72D7E8"), ("唤醒度", "arousal", "#F49BBE"), ("沉浸度", "immersion", "#86D6A6")):
            self._bars[key] = _AxisBar(label, key, color, self)
            root.addWidget(self._bars[key])
        self._motive = QLabel("动机：平静 · 等待新的交流")
        self._motive.setStyleSheet("color:#929DB8; background:transparent;")
        self._motive.setFont(QFont("Microsoft YaHei UI", 8))
        root.addWidget(self._motive)
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self):
        try:
            from brain.emotional import get_manager
            manager = get_manager()
            info = manager.get_debug_info()
            for key, bar in self._bars.items():
                bar.set_value((info.get("axes") or {}).get(key, 0.0))
            self._mood.setText(str(info.get("middle_layer") or "中性"))
            motive = manager.get_proactive_motive() or {}
            self._motive.setText(f"动机：{motive.get('motive') or motive.get('action') or '平静 · 等待新的交流'}")
        except Exception:
            self._mood.setText("状态暂不可用")

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
