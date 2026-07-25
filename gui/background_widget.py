"""Reusable, low-cost background layer for the desktop main window."""
from __future__ import annotations

import random
from pathlib import Path

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import QWidget


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


class BackgroundWidget(QWidget):
    """Paint a user-selected image behind the normal central-widget children.

    The widget never changes child opacity.  Only the pixmap is painted with
    the configured alpha, so chat controls remain crisp and accessible.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = ""
        self._source_type = "single"
        self._fit_mode = "cover"
        self._opacity = 0.22
        self._resolved_path = ""
        self._pixmap = QPixmap()
        self.setAttribute(Qt.WA_StyledBackground, True)

    @staticmethod
    def image_files(folder: str) -> list[Path]:
        path = Path(folder).expanduser()
        if not path.is_dir():
            return []
        try:
            return sorted(
                (item for item in path.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS),
                key=lambda item: item.name.lower(),
            )
        except OSError:
            return []

    def _resolve_path(self, source: str, source_type: str) -> str:
        path = Path(source).expanduser()
        if source_type == "folder_random":
            files = self.image_files(str(path))
            return str(random.choice(files)) if files else ""
        if source_type in {"folder_first", "folder"}:
            files = self.image_files(str(path))
            return str(files[0]) if files else ""
        return str(path) if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS else ""

    def set_background(self, source: str, opacity: float = 0.22,
                       source_type: str = "single", fit_mode: str = "cover") -> None:
        source = str(source or "").strip()
        source_type = source_type if source_type in {"single", "folder_random", "folder_first"} else "single"
        fit_mode = fit_mode if fit_mode in {"cover", "contain", "stretch"} else "cover"
        needs_resolve = source != self._source or source_type != self._source_type
        self._source, self._source_type, self._fit_mode = source, source_type, fit_mode
        self._opacity = max(0.0, min(1.0, float(opacity)))
        if needs_resolve:
            self._resolved_path = self._resolve_path(source, source_type)
            self._pixmap = QPixmap(self._resolved_path) if self._resolved_path else QPixmap()
        self.update()

    def clear_background(self) -> None:
        self.set_background("", self._opacity, "single", self._fit_mode)

    @property
    def resolved_path(self) -> str:
        return self._resolved_path

    def paintEvent(self, event):  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 12, 12)
        painter.setClipPath(clip)
        # Always keep an opaque dark base. The wallpaper is an overlay on top
        # of it, so lowering its opacity never reveals the user's desktop.
        painter.fillRect(self.rect(), QColor("#10162A"))
        if self._pixmap.isNull() or self._opacity <= 0:
            painter.end()
            return
        target = self.rect()
        if self._fit_mode == "stretch":
            scaled = self._pixmap.scaled(target.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        elif self._fit_mode == "contain":
            scaled = self._pixmap.scaled(target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            scaled = self._pixmap.scaled(target.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        painter.setOpacity(self._opacity)
        x = target.x() + (target.width() - scaled.width()) // 2
        y = target.y() + (target.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()


class FrostedPanel(QWidget):
    """A deterministic frosted-glass surface painted behind child widgets."""

    def __init__(self, parent=None, opacity: float = 0.75):
        super().__init__(parent)
        self._opacity = max(0.0, min(1.0, float(opacity)))
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)

    def set_opacity(self, opacity: float):
        self._opacity = max(0.0, min(1.0, float(opacity)))
        self.update()

    @property
    def opacity(self) -> float:
        return self._opacity

    def paintEvent(self, event):  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.setClipPath(path)

        alpha = round(self._opacity * 255)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor(24, 32, 55, alpha))
        gradient.setColorAt(1, QColor(13, 20, 38, alpha))
        painter.fillRect(rect, gradient)

        # A very subtle fixed grain/line pattern gives the surface a frosted
        # texture without introducing animation or repaint flicker.
        if self._opacity > 0.03:
            painter.setPen(QColor(180, 205, 255, min(18, round(alpha * 0.08))))
            for x in range(0, self.width(), 8):
                painter.drawLine(x, 0, x + self.height(), self.height())
        painter.setPen(QColor(150, 180, 255, min(55, round(alpha * 0.22))))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        painter.end()
