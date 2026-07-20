"""Small interactive constellation view for derived memory layers."""
from __future__ import annotations

import json
import math

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QBrush, QPen
from PyQt5.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QLabel, QPushButton,
    QComboBox, QHBoxLayout, QVBoxLayout, QWidget,
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
        top = QHBoxLayout()
        self._hint = QLabel("叙事记忆会在后台整理后出现在这里。点击实体节点查看档案。")
        self._hint.setWordWrap(True)
        top.addWidget(self._hint)
        self._layer_combo = QComboBox()
        self._layer_combo.addItem("实体层", "entities")
        self._layer_combo.addItem("Episode 层", "episodes")
        self._layer_combo.addItem("Saga 层", "sagas")
        self._layer_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        top.addWidget(self._layer_combo)
        refresh = QPushButton("刷新星图")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
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
        layer = self._layer_combo.currentData()
        if not entities and layer == "entities":
            self._hint.setText("暂无实体档案。完成几轮对话并等待后台叙事整合后，星图会逐步生长。")
            return
        self._hint.setText(f"{len(entities)} 个实体 · {len(episodes)} 个 Episode · {len(sagas)} 条 Saga")
        if layer == "episodes":
            self._render_episodes(episodes)
            return
        if layer == "sagas":
            self._render_sagas(sagas)
            return
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

    def _render_episodes(self, episodes: list[dict]):
        if not episodes:
            self._hint.setText(self._hint.text() + " · 暂无 Episode")
            return
        radius = max(180.0, 45.0 * math.sqrt(len(episodes)))
        positions = {}
        for index, episode in enumerate(episodes):
            angle = 2 * math.pi * index / max(1, len(episodes))
            x, y = radius * math.cos(angle), radius * math.sin(angle)
            positions[int(episode["id"])] = (x, y)
            size = 26 + min(30, int(float(episode.get("confidence", 0.5) or 0.5) * 30))
            item = _EntityNode(QRectF(x - size / 2, y - size / 2, size, size), episode, self._show_episode)
            item.setBrush(QBrush(QColor("#D994FF")))
            item.setPen(QPen(QColor("#F0C8FF"), 1.5))
            item.setToolTip(episode.get("summary", ""))
            self._scene.addItem(item)
            label = QGraphicsSimpleTextItem(episode.get("title", "")[:30])
            label.setBrush(QBrush(QColor("#F2DEFF")))
            label.setPos(x + size / 2 + 4, y - 8)
            self._scene.addItem(label)
        for left_index, left in enumerate(episodes):
            left_entities = set(json.loads(left.get("entity_ids", "[]") or "[]"))
            for right in episodes[left_index + 1:]:
                right_entities = set(json.loads(right.get("entity_ids", "[]") or "[]"))
                if not left_entities & right_entities:
                    continue
                x1, y1 = positions[int(left["id"])]
                x2, y2 = positions[int(right["id"])]
                line = QGraphicsLineItem(x1, y1, x2, y2)
                line.setPen(QPen(QColor("#604B76"), 1))
                self._scene.addItem(line)
        self._scene.setSceneRect(-radius - 160, -radius - 100, radius * 2 + 320, radius * 2 + 200)
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def _render_sagas(self, sagas: list[dict]):
        if not sagas:
            self._hint.setText(self._hint.text() + " · 暂无 Saga")
            return
        radius = max(180.0, 65.0 * math.sqrt(len(sagas)))
        for index, saga in enumerate(sagas):
            angle = 2 * math.pi * index / max(1, len(sagas))
            x, y = radius * math.cos(angle), radius * math.sin(angle)
            size = 38 + min(36, int(float(saga.get("confidence", 0.5) or 0.5) * 36))
            item = _EntityNode(QRectF(x - size / 2, y - size / 2, size, size), saga, self._show_saga)
            item.setBrush(QBrush(QColor("#FFB454")))
            item.setPen(QPen(QColor("#FFE0A5"), 2))
            item.setToolTip(saga.get("summary", ""))
            self._scene.addItem(item)
            label = QGraphicsSimpleTextItem(saga.get("title", "")[:30])
            label.setBrush(QBrush(QColor("#FFF0CE")))
            label.setPos(x + size / 2 + 4, y - 8)
            self._scene.addItem(label)
        self._scene.setSceneRect(-radius - 180, -radius - 110, radius * 2 + 360, radius * 2 + 220)
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def _show_episode(self, episode: dict):
        self._detail.setText(
            f"Episode #{episode.get('id')} · {episode.get('title', '')}\n"
            f"{episode.get('summary', '')}\n来源事实：{episode.get('source_fact_ids', '[]')} · 来源碎片：{episode.get('fragment_ids', '[]')}"
        )

    def _show_saga(self, saga: dict):
        self._detail.setText(
            f"Saga #{saga.get('id')} · {saga.get('title', '')}\n"
            f"{saga.get('summary', '')}\n关联 Episode：{saga.get('episode_ids', '[]')}"
        )
