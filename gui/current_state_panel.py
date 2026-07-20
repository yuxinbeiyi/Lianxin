"""Owner-facing editor for time-bounded current states."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QDateTime, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from brain.current_state import (
    STATE_TYPES,
    get_state_events,
    list_current_states,
    resolve_current_state,
    set_current_state,
    update_current_state,
)


STATE_LABELS = {
    "health": "健康",
    "emotion": "情绪",
    "location": "位置",
    "project": "项目",
    "relationship": "关系",
    "plan": "计划",
    "other": "其他",
}
STATUS_LABELS = {"active": "有效", "resolved": "已结束", "expired": "已过期"}

CURRENT_STATE_STYLE = """
    QWidget#currentStatePanel, QWidget#currentStateList {
        background: #191B2D;
    }
    QScrollArea#current_state_scroll {
        background: #191B2D;
        border: 0;
    }
    QScrollArea#current_state_scroll > QWidget > QWidget {
        background: #191B2D;
    }
    QComboBox {
        min-height: 28px;
        background: #272A42;
        color: #E5E7F4;
        border: 1px solid #414764;
        border-radius: 5px;
        padding: 0 8px;
    }
    QComboBox QAbstractItemView {
        background: #272A42;
        color: #E5E7F4;
        selection-background-color: #3B4163;
    }
    QPushButton {
        min-height: 28px;
        background: #30344F;
        color: #E7E9F7;
        border: 1px solid #464C70;
        border-radius: 5px;
        padding: 0 10px;
    }
    QPushButton:hover {
        background: #3B4163;
        border-color: #6974AC;
    }
    QPushButton#add_state_button {
        background: #276B5D;
        border-color: #3C8E7B;
        color: #FFFFFF;
        font-weight: bold;
    }
    QPushButton#add_state_button:hover { background: #31806F; }
    QScrollBar:vertical { background: #191B2D; width: 7px; margin: 0; }
    QScrollBar::handle:vertical {
        background: #484D6D;
        min-height: 28px;
        border-radius: 3px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def _local_qdatetime(days: int = 7) -> QDateTime:
    return QDateTime.currentDateTime().addDays(days)


class CurrentStateEditor(QDialog):
    """Small editor used for both new states and lifecycle updates."""

    def __init__(self, state: dict | None = None, parent=None):
        super().__init__(parent)
        self._state = state
        self.setWindowTitle("编辑当前状态" if state else "新增当前状态")
        self.setMinimumWidth(480)
        self.setModal(True)
        self.setStyleSheet(
            "QDialog { background: #191B2D; color: #E5E7F4; }"
            "QLabel { color: #D9DCEC; }"
            "QTextEdit, QDateTimeEdit, QDoubleSpinBox, QComboBox {"
            " background: #272A42; color: #F2F3FA; border: 1px solid #414764;"
            " border-radius: 5px; padding: 6px; }"
            + CURRENT_STATE_STYLE
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        title = QLabel(self.windowTitle())
        title.setFont(QFont("Microsoft YaHei UI", 13, QFont.Bold))
        title.setStyleSheet("color: #E5E7FF;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)

        self.content_edit = QTextEdit()
        self.content_edit.setObjectName("state_content_edit")
        self.content_edit.setPlaceholderText("例如：用户这周正在准备产品发布")
        self.content_edit.setMinimumHeight(78)
        self.content_edit.setMaximumHeight(130)
        form.addRow("内容", self.content_edit)

        self.type_combo = QComboBox()
        self.type_combo.setObjectName("state_type_combo")
        for state_type in STATE_TYPES:
            self.type_combo.addItem(STATE_LABELS[state_type], state_type)
        form.addRow("类型", self.type_combo)

        self.expiry_edit = QDateTimeEdit(_local_qdatetime())
        self.expiry_edit.setObjectName("state_expiry_edit")
        self.expiry_edit.setCalendarPopup(True)
        self.expiry_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.expiry_edit.setMinimumDateTime(QDateTime.currentDateTime().addSecs(60))
        self.expiry_edit.setMaximumDateTime(QDateTime.currentDateTime().addDays(90))
        form.addRow("有效至", self.expiry_edit)

        self.confidence_spin = QDoubleSpinBox()
        self.confidence_spin.setObjectName("state_confidence_spin")
        self.confidence_spin.setRange(0.0, 1.0)
        self.confidence_spin.setSingleStep(0.05)
        self.confidence_spin.setDecimals(2)
        self.confidence_spin.setValue(0.95)
        self.confidence_spin.setSuffix(" 置信度")
        form.addRow("可信度", self.confidence_spin)
        layout.addLayout(form)

        hint = QLabel("手动编辑会立即应用；结束状态后仍可在历史记录中查看。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9DA3C7; font-size: 12px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._apply_state()

    def _apply_state(self):
        if not self._state:
            return
        self.content_edit.setPlainText(self._state.get("content", ""))
        index = self.type_combo.findData(self._state.get("state_type", "other"))
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        parsed = QDateTime.fromString(self._state.get("expires_at", ""), Qt.ISODate)
        if parsed.isValid():
            self.expiry_edit.setDateTime(parsed.toLocalTime())
        self.confidence_spin.setValue(float(self._state.get("confidence", 0.8)))

    def _validate_and_accept(self):
        if not self.content_edit.toPlainText().strip():
            QMessageBox.warning(self, "无法保存", "状态内容不能为空。")
            return
        if self.expiry_edit.dateTime() <= QDateTime.currentDateTime():
            QMessageBox.warning(self, "无法保存", "有效时间必须晚于当前时间。")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "content": self.content_edit.toPlainText().strip(),
            "state_type": self.type_combo.currentData(),
            "expires_at": self.expiry_edit.dateTime().toString(Qt.ISODate),
            "confidence": self.confidence_spin.value(),
        }


class CurrentStateHistoryDialog(QDialog):
    def __init__(self, state: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"状态 #{state['id']} 的变更历史")
        self.resize(640, 420)
        self.setStyleSheet(
            "QDialog { background: #191B2D; color: #E5E7F4; }"
            "QScrollArea { border: 0; background: #191B2D; }"
            + CURRENT_STATE_STYLE
        )
        layout = QVBoxLayout(self)
        title = QLabel(f"{STATE_LABELS.get(state['state_type'], '其他')} · {state['content']}")
        title.setWordWrap(True)
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        layout.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        events = get_state_events(state["id"])
        if not events:
            body_layout.addWidget(QLabel("暂无变更记录"))
        for event in events:
            action = {
                "set": "创建",
                "update": "更新",
                "confirm": "再次确认",
                "resolve": "结束",
                "expire": "自动过期",
            }.get(event.get("action"), event.get("action", "变更"))
            source_ids = event.get("source_message_ids") or []
            source = event.get("source_channel") or "桌面端手动操作"
            if source_ids:
                source += " · 消息 " + ", ".join(f"#{item}" for item in source_ids)
            text = QLabel(
                f"{event.get('created_at', '')}  {action}\n"
                f"{event.get('content', '')}\n"
                f"来源：{source}"
                + (f"\n原因：{event.get('reason')}" if event.get("reason") else "")
            )
            text.setWordWrap(True)
            text.setStyleSheet(
                "background: #242742; border: 1px solid #3E456C; "
                "border-radius: 6px; padding: 9px; color: #E3E5F5;"
            )
            body_layout.addWidget(text)
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignRight)


class CurrentStatePanel(QWidget):
    """A refreshable management view embedded in MemorySettingsDialog."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("currentStatePanel")
        self.setStyleSheet(CURRENT_STATE_STYLE)
        self._states: list[dict] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("当前状态")
        title.setFont(QFont("Microsoft YaHei UI", 13, QFont.Bold))
        title.setStyleSheet("color: #1ABC9C;")
        title_box.addWidget(title)
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #8F96B2; font-size: 12px;")
        title_box.addWidget(self.summary_label)
        header.addLayout(title_box)
        header.addStretch()
        self.filter_combo = QComboBox()
        self.filter_combo.setObjectName("state_status_filter")
        for key, label in (("active", "有效"), ("all", "全部"), ("resolved", "已结束"), ("expired", "已过期")):
            self.filter_combo.addItem(label, key)
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        header.addWidget(self.filter_combo)
        self.type_combo = QComboBox()
        self.type_combo.setObjectName("state_type_filter")
        self.type_combo.addItem("全部类型", "")
        for state_type in STATE_TYPES:
            self.type_combo.addItem(STATE_LABELS[state_type], state_type)
        self.type_combo.currentIndexChanged.connect(self.refresh)
        header.addWidget(self.type_combo)
        refresh_btn = QPushButton("↻")
        refresh_btn.setToolTip("刷新当前状态")
        refresh_btn.setFixedSize(30, 30)
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        add_btn = QPushButton("＋ 新增")
        add_btn.setObjectName("add_state_button")
        add_btn.clicked.connect(self._add_state)
        header.addWidget(add_btn)
        layout.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("current_state_scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_widget.setObjectName("currentStateList")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(2, 2, 2, 2)
        self._list_layout.setSpacing(8)
        self._scroll.setWidget(self._list_widget)
        layout.addWidget(self._scroll, 1)

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)

    def refresh(self):
        self._states = list_current_states(include_inactive=True)
        selected_status = self.filter_combo.currentData() if hasattr(self, "filter_combo") else "active"
        selected_type = self.type_combo.currentData() if hasattr(self, "type_combo") else ""
        for index in reversed(range(self._list_layout.count())):
            item = self._list_layout.takeAt(index)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        visible = []
        for state in self._states:
            if selected_status != "all" and state.get("status") != selected_status:
                continue
            if selected_type and state.get("state_type") != selected_type:
                continue
            visible.append(state)
            self._list_layout.addWidget(self._make_row(state))
        if not visible:
            empty = QLabel("当前筛选下没有状态")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #8F96B2; padding: 48px 10px;")
            self._list_layout.addWidget(empty)
        self._list_layout.addStretch()
        active = sum(state.get("status") == "active" for state in self._states)
        self.summary_label.setText(f"有效 {active} 条 · 共记录 {len(self._states)} 条")

    def _make_row(self, state: dict) -> QFrame:
        row = QFrame()
        row.setObjectName("current_state_row")
        row.setStyleSheet(
            "QFrame#current_state_row { background: #242742; border: 1px solid #3E456C; border-radius: 7px; }"
        )
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(12, 9, 10, 9)
        top = QHBoxLayout()
        badge = QLabel(STATE_LABELS.get(state.get("state_type"), "其他"))
        badge.setStyleSheet("color: #7DE1C0; font-weight: bold;")
        top.addWidget(badge)
        status = state.get("status", "active")
        status_label = QLabel(STATUS_LABELS.get(status, status))
        status_label.setStyleSheet(
            "color: #86A5FF;" if status == "active" else "color: #9296AE;"
        )
        top.addWidget(status_label)
        top.addStretch()
        expiry = str(state.get("expires_at", "")).replace("T", " ")[:16]
        top.addWidget(QLabel(f"有效至 {expiry}"))
        row_layout.addLayout(top)

        content = QLabel(state.get("content", ""))
        content.setWordWrap(True)
        content.setStyleSheet("color: #F2F3FA; font-size: 14px; font-weight: bold;")
        row_layout.addWidget(content)
        source_ids = state.get("source_message_ids") or []
        source = state.get("source_channel") or "桌面端手动编辑"
        if source_ids:
            source += " · " + ", ".join(f"消息#{item}" for item in source_ids)
        meta = QLabel(f"置信度 {float(state.get('confidence', 0)):.0%} · 来源：{source}")
        meta.setStyleSheet("color: #A7ACCA; font-size: 11px;")
        row_layout.addWidget(meta)

        actions = QHBoxLayout()
        actions.addStretch()
        history_btn = QPushButton("▤ 历史")
        history_btn.setToolTip("查看状态变更历史")
        history_btn.clicked.connect(lambda _checked=False, s=state: self._show_history(s))
        actions.addWidget(history_btn)
        if status == "active":
            edit_btn = QPushButton("✎ 编辑")
            edit_btn.clicked.connect(lambda _checked=False, s=state: self._edit_state(s))
            actions.addWidget(edit_btn)
            resolve_btn = QPushButton("✓ 结束")
            resolve_btn.clicked.connect(lambda _checked=False, s=state: self._resolve_state(s))
            actions.addWidget(resolve_btn)
        row_layout.addLayout(actions)
        return row

    def _add_state(self):
        dialog = CurrentStateEditor(parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        values = dialog.values()
        try:
            set_current_state(
                values["content"], values["state_type"],
                expires_at=values["expires_at"],
                confidence=values["confidence"],
                source_quality="user_confirmed", source_channel="desktop_manual",
            )
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        self.refresh()
        self.changed.emit()

    def _edit_state(self, state: dict):
        dialog = CurrentStateEditor(state, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        values = dialog.values()
        try:
            update_current_state(
                state["id"], content=values["content"],
                state_type=values["state_type"], expires_at=values["expires_at"],
                confidence=values["confidence"], source_quality="user_confirmed",
                source_channel="desktop_manual",
            )
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "无法更新", str(exc))
            return
        self.refresh()
        self.changed.emit()

    def _resolve_state(self, state: dict):
        reply = QMessageBox.question(
            self, "结束当前状态", f"确定结束这条状态吗？\n\n{state['content']}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        reason, ok = self._reason_dialog()
        if not ok:
            return
        try:
            resolve_current_state(
                state["id"], reason, source_channel="desktop_manual"
            )
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "无法结束", str(exc))
            return
        self.refresh()
        self.changed.emit()

    def _reason_dialog(self):
        from PyQt5.QtWidgets import QInputDialog
        return QInputDialog.getText(self, "结束原因", "请输入结束原因：", text="状态已不再适用")

    def _show_history(self, state: dict):
        CurrentStateHistoryDialog(state, self).exec_()
