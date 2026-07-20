"""Small interactive constellation view for derived memory layers."""
from __future__ import annotations

import json
import math

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QBrush, QPen
from PyQt5.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)


class _EntityNode(QGraphicsEllipseItem):
    def __init__(self, rect, entity, callback):
        super().__init__(rect)
        self.entity = entity
        self.callback = callback

    def mousePressEvent(self, event):
        self.callback(self.entity)
        super().mousePressEvent(event)


class MemoryConstellationPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        top = QVBoxLayout()
        self._hint = QLabel("叙事记忆会在后台整理后出现在这里。点击实体节点查看档案。")
        self._hint.setWordWrap(True)
        top.addWidget(self._hint)
        refresh = QPushButton("刷新星图")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh, alignment=Qt.AlignRight)
        layout.addLayout(top)
        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHints(self._view.renderHints())
        self._view.setDragMode(QGraphicsView.ScrollHandDrag)
        self._view.setStyleSheet("QGraphicsView { background: #111426; border: 0; border-radius: 8px; }")
        layout.addWidget(self._view, 1)
        self._detail = QLabel("")
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: #7DE2D1; padding: 4px;")
        layout.addWidget(self._detail)
        self.refresh()

    def refresh(self):
        self._scene.clear()
        try:
            from brain.memory_narrative import list_entity_profiles, list_episodes, list_sagas
            entities = list_entity_profiles(80)
            episodes = list_episodes(120)
            sagas = list_sagas(30)
        except Exception as exc:
            self._hint.setText(f"星图加载失败：{exc}")
            return
        if not entities:
            self._hint.setText("暂无实体档案。完成几轮对话并等待后台叙事整合后，星图会逐步生长。")
            return
        self._hint.setText(f"{len(entities)} 个实体 · {len(episodes)} 个 Episode · {len(sagas)} 条 Saga")
        center_x, center_y = 0.0, 0.0
        radius = max(180.0, 35.0 * math.sqrt(len(entities)))
        positions = {}
        entity_items = {}
        for index, entity in enumerate(entities):
            angle = 2 * math.pi * index / max(1, len(entities))
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            positions[int(entity["id"])] = (x, y)
            size = 18 + min(30, int(entity.get("mention_count", 1) or 1) * 2)
            item = _EntityNode(QRectF(x - size / 2, y - size / 2, size, size), entity, self._show_entity)
            item.setBrush(QBrush(QColor("#6C7BFF")))
            item.setPen(QPen(QColor("#9DA8FF"), 1.5))
            item.setToolTip(f"{entity.get('name', '')}\n{entity.get('summary', '')}")
            item.setData(0, entity)
            entity_items[int(entity["id"])] = item
            self._scene.addItem(item)
            label = QGraphicsSimpleTextItem(entity.get("name", ""))
            label.setBrush(QBrush(QColor("#E7E9FF")))
            label.setPos(x + size / 2 + 4, y - 8)
            self._scene.addItem(label)
        for episode in episodes:
            ids = []
            try:
                ids = [int(value) for value in json.loads(episode.get("entity_ids", "[]") or "[]")]
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            ids = [value for value in ids if value in positions]
            for left, right in zip(ids, ids[1:]):
                x1, y1 = positions[left]
                x2, y2 = positions[right]
                line = QGraphicsLineItem(x1, y1, x2, y2)
                line.setPen(QPen(QColor("#394266"), 1))
                line.setToolTip(episode.get("summary", ""))
                self._scene.addItem(line)
        self._scene.setSceneRect(-radius - 140, -radius - 100, radius * 2 + 280, radius * 2 + 200)
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def _show_entity(self, entity: dict):
        self._detail.setText(
            f"{entity.get('name', '')} · {entity.get('entity_type', 'concept')} · "
            f"提及 {entity.get('mention_count', 0)} 次\n"
            f"{entity.get('summary', '')}\n当前状态：{entity.get('current_status', '')}"
        )
