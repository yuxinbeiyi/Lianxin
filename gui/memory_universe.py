"""Immersive Memory Universe window.

The renderer intentionally stays inside Qt: no web runtime or extra graphics
dependency is required. Derived memory data remains owned by brain modules;
this window is a visualization and correction surface.
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime

from PyQt5.QtCore import QSettings, Qt, QTimer, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient,
)
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QGraphicsItem, QGraphicsLineItem, QGraphicsObject, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
    QDialog, QMainWindow, QPushButton, QSlider, QTextBrowser, QVBoxLayout, QWidget,
)


_BG = QColor("#070B1E")
_PANEL = "rgba(15, 23, 52, 225)"
_TEXT = "#E7ECFF"
_MUTED = "#8D9AC8"
_ACCENTS = {
    "universe": QColor("#83E8FF"),
    "entities": QColor("#6C8CFF"),
    "episodes": QColor("#D994FF"),
    "sagas": QColor("#FFB454"),
}


class _StarNode(QGraphicsObject):
    clicked = pyqtSignal(object)

    def __init__(self, payload: dict, color: QColor, radius: float, event_kind: str = "", parent=None):
        super().__init__(parent)
        self.payload = payload
        self.color = color
        self.radius = radius
        self.phase = random.random() * math.pi * 2
        self.event_kind = event_kind
        self.flash = 1.0 if event_kind else 0.0
        self.setAcceptHoverEvents(True)
        self._hover = False

    def boundingRect(self):
        pad = self.radius * 2.5
        return QRectF(-self.radius - pad, -self.radius - pad,
                      (self.radius + pad) * 2, (self.radius + pad) * 2)

    def paint(self, painter: QPainter, _option, _widget=None):
        pulse = 1.0 + (0.08 if self._hover else 0.04) * math.sin(self.phase)
        radius = self.radius * pulse
        glow = QRadialGradient(0, 0, radius * 3.2)
        glow.setColorAt(0.0, QColor(self.color.red(), self.color.green(), self.color.blue(), 180))
        glow.setColorAt(0.38, QColor(self.color.red(), self.color.green(), self.color.blue(), 65))
        glow.setColorAt(1.0, QColor(self.color.red(), self.color.green(), self.color.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(-radius * 3, -radius * 3, radius * 6, radius * 6))
        painter.setBrush(self.color)
        painter.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))
        painter.setBrush(QColor(255, 255, 255, 180))
        painter.drawEllipse(QRectF(-radius * 0.28, -radius * 0.38, radius * 0.55, radius * 0.55))
        if self.flash > 0:
            event_color = {
                "correction": QColor("#FF6978"),
                "episode_merged": QColor("#FFB454"),
                "saga_merged": QColor("#FFB454"),
                "quality_changed": QColor("#83E8FF"),
            }.get(self.event_kind, QColor("#83E8FF"))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(event_color.red(), event_color.green(), event_color.blue(), int(210 * self.flash)), 2.0))
            ring = radius * (1.4 + self.flash * .8)
            painter.drawEllipse(QRectF(-ring, -ring, ring * 2, ring * 2))

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        self.clicked.emit(self.payload)
        super().mousePressEvent(event)


class _UniverseView(QGraphicsView):
    parallax_changed = pyqtSignal(float, float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._particles = [
            (random.random(), random.random(), random.uniform(0.25, 1.0), random.random() * 6.28)
            for _ in range(180)
        ]
        self._phase = 0.0
        self._parallax_x = 0.0
        self._parallax_y = 0.0
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setCacheMode(QGraphicsView.CacheBackground)
        self.setOptimizationFlag(QGraphicsView.DontSavePainterState, True)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setStyleSheet("background: transparent; border: 0;")

    def advance_animation(self):
        self._phase += 0.035
        self.invalidateScene(self.sceneRect(), QGraphicsScene.BackgroundLayer)
        self.viewport().update()

    def set_parallax(self, x: float, y: float):
        self._parallax_x, self._parallax_y = float(x), float(y)
        self.viewport().update()

    def mouseMoveEvent(self, event):
        rect = self.viewport().rect()
        nx = (event.pos().x() / max(1, rect.width()) - 0.5) * 2.0
        ny = (event.pos().y() / max(1, rect.height()) - 0.5) * 2.0
        self.parallax_changed.emit(max(-1.0, min(1.0, nx)), max(-1.0, min(1.0, ny)))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.parallax_changed.emit(0.0, 0.0)
        super().leaveEvent(event)

    def wheelEvent(self, event):
        factor = 1.12 if event.angleDelta().y() > 0 else 0.89
        self.scale(factor, factor)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, _BG)
        gradient = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.72)
        gradient.setColorAt(0.0, QColor("#151C49"))
        gradient.setColorAt(0.36, QColor("#0C1537"))
        gradient.setColorAt(1.0, _BG)
        painter.fillRect(rect, gradient)
        # Two slow-moving nebula clouds give depth without bitmap assets.
        for ratio, color, drift in ((0.28, QColor(81, 58, 174, 40), 0.0),
                                    (0.72, QColor(22, 160, 188, 30), 1.8)):
            cx = rect.left() + rect.width() * ratio + math.sin(self._phase + drift) * 80 + self._parallax_x * 34
            cy = rect.top() + rect.height() * (0.35 + ratio * 0.35) + self._parallax_y * 24
            cloud = QRadialGradient(cx, cy, rect.width() * 0.35)
            cloud.setColorAt(0.0, color)
            cloud.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
            painter.fillRect(rect, cloud)
        painter.setPen(Qt.NoPen)
        for x_ratio, y_ratio, alpha, phase in self._particles:
            x = rect.left() + rect.width() * x_ratio + self._parallax_x * 10
            y = rect.top() + rect.height() * y_ratio + self._parallax_y * 7
            flicker = max(0, min(255, int(120 * alpha * (0.75 + 0.25 * math.sin(self._phase * 2 + phase)))))
            painter.setBrush(QColor(190, 218, 255, flicker))
            painter.drawEllipse(QRectF(x, y, 1.5 + alpha, 1.5 + alpha))


class MemoryUniverseWindow(QMainWindow):
    """Standalone, resizable and fullscreen-capable memory visualization."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✦ 莲心记忆宇宙")
        self.setMinimumSize(1080, 700)
        self.setWindowFlags(Qt.Window)
        self._settings = QSettings("Lianxin", "MemoryUniverse")
        geometry = self._settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(1440, 900)
        self._selected = None
        self._source_message_ids = []
        self._layer_history = []
        self._last_layer = "universe"
        self._all_data = {"entities": [], "episodes": [], "sagas": []}
        self._event_kinds = {}
        self._last_event_id = int(self._settings.value("last_event_id", 0) or 0)
        self._reduced_motion = self._settings.value("reduced_motion", "false") == "true"
        self._max_visible_nodes = 700
        self._render_generation = 0
        self._parallax_x = 0.0
        self._parallax_y = 0.0
        self._build_ui()
        self._reload_data()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("memoryUniverseRoot")
        root.setStyleSheet(f"""
            QWidget#memoryUniverseRoot {{ background: {_BG.name()}; color: {_TEXT}; }}
            QFrame#universePanel {{ background: {_PANEL}; border: 1px solid rgba(113, 143, 235, 80); border-radius: 14px; }}
            QLabel {{ color: {_TEXT}; }}
            QLabel#muted {{ color: {_MUTED}; }}
            QLineEdit, QComboBox, QTextBrowser {{ background: rgba(11, 17, 42, 235); color: {_TEXT}; border: 1px solid #334579; border-radius: 8px; padding: 7px; }}
            QPushButton {{ background: #1A2854; color: {_TEXT}; border: 1px solid #40589B; border-radius: 8px; padding: 7px 12px; }}
            QPushButton:hover {{ background: #2B4078; }}
            QSlider::groove:horizontal {{ height: 5px; background: #27345E; border-radius: 2px; }}
            QSlider::handle:horizontal {{ width: 15px; margin: -5px 0; background: #83E8FF; border-radius: 8px; }}
        """)
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 12, 16, 16)
        outer.setSpacing(10)

        toolbar = QHBoxLayout()
        title = QLabel("✦ 记忆宇宙")
        title.setFont(QFont("Microsoft YaHei UI", 16, QFont.Bold))
        toolbar.addWidget(title)
        self._breadcrumb = QLabel("宇宙")
        self._breadcrumb.setObjectName("muted")
        toolbar.addWidget(self._breadcrumb)
        self._back_btn = QPushButton("← 返回")
        self._back_btn.setEnabled(False)
        self._back_btn.clicked.connect(self._go_back)
        toolbar.addWidget(self._back_btn)
        toolbar.addStretch()
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索记忆、人物或经历…")
        self._search.setFixedWidth(260)
        self._search.returnPressed.connect(self._apply_filters)
        toolbar.addWidget(self._search)
        self._layer = QComboBox()
        self._layer.addItem("宇宙视图", "universe")
        self._layer.addItem("人物与实体", "entities")
        self._layer.addItem("经历星座", "episodes")
        self._layer.addItem("长期故事", "sagas")
        self._layer.currentIndexChanged.connect(self._on_layer_changed)
        toolbar.addWidget(self._layer)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._reload_data)
        toolbar.addWidget(refresh)
        self._motion_btn = QPushButton("动效：关" if self._reduced_motion else "动效：开")
        self._motion_btn.clicked.connect(self._toggle_motion)
        toolbar.addWidget(self._motion_btn)
        fullscreen = QPushButton("全屏")
        fullscreen.clicked.connect(self._toggle_fullscreen)
        toolbar.addWidget(fullscreen)
        outer.addLayout(toolbar)

        body = QHBoxLayout()
        body.setSpacing(10)
        canvas_frame = QFrame()
        canvas_frame.setObjectName("universePanel")
        canvas_layout = QVBoxLayout(canvas_frame)
        self._scene = QGraphicsScene(self)
        self._view = _UniverseView(self._scene)
        self._view.parallax_changed.connect(self._on_parallax)
        canvas_layout.addWidget(self._view)
        body.addWidget(canvas_frame, 4)

        side = QFrame()
        side.setObjectName("universePanel")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_title = QLabel("记忆观测台")
        side_title.setFont(QFont("Microsoft YaHei UI", 12, QFont.Bold))
        side_layout.addWidget(side_title)
        self._stats = QLabel("")
        self._stats.setObjectName("muted")
        self._stats.setWordWrap(True)
        side_layout.addWidget(self._stats)
        self._detail = QTextBrowser()
        side_layout.addWidget(self._detail, 1)
        self._source_btn = QPushButton("查看来源链")
        self._source_btn.clicked.connect(self._show_sources)
        side_layout.addWidget(self._source_btn)
        self._open_msg_btn = QPushButton("打开原始消息")
        self._open_msg_btn.clicked.connect(self._open_original_messages)
        side_layout.addWidget(self._open_msg_btn)
        self._review_btn = QPushButton("标记为需要复核")
        self._review_btn.clicked.connect(self._mark_review)
        side_layout.addWidget(self._review_btn)
        body.addWidget(side, 1)
        outer.addLayout(body, 1)

        timeline = QHBoxLayout()
        timeline.addWidget(QLabel("记忆时间线"))
        self._timeline = QSlider(Qt.Horizontal)
        self._timeline.setRange(0, 100)
        self._timeline.setValue(100)
        self._timeline.setToolTip("调整可见记忆的新鲜度范围")
        self._timeline.valueChanged.connect(self._apply_filters)
        timeline.addWidget(self._timeline, 1)
        self._timeline_label = QLabel("全部")
        self._timeline_label.setObjectName("muted")
        timeline.addWidget(self._timeline_label)
        outer.addLayout(timeline)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(33)

    def _reload_data(self):
        try:
            from brain.memory_narrative import list_entity_profiles, list_episodes, list_sagas
            from brain.memory_narrative import list_narrative_events
            events = list_narrative_events(300, since_id=self._last_event_id)
            for event in events:
                key = (event.get("entity_type", ""), int(event.get("entity_id") or 0))
                self._event_kinds[key] = event.get("event_type", "")
                self._last_event_id = max(self._last_event_id, int(event.get("id", 0) or 0))
            self._settings.setValue("last_event_id", self._last_event_id)
            self._all_data = {
                "entities": list_entity_profiles(300),
                "episodes": list_episodes(300),
                "sagas": list_sagas(100),
            }
        except Exception as exc:
            self._detail.setPlainText(f"记忆宇宙加载失败：{exc}")
            self._all_data = {"entities": [], "episodes": [], "sagas": []}
        self._apply_filters()

    def _apply_filters(self):
        layer = self._layer.currentData()
        keyword = self._search.text().strip().lower()
        data = {key: [dict(item) for item in value] for key, value in self._all_data.items()}
        if keyword:
            for key, items in data.items():
                data[key] = [item for item in items if keyword in json.dumps(item, ensure_ascii=False).lower()]
        cutoff = self._timeline.value()
        if cutoff < 100:
            # Keep the newest fraction; the exact timestamp remains visible in details.
            for key, items in data.items():
                keep = max(1, int(len(items) * cutoff / 100)) if items else 0
                data[key] = items[:keep]
            self._timeline_label.setText(f"最新 {cutoff}%")
        else:
            self._timeline_label.setText("全部")
        self._breadcrumb.setText({"universe": " / 宇宙", "entities": " / 人物与实体", "episodes": " / 经历星座", "sagas": " / 长期故事"}.get(layer, ""))
        self._render(layer, data)

    def _on_layer_changed(self, _index):
        layer = self._layer.currentData()
        if layer != self._last_layer:
            self._layer_history.append(self._last_layer)
            self._last_layer = layer
        self._back_btn.setEnabled(bool(self._layer_history))
        self._apply_filters()

    def _on_parallax(self, x: float, y: float):
        """Move foreground layers by depth to create a restrained 2.5D effect."""
        self._parallax_x, self._parallax_y = float(x), float(y)
        self._view.set_parallax(x, y)
        for item in self._scene.items():
            base = item.data(1)
            depth = item.data(2)
            if base is None or depth is None:
                continue
            item.setPos(base + QPointF(x * 34.0 * float(depth), y * 24.0 * float(depth)))

    def _go_back(self):
        if not self._layer_history:
            return
        previous = self._layer_history.pop()
        self._last_layer = previous
        self._back_btn.setEnabled(bool(self._layer_history))
        index = self._layer.findData(previous)
        if index >= 0:
            self._layer.blockSignals(True)
            self._layer.setCurrentIndex(index)
            self._layer.blockSignals(False)
            self._apply_filters()

    def _render(self, layer, data):
        self._render_generation += 1
        self._scene.clear()
        self._hidden_count = 0
        if layer == "universe":
            self._render_universe(data)
        elif layer == "entities":
            self._render_ring(data["entities"], "entities", "name", "summary")
        elif layer == "episodes":
            self._render_ring(data["episodes"], "episodes", "title", "summary")
        else:
            self._render_ring(data["sagas"], "sagas", "title", "summary")
        visible_items = data["entities"] if layer == "universe" else data.get(layer, [])
        self._stats.setText(
            f"实体 {len(data['entities'])} · 经历星座 {len(data['episodes'])} · 长期故事 {len(data['sagas'])}\n"
            "亮度：质量/置信度 · 线条：共享实体或叙事关系\n"
            f"当前显示 {max(0, len(visible_items) - self._hidden_count)}/{len(visible_items)} 星体"
        )

    def _render_universe(self, data):
        groups = {}
        for item in data["entities"]:
            groups.setdefault(item.get("entity_type", "concept"), []).append(item)
        payloads = [{"id": key, "name": key, "summary": f"{len(items)} 个实体", "items": items}
                    for key, items in groups.items()]
        self._render_ring(payloads, "universe", "name", "summary")
        self._render_binary_core()

    def _render_binary_core(self):
        """Render the user/companion pair at the heart of the memory universe."""
        left = {"id": "user-core", "name": "雨心博士", "entity_type": "person",
                "summary": "记忆宇宙的主人"}
        right = {"id": "ai-core", "name": "莲心", "entity_type": "companion",
                 "summary": "陪伴者与记忆整理者"}
        line = QGraphicsLineItem(-42, 0, 42, 0)
        line.setPen(QPen(QColor(185, 210, 230, 110), 1.2))
        line.setData(1, QPointF(0, 0))
        line.setData(2, 1.0)
        self._scene.addItem(line)
        for payload, x, color in ((left, -42, QColor("#FFD58A")), (right, 42, QColor("#83E8FF"))):
            node = _StarNode(payload, color, 19)
            node.setData(1, QPointF(x, 0))
            node.setData(2, 1.0)
            node.setPos(x, 0)
            node.clicked.connect(self._select_item)
            self._scene.addItem(node)
            label = QGraphicsSimpleTextItem(payload["name"])
            label.setBrush(color)
            label.setData(1, QPointF(x - 22, 34))
            label.setData(2, 1.0)
            label.setPos(x - 22, 34)
            self._scene.addItem(label)

    def _render_ring(self, items, layer, title_key, summary_key):
        if not items:
            empty = self._scene.addText("这里还没有星光\n完成更多对话后，记忆宇宙会逐渐生长。")
            empty.setDefaultTextColor(QColor("#8D9AC8"))
            empty.setPos(-130, -20)
            return
        original_count = len(items)
        if original_count > self._max_visible_nodes:
            items = sorted(
                items,
                key=lambda value: (
                    float(value.get("confidence", 0) or 0),
                    int(value.get("mention_count", 0) or 0),
                ),
                reverse=True,
            )[: self._max_visible_nodes]
            self._hidden_count = original_count - len(items)
        radius = max(190.0, 58.0 * math.sqrt(len(items)))
        color = _ACCENTS.get(layer, _ACCENTS["entities"])
        event_type = {"entities": "entity", "episodes": "episode", "sagas": "saga"}.get(layer, "")
        for index, item in enumerate(items):
            angle = index * math.pi * 2 / max(1, len(items))
            x, y = radius * math.cos(angle), radius * math.sin(angle)
            confidence = float(item.get("confidence", 0.8) or 0.8)
            try:
                item_id = int(item.get("id", 0) or 0)
            except (TypeError, ValueError):
                item_id = 0
            event_kind = self._event_kinds.get((event_type, item_id), "")
            node = _StarNode(item, color, 14 + confidence * 12, event_kind)
            depth = {"universe": 0.58, "entities": 0.86, "episodes": 1.0, "sagas": 1.08}.get(layer, 0.9)
            node.setData(1, QPointF(x, y))
            node.setData(2, depth)
            node.setPos(x, y)
            node.clicked.connect(self._select_item)
            self._scene.addItem(node)
            label = QGraphicsSimpleTextItem(str(item.get(title_key, "未命名"))[:28])
            label.setBrush(QColor("#E7ECFF"))
            label.setData(1, QPointF(x + 18, y - 8))
            label.setData(2, depth)
            label.setPos(x + 18, y - 8)
            self._scene.addItem(label)
        self._scene.setSceneRect(-radius - 220, -radius - 130, radius * 2 + 440, radius * 2 + 260)
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def _select_item(self, item):
        self._selected = item
        title = item.get("name") or item.get("title") or "未命名记忆"
        content = item.get("summary") or item.get("current_status") or ""
        self._detail.setHtml(
            f"<h3>{title}</h3><p>{content}</p>"
            f"<p>类型：{item.get('entity_type') or item.get('category') or '记忆'}<br>"
            f"置信度：{float(item.get('confidence', 0) or 0):.0%}<br>"
            f"更新时间：{item.get('updated_at') or item.get('last_seen_at') or '未知'}</p>"
        )

    def _show_sources(self):
        if not self._selected:
            self._detail.setPlainText("请先点击一颗记忆星体。")
            return
        item = self._selected
        fact_ids = []
        fragment_ids = []
        self._source_message_ids = []
        record_type = "entity" if item.get("name") else ("saga" if item.get("episode_ids") else "episode")
        try:
            from brain.memory_narrative import trace_narrative_sources

            traced = trace_narrative_sources(record_type, int(item["id"]))
            fact_ids.extend(traced.get("facts", []))
            fragment_ids.extend(traced.get("fragments", []))
            self._source_message_ids.extend(traced.get("message_ids", []))
        except Exception:
            pass
        for key, target in (("source_fact_ids", fact_ids), ("fragment_ids", fragment_ids)):
            try:
                target.extend(json.loads(item.get(key, "[]") or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        fact_ids = list(dict.fromkeys(int(value) for value in fact_ids if str(value).isdigit()))
        fragment_ids = list(dict.fromkeys(int(value) for value in fragment_ids if str(value).isdigit()))
        # Saga nodes point to Episodes first; expand that chain before reading facts.
        if item.get("episode_ids") and not fact_ids:
            try:
                from brain.memory_narrative import list_episodes
                episode_ids = [int(value) for value in json.loads(item.get("episode_ids", "[]") or "[]")]
                for episode in list_episodes(300):
                    if int(episode.get("id", 0)) not in episode_ids:
                        continue
                    fact_ids.extend(json.loads(episode.get("source_fact_ids", "[]") or "[]"))
                    fragment_ids.extend(json.loads(episode.get("fragment_ids", "[]") or "[]"))
                fact_ids = list(dict.fromkeys(fact_ids))
                fragment_ids = list(dict.fromkeys(fragment_ids))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        lines = ["来源链", f"事实：{fact_ids or '无'}", f"碎片：{fragment_ids or '无'}"]
        try:
            from brain.graph_memory import get_fact_by_id, get_fact_fragments
            for fact_id in fact_ids[:10]:
                fact = get_fact_by_id(int(fact_id))
                if fact:
                    lines.append(f"\n事实#{fact_id}：{fact.get('content', '')}")
                    for fragment in get_fact_fragments(int(fact_id), include_inactive=True)[:5]:
                        message_ids = fragment.get("source_message_ids", []) or []
                        self._source_message_ids.extend(
                            int(value) for value in message_ids if str(value).isdigit()
                        )
                        lines.append(f"  来源消息：{message_ids}")
            self._source_message_ids = sorted(set(self._source_message_ids))
            if self._source_message_ids:
                lines.append(f"\n可打开原始消息：{len(self._source_message_ids)} 条")
        except Exception as exc:
            lines.append(f"来源读取失败：{exc}")
        self._detail.setPlainText("\n".join(lines))

    def _open_original_messages(self):
        """Show the immutable chat rows referenced by the selected memory."""
        if not self._selected:
            self._detail.setPlainText("请先点击一颗记忆星体并查看来源链。")
            return
        if not self._source_message_ids:
            self._show_sources()
        if not self._source_message_ids:
            self._detail.append("\n未找到可定位的原始消息引用。")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("原始消息来源")
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser(dialog)
        try:
            from brain.graph_memory import _get_conn
            conn = _get_conn()
            placeholders = ",".join("?" for _ in self._source_message_ids)
            rows = conn.execute(
                f"SELECT id,session_id,role,content,timestamp FROM messages WHERE id IN ({placeholders}) ORDER BY timestamp,id",
                tuple(self._source_message_ids),
            ).fetchall()
            text = []
            for row in rows:
                text.append(
                    f"[{row['timestamp'] or ''}] #{row['id']}  {row['role'] or ''}  "
                    f"session={row['session_id'] or ''}\n{row['content'] or ''}"
                )
            browser.setPlainText("\n\n".join(text) or "原始消息已不存在（可能已被清理）。")
        except Exception as exc:
            browser.setPlainText(f"读取原始消息失败：{exc}")
        layout.addWidget(browser)
        close_btn = QPushButton("关闭", dialog)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec_()

    def _mark_review(self):
        if not self._selected:
            return
        item = self._selected
        try:
            from brain.memory_narrative import transition_narrative_lifecycle

            record_type = "entity" if item.get("name") else ("saga" if item.get("episode_ids") else "episode")
            transition_narrative_lifecycle(record_type, int(item["id"]), "needs_review",
                                           reason="用户在记忆宇宙中标记复核")
            self._detail.append("\n已标记为需要复核。")
        except Exception as exc:
            self._detail.append(f"\n标记失败：{exc}")

    def _animate(self):
        if self._reduced_motion or not self.isVisible():
            return
        self._view.advance_animation()
        for item in self._scene.items():
            if isinstance(item, _StarNode):
                item.phase += 0.035
                if item.flash > 0:
                    item.flash = max(0.0, item.flash - 0.018)
                item.update()

    def _toggle_motion(self):
        self._reduced_motion = not self._reduced_motion
        self._settings.setValue("reduced_motion", "true" if self._reduced_motion else "false")
        self._motion_btn.setText("动效：关" if self._reduced_motion else "动效：开")
        self._view.viewport().update()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event):
        # Invalidate queued progressive-render callbacks before Qt destroys
        # the scene; otherwise a fast test/close can leave a stale batch task.
        self._render_generation += 1
        self._scene.clear()
        self._settings.setValue("geometry", self.saveGeometry())
        self._timer.stop()
        super().closeEvent(event)
