"""Reusable, low-cost background layer for the desktop main window."""
from __future__ import annotations

import random
from pathlib import Path

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPixmap
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
        # With a valid wallpaper the central surface itself must remain
        # transparent; otherwise this fallback fill hides the image before
        # child widgets (including the chat mask) can be composited.
        if self._pixmap.isNull() or self._opacity <= 0:
            painter.fillRect(self.rect(), QColor("#1A1A2E"))
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
