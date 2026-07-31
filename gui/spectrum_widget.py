"""
SpectrumWidget：模拟音乐频谱跳动条（居中正态分布）
"""

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QPainter, QLinearGradient, QColor
import random
import math


class SpectrumWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(32)
        self.setMaximumHeight(40)

        self.bar_count = 64
        self.bar_heights = [0.0] * self.bar_count
        self.is_playing = False
        self.volume = 0.5

        self._gauss_weights = self._compute_gauss_weights()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_heights)
        self.timer.start(30)

    def _compute_gauss_weights(self):
        weights = []
        mean = (self.bar_count - 1) / 2
        sigma = self.bar_count / 5   # 可调整宽度
        for i in range(self.bar_count):
            x = i - mean
            w = math.exp(- (x * x) / (2 * sigma * sigma))
            weights.append(w)
        max_w = max(weights)
        return [w / max_w for w in weights]

    def set_playing(self, playing: bool):
        self.is_playing = playing

    def set_volume(self, volume: float):
        self.volume = max(0.0, min(1.0, volume))

    def _update_heights(self):
        if not self.is_playing or self.volume < 0.005:
            for i in range(self.bar_count):
                self.bar_heights[i] = max(0.0, self.bar_heights[i] - random.uniform(3, 7))
        else:
            # 最大允许高度：控件高度减去 2 像素（避免顶到进度条）
            max_allowed = self.height() - 2
            # 基础幅度：随音量增大而增大（最高约 max_allowed 的 80%）
            base_amp = (self.volume ** 1.6) * (max_allowed * 0.85)
            for i in range(self.bar_count):
                target = self._gauss_weights[i] * base_amp
                # 小幅度随机波动，增加生动性（范围窄，保持正态形状）
                target *= random.uniform(0.85, 1.15)
                # 平滑过渡
                self.bar_heights[i] = self.bar_heights[i] * 0.4 + target * 0.6
                if self.bar_heights[i] > max_allowed:
                    self.bar_heights[i] = max_allowed
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()
        w = width / self.bar_count
        gradient = QLinearGradient(0, 0, width, 0)
        gradient.setColorAt(0, QColor(100, 150, 255))
        gradient.setColorAt(1, QColor(75, 100, 255))

        for i, h in enumerate(self.bar_heights):
            if h <= 0:
                continue
            x = int(i * w)
            rect_w = max(1, int(w - 1))
            rect_h = max(2, int(h))
            y = height - rect_h
            painter.fillRect(x, y, rect_w, rect_h, gradient)
        painter.end()
