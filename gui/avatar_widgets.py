"""聊天头像控件、裁剪窗口与全局设置页。"""
from pathlib import Path
import shutil

from PyQt5.QtCore import Qt, QPoint, QRectF, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap, QPainter, QPainterPath, QColor
from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QDialog, QDialogButtonBox, QSlider, QMessageBox,
)

from config import get_chat_avatar_config, save_chat_avatar_config
from utils.paths import get_user_data_dir


def _default_assistant_path():
    return str(Path(__file__).resolve().parent.parent / "assets" / "莲心形象透明背景.png")


class CircularAvatar(QLabel):
    double_clicked = pyqtSignal(str)
    clicked = pyqtSignal(str)
    long_pressed = pyqtSignal(str)
    context_requested = pyqtSignal(str)
    """固定尺寸的抗锯齿圆形头像，图片失效时自动回退占位。"""
    def __init__(self, role="assistant", size=42, parent=None):
        super().__init__(parent)
        self.role = role
        self._size = int(size)
        self.setFixedSize(self._size, self._size)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.reload()

    def reload(self):
        cfg = get_chat_avatar_config()
        self.setVisible(bool(cfg.get("enabled", True)))
        self._size = max(40, min(100, int(cfg.get("size", 60))))
        self.setFixedSize(self._size, self._size)
        self._path = cfg.get("assistant_path" if self.role == "assistant" else "user_path", "")
        if self.role == "assistant" and not self._path:
            self._path = _default_assistant_path()
        self._border = bool(cfg.get("border", True))
        self._shake_offsets = [0, -4, 5, -5, 4, -3, 2, 0]
        self._headpat_offsets = [0, -2, -4, -3, -1, 0, 1, 0]
        self._shake_step = 0
        self._animation_kind = "tap"
        if not hasattr(self, "_shake_timer"):
            self._shake_timer = QTimer(self)
            self._shake_timer.timeout.connect(self._advance_shake)
        if not hasattr(self, "_press_timer"):
            self._press_timer = QTimer(self)
            self._press_timer.setSingleShot(True)
            self._press_timer.setInterval(650)
            self._press_timer.timeout.connect(self._emit_long_press)
        self._press_active = False
        self._suppress_click = False
        self.update()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._suppress_click = True
            self.play_tap_animation()
            self.double_clicked.emit(self.role)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        if event.reason() == event.Mouse:
            self.context_requested.emit(self.role)
            event.accept()
            return
        super().contextMenuEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_active = True
            self._suppress_click = False
            self._press_timer.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_long = not self._press_timer.isActive()
            self._press_timer.stop()
            if self._press_active and not was_long and not self._suppress_click:
                self.clicked.emit(self.role)
            self._press_active = False
        super().mouseReleaseEvent(event)

    def _emit_long_press(self):
        if self._press_active:
            self.long_pressed.emit(self.role)

    def play_tap_animation(self):
        if not get_chat_avatar_config().get("animation_enabled", True):
            return
        self._shake_step = 0
        self._animation_kind = "tap"
        self._shake_timer.start(34)

    def play_headpat_animation(self):
        if not get_chat_avatar_config().get("animation_enabled", True):
            return
        self._shake_step = 0
        self._animation_kind = "headpat"
        self._shake_timer.start(48)

    def _advance_shake(self):
        self._shake_step += 1
        if self._shake_step >= len(self._shake_offsets):
            self._shake_timer.stop()
            self._shake_step = 0
        self.update()

    def set_preview_path(self, path):
        self._path = path or (_default_assistant_path() if self.role == "assistant" else "")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        active = getattr(self, "_shake_timer", None) and self._shake_timer.isActive()
        if active and self._animation_kind == "headpat":
            painter.translate(0, self._headpat_offsets[self._shake_step])
        else:
            offset = self._shake_offsets[self._shake_step] if active else 0
            painter.translate(offset, 0)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath(); path.addEllipse(QRectF(rect))
        painter.setClipPath(path)
        pix = QPixmap(self._path) if self._path and Path(self._path).is_file() else QPixmap()
        if pix.isNull():
            painter.fillRect(rect, QColor("#6870A8" if self.role == "assistant" else "#377C69"))
            painter.setPen(Qt.white)
            painter.drawText(rect, Qt.AlignCenter, "莲" if self.role == "assistant" else "我")
        else:
            scaled = pix.scaled(rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            painter.drawPixmap(rect, scaled, scaled.rect())
        painter.setClipping(False)
        if self._border:
            painter.setPen(QColor("#AAB4FF" if self.role == "assistant" else "#8BD8BA"))
            painter.setBrush(Qt.NoBrush); painter.drawEllipse(rect)
        painter.end()


class _CropCanvas(QLabel):
    """可拖动、可缩放的裁剪画布，支持正方形和竖版头像比例。"""

    def __init__(self, pixmap, crop_ratio=1.0, parent=None):
        super().__init__(parent)
        self.source = pixmap
        self.crop_ratio = max(0.1, float(crop_ratio))
        self.zoom = 1.0
        self.offset = QPoint(0, 0)
        self._drag = None
        self.setMinimumSize(460, 400)
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)

    def _crop_rect(self):
        margin = 36
        available_width = max(80, self.width() - margin)
        available_height = max(80, self.height() - margin)
        crop_width = min(available_width, int(available_height * self.crop_ratio))
        crop_height = min(available_height, int(crop_width / self.crop_ratio))
        x = (self.width() - crop_width) // 2
        y = (self.height() - crop_height) // 2
        return x, y, crop_width, crop_height

    def _image_geometry(self):
        x, y, crop_width, crop_height = self._crop_rect()
        base_scale = max(
            crop_width / max(1, self.source.width()),
            crop_height / max(1, self.source.height()),
        )
        scale = base_scale * self.zoom
        image_width = max(1, int(self.source.width() * scale))
        image_height = max(1, int(self.source.height() * scale))
        left = (self.width() - image_width) // 2 + self.offset.x()
        top = (self.height() - image_height) // 2 + self.offset.y()
        return x, y, crop_width, crop_height, scale, image_width, image_height, left, top

    def _clamp_offset(self):
        x, y, crop_width, crop_height, _, image_width, image_height, _, _ = self._image_geometry()
        max_x = max(0, (image_width - crop_width) // 2)
        max_y = max(0, (image_height - crop_height) // 2)
        self.offset.setX(max(-max_x, min(max_x, self.offset.x())))
        self.offset.setY(max(-max_y, min(max_y, self.offset.y())))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#141625"))
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        _, _, _, _, _, image_width, image_height, left, top = self._image_geometry()
        scaled = self.source.scaled(image_width, image_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(QPoint(left, top), scaled)
        x, y, crop_width, crop_height = self._crop_rect()
        painter.setPen(QColor("#FFFFFF"))
        painter.drawRect(x, y, crop_width - 1, crop_height - 1)
        painter.setPen(QColor(255, 255, 255, 80))
        painter.drawLine(x + crop_width // 3, y, x + crop_width // 3, y + crop_height)
        painter.drawLine(x + crop_width * 2 // 3, y, x + crop_width * 2 // 3, y + crop_height)
        painter.drawLine(x, y + crop_height // 3, x + crop_width, y + crop_height // 3)
        painter.drawLine(x, y + crop_height * 2 // 3, x + crop_width, y + crop_height * 2 // 3)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            self.offset += event.pos() - self._drag
            self._drag = event.pos()
            self._clamp_offset()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        factor = 1.1 if event.angleDelta().y() > 0 else 0.9
        self.zoom = max(1.0, min(5.0, self.zoom * factor))
        self._clamp_offset()
        self.update()
        event.accept()

    def cropped(self, size=(512, 512)):
        if isinstance(size, int):
            size = (size, size)
        target_width, target_height = int(size[0]), int(size[1])
        x, y, crop_width, crop_height, scale, _, _, left, top = self._image_geometry()
        source_x = max(0, int((x - left) / max(scale, 0.0001)))
        source_y = max(0, int((y - top) / max(scale, 0.0001)))
        source_width = min(self.source.width() - source_x, int(crop_width / max(scale, 0.0001)))
        source_height = min(self.source.height() - source_y, int(crop_height / max(scale, 0.0001)))
        crop = self.source.copy(source_x, source_y, max(1, source_width), max(1, source_height))
        return crop.scaled(target_width, target_height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


class AvatarCropDialog(QDialog):
    def __init__(self, path, parent=None, crop_ratio=1.0, output_size=(512, 512), title="裁剪头像"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 680 if crop_ratio < 1 else 620)
        pixmap = QPixmap(path)
        layout = QVBoxLayout(self)
        self.canvas = _CropCanvas(pixmap, crop_ratio=crop_ratio)
        layout.addWidget(self.canvas)
        ratio_text = "竖版头像区域" if crop_ratio < 0.9 else "头像区域"
        tip = QLabel(f"拖动图片调整构图，滚轮缩放，白色框为{ratio_text}；原始图片不会被修改。")
        tip.setStyleSheet("color:#888;")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._output_size = output_size

    def cropped_pixmap(self):
        return self.canvas.cropped(self._output_size)


class ChatAvatarSettingsTab(QWidget):
    changed = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent); self._draft=get_chat_avatar_config(); self._build()
    def _build(self):
        layout=QVBoxLayout(self); layout.setSpacing(12)
        intro=QLabel("设置聊天气泡两侧的圆形头像。图片会保存到莲心专用目录，不依赖原文件位置。")
        intro.setWordWrap(True); intro.setStyleSheet("color:#777;"); layout.addWidget(intro)
        self._previews={}
        for role,title in (("assistant","莲心头像"),("user","我的头像")):
            row=QHBoxLayout(); preview=CircularAvatar(role,60,self); self._previews[role]=preview; row.addWidget(preview)
            btn=QPushButton("浏览并裁剪"); btn.clicked.connect(lambda _,r=role:self._choose(r)); row.addWidget(btn)
            reset=QPushButton("恢复默认"); reset.clicked.connect(lambda _,r=role:self._reset(r)); row.addWidget(reset); row.addStretch(); layout.addLayout(row)
        self._enabled=QCheckBox("在聊天气泡中显示头像"); self._enabled.setChecked(self._draft.get("enabled",True)); layout.addWidget(self._enabled)
        self._interaction_enabled=QCheckBox("启用双击头像拍一拍互动"); self._interaction_enabled.setChecked(self._draft.get("interactions_enabled", True)); layout.addWidget(self._interaction_enabled)
        self._dynamic_response=QCheckBox("让莲心思考后动态生成回应"); self._dynamic_response.setChecked(self._draft.get("dynamic_response", True)); layout.addWidget(self._dynamic_response)
        self._counter_tap=QCheckBox("允许莲心反拍我的头像"); self._counter_tap.setChecked(self._draft.get("counter_tap", True)); layout.addWidget(self._counter_tap)
        self._animation_enabled=QCheckBox("启用头像震动动画"); self._animation_enabled.setChecked(self._draft.get("animation_enabled", True)); layout.addWidget(self._animation_enabled)
        self._response_in_chat=QCheckBox("将莲心的拍一拍回应显示为聊天消息"); self._response_in_chat.setChecked(self._draft.get("response_in_chat", True)); layout.addWidget(self._response_in_chat)
        cooldown_row=QHBoxLayout(); cooldown_row.addWidget(QLabel("拍一拍冷却")); self._cooldown=QDoubleSpinBox(); self._cooldown.setRange(0.5,10.0); self._cooldown.setSingleStep(0.5); self._cooldown.setSuffix(" 秒"); self._cooldown.setValue(float(self._draft.get("tap_cooldown_seconds",1.5))); cooldown_row.addWidget(self._cooldown); cooldown_row.addStretch(); layout.addLayout(cooldown_row)
        settings=QHBoxLayout(); settings.addWidget(QLabel("头像大小")); self._size=QSpinBox(); self._size.setRange(40,100); self._size.setValue(int(self._draft.get("size",60))); settings.addWidget(self._size); settings.addWidget(QLabel("像素，头像与气泡间距")); self._gap=QSpinBox(); self._gap.setRange(4,28); self._gap.setValue(int(self._draft.get("gap",10))); settings.addWidget(self._gap); settings.addWidget(QLabel("像素")); settings.addStretch(); layout.addLayout(settings)
        self._border=QCheckBox("显示头像边框"); self._border.setChecked(self._draft.get("border",True)); layout.addWidget(self._border); layout.addStretch()
    def _choose(self, role):
        path,_=QFileDialog.getOpenFileName(self,"选择头像","","图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:return
        dlg=AvatarCropDialog(path,self)
        if dlg.exec_()!=QDialog.Accepted:return
        folder=get_user_data_dir()/"avatars"; folder.mkdir(parents=True,exist_ok=True); out=folder/("lianxin.png" if role=="assistant" else "user.png"); dlg.cropped_pixmap().save(str(out),"PNG")
        self._draft["assistant_path" if role=="assistant" else "user_path"]=str(out); self._previews[role].set_preview_path(str(out))
    def _reset(self, role):
        key="assistant_path" if role=="assistant" else "user_path"; self._draft[key]=""; self._previews[role].set_preview_path("")
    def load(self):
        self._draft=get_chat_avatar_config(); self._enabled.setChecked(self._draft.get("enabled",True)); self._interaction_enabled.setChecked(self._draft.get("interactions_enabled", True)); self._dynamic_response.setChecked(self._draft.get("dynamic_response", True)); self._counter_tap.setChecked(self._draft.get("counter_tap", True)); self._animation_enabled.setChecked(self._draft.get("animation_enabled", True)); self._response_in_chat.setChecked(self._draft.get("response_in_chat", True)); self._cooldown.setValue(float(self._draft.get("tap_cooldown_seconds",1.5))); self._size.setValue(int(self._draft.get("size",60))); self._gap.setValue(int(self._draft.get("gap",10))); self._border.setChecked(self._draft.get("border",True)); self._previews["assistant"].set_preview_path(self._draft.get("assistant_path", "")); self._previews["user"].set_preview_path(self._draft.get("user_path", ""))
    def save(self):
        self._draft.update(enabled=self._enabled.isChecked(), interactions_enabled=self._interaction_enabled.isChecked(), dynamic_response=self._dynamic_response.isChecked(), counter_tap=self._counter_tap.isChecked(), animation_enabled=self._animation_enabled.isChecked(), response_in_chat=self._response_in_chat.isChecked(), tap_cooldown_seconds=self._cooldown.value(), size=self._size.value(),gap=self._gap.value(),border=self._border.isChecked()); save_chat_avatar_config(self._draft); self.changed.emit()
