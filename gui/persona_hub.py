"""人格枢控：人格档案编辑、预览、保存与热激活。"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path

from PyQt5.QtCore import QSettings, Qt, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtWidgets import (
    QAction, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSplitter, QTabWidget, QTextEdit, QVBoxLayout,
    QComboBox, QCheckBox,
    QWidget,
)

from brain.persona import (
    DEFAULT_PERSONA_ID,
    PersonaManager,
    PersonaProfile,
    PersonaPromptComposer,
    PersonaSnapshot,
    PersonaStoreError,
    PersonaValidationError,
    get_persona_manager,
)
from brain.persona.models import utc_now_iso
from config import get_core_system_policy, get_user_name


class PersonaHub(QMainWindow):
    persona_activated = pyqtSignal(str, bool)  # profile_name, start_new_conversation
    growth_event_applied = pyqtSignal(object)

    def __init__(self, parent=None, manager: PersonaManager | None = None):
        super().__init__(parent)
        self._manager = manager or get_persona_manager()
        self._current_profile: PersonaProfile | None = None
        self._dirty = False
        self._loading = False
        self._settings = QSettings("LianxinAI", "PersonaHub")
        self._editors: dict[str, QWidget] = {}

        self.setWindowTitle("人格枢控")
        self.setWindowFlags(
            Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setMinimumSize(900, 620)
        self.resize(1180, 760)
        self._build_ui()
        self._restore_window_state()
        self._refresh_profiles()

    def _build_ui(self):
        root_widget = QWidget()
        root_widget.setObjectName("personaRoot")
        self.setCentralWidget(root_widget)
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("人格枢控")
        title.setFont(QFont("Microsoft YaHei UI", 18, QFont.Bold))
        subtitle = QLabel("统一管理莲心在聊天、语音与主动行为中的身份和表达方式")
        subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self._active_label = QLabel()
        self._active_label.setObjectName("activeBadge")
        header.addWidget(self._active_label)
        self._toggle_enabled_btn = QPushButton()
        self._toggle_enabled_btn.clicked.connect(self._toggle_persona_system)
        header.addWidget(self._toggle_enabled_btn)
        self._fullscreen_btn = QPushButton("全屏")
        self._fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        header.addWidget(self._fullscreen_btn)
        root.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_profile_sidebar())
        splitter.addWidget(self._build_editor_panel())
        splitter.addWidget(self._build_preview_panel())
        splitter.setSizes([230, 610, 330])
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self._status_label = QLabel("就绪")
        self._status_label.setObjectName("muted")
        footer.addWidget(self._status_label, 1)
        self._restore_btn = QPushButton("恢复官方设定")
        self._restore_btn.clicked.connect(self._restore_default)
        footer.addWidget(self._restore_btn)
        self._save_btn = QPushButton("保存草稿")
        self._save_btn.clicked.connect(self._save_current)
        footer.addWidget(self._save_btn)
        self._activate_btn = QPushButton("保存并激活")
        self._activate_btn.setObjectName("primaryButton")
        self._activate_btn.clicked.connect(self._activate_current)
        footer.addWidget(self._activate_btn)
        root.addLayout(footer)

        fullscreen_action = QAction(self)
        fullscreen_action.setShortcut(QKeySequence("F11"))
        fullscreen_action.triggered.connect(self._toggle_fullscreen)
        self.addAction(fullscreen_action)
        save_action = QAction(self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self._save_current)
        self.addAction(save_action)
        self.setStyleSheet(self._style_sheet())

    def _build_profile_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        heading = QLabel("人格档案")
        heading.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        layout.addWidget(heading)
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索人格…")
        self._search.textChanged.connect(self._filter_profiles)
        layout.addWidget(self._search)
        self._profile_list = QListWidget()
        self._profile_list.currentItemChanged.connect(self._on_profile_changed)
        layout.addWidget(self._profile_list, 1)
        row = QHBoxLayout()
        for text, slot in (("新建", self._new_profile), ("复制", self._copy_profile)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        row2 = QHBoxLayout()
        for text, slot in (("导入", self._import_profile), ("导出", self._export_profile)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row2.addWidget(button)
        layout.addLayout(row2)
        self._delete_btn = QPushButton("删除人格")
        self._delete_btn.setObjectName("dangerButton")
        self._delete_btn.clicked.connect(self._delete_profile)
        layout.addWidget(self._delete_btn)
        return panel

    def _build_editor_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._tabs.addTab(self._make_form_tab((
            ("profile_name", "档案名称", False, "例如：默认莲心、冷静研究员"),
            ("assistant_name", "助手名称", False, "模型在对话中使用的名字"),
            ("summary", "一句话简介", True, "用一句话概括这个人格"),
            ("identity", "身份与背景", True, "角色经历、世界观和自我认知"),
            ("appearance", "外貌设定", True, "可选；用于保持角色形象一致"),
        )), "基础身份")
        self._tabs.addTab(self._make_form_tab((
            ("personality", "性格设定", True, "核心性格、优点、缺点和情绪倾向"),
            ("habits", "行为习惯", True, "主动关心、安慰、提醒和处理问题的习惯"),
            ("relationship", "与用户的关系", True, "如何理解用户以及关系边界"),
            ("user_address", "对用户的称呼", False, "支持 {user_name} 占位符"),
        )), "性格与关系")
        self._tabs.addTab(self._make_form_tab((
            ("speaking_style", "语言风格", True, "回复长度、专业程度、幽默和口语习惯"),
            ("boundaries", "表达边界", True, "不希望出现的句式、行为和表达"),
        )), "语言与边界")
        self._tabs.addTab(self._make_form_tab((
            ("custom_instructions", "高级补充指令", True,
             "只用于人格表达，不能覆盖工具、隐私和权限规则"),
        )), "高级")
        self._tabs.addTab(self._build_growth_tab(), "成长轨迹")
        return panel

    def _build_growth_tab(self) -> QWidget:
        panel = QWidget()
        self._growth_tab = panel
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        notice = QLabel("成长只会写入可撤销的演化层，永远不能覆盖身份、隐私、权限与安全规则。")
        notice.setObjectName("notice")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self._growth_summary = QLabel()
        self._growth_summary.setWordWrap(True)
        layout.addWidget(self._growth_summary)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("自动成长"))
        self._growth_mode = QComboBox()
        self._growth_mode.addItem("关闭", "off")
        self._growth_mode.addItem("每次确认", "confirm")
        self._growth_mode.addItem("低风险自动成长", "low_risk_auto")
        self._growth_mode.currentIndexChanged.connect(self._save_growth_settings)
        controls.addWidget(self._growth_mode)
        self._allow_requests = QCheckBox("允许主动诉求")
        self._allow_photo_invites = QCheckBox("允许照片邀请")
        self._allow_requests.toggled.connect(self._save_growth_settings)
        self._allow_photo_invites.toggled.connect(self._save_growth_settings)
        controls.addWidget(self._allow_requests)
        controls.addWidget(self._allow_photo_invites)
        self._growth_filter = QComboBox()
        self._growth_filter.addItem("全部记录", "")
        for label, value in (("待确认", "pending"), ("已生效", "applied"), ("已撤销", "reverted"), ("已忽略", "dismissed"), ("已过期", "expired")):
            self._growth_filter.addItem(label, value)
        self._growth_filter.currentIndexChanged.connect(self._refresh_growth)
        controls.addWidget(self._growth_filter)
        controls.addStretch()
        layout.addLayout(controls)
        self._growth_list = QListWidget()
        self._growth_list.currentItemChanged.connect(self._on_growth_selected)
        layout.addWidget(self._growth_list, 1)
        self._growth_detail = QTextEdit()
        self._growth_detail.setReadOnly(True)
        self._growth_detail.setMinimumHeight(130)
        layout.addWidget(self._growth_detail)
        actions = QHBoxLayout()
        self._growth_apply_btn = QPushButton("采纳变化")
        self._growth_revert_btn = QPushButton("撤销变化")
        self._growth_rollback_btn = QPushButton("回退到此版本")
        self._growth_preview_btn = QPushButton("预览效果")
        self._growth_pause_btn = QPushButton("暂停成长 7 天")
        self._growth_export_btn = QPushButton("导出记录")
        self._growth_clear_btn = QPushButton("清空此人格记录")
        self._proactive_why_btn = QPushButton("为什么最近联系我？")
        self._proactive_reduce_btn = QPushButton("减少这类消息")
        self._proactive_stop_btn = QPushButton("停止这类消息")
        self._growth_dismiss_btn = QPushButton("忽略候选")
        for button, slot in (
            (self._growth_apply_btn, self._apply_growth),
            (self._growth_revert_btn, self._revert_growth),
            (self._growth_rollback_btn, self._rollback_growth_version),
            (self._growth_preview_btn, self._preview_growth),
            (self._growth_pause_btn, self._pause_growth),
            (self._growth_export_btn, self._export_growth),
            (self._growth_clear_btn, self._clear_growth),
            (self._proactive_why_btn, self._show_proactive_reason),
            (self._proactive_reduce_btn, self._reduce_proactive_kind),
            (self._proactive_stop_btn, self._stop_proactive_kind),
            (self._growth_dismiss_btn, self._dismiss_growth),
        ):
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self._load_growth_settings()
        return panel

    def _make_form_tab(self, specs) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("editorScroll")
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("editorScrollContent")
        form = QFormLayout(content)
        form.setContentsMargins(10, 12, 14, 12)
        form.setSpacing(12)
        for field, label, multiline, placeholder in specs:
            editor = QTextEdit() if multiline else QLineEdit()
            editor.setPlaceholderText(placeholder)
            if multiline:
                editor.setMinimumHeight(90 if field != "custom_instructions" else 220)
                editor.textChanged.connect(self._on_editor_changed)
            else:
                editor.textChanged.connect(self._on_editor_changed)
            self._editors[field] = editor
            form.addRow(label, editor)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        scroll.setWidget(content)
        return scroll

    def _build_preview_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        heading = QLabel("实时编译预览")
        heading.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        layout.addWidget(heading)
        self._preview_meta = QLabel()
        self._preview_meta.setObjectName("muted")
        self._preview_meta.setWordWrap(True)
        layout.addWidget(self._preview_meta)
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText("选择一个人格后显示最终 Prompt 分层预览")
        layout.addWidget(self._preview, 1)
        note = QLabel("系统工具、隐私与权限规则始终为只读层，无法被高级指令删除。")
        note.setObjectName("notice")
        note.setWordWrap(True)
        layout.addWidget(note)
        return panel

    def _refresh_profiles(self, select_id: str | None = None):
        active = self._manager.get_snapshot()
        select_id = select_id or (self._current_profile.id if self._current_profile else active.profile.id)
        self._profile_list.blockSignals(True)
        self._profile_list.clear()
        selected_item = None
        for profile in self._manager.list_profiles():
            prefix = "● " if profile.id == active.profile.id and active.enabled else "  "
            item = QListWidgetItem(prefix + profile.profile_name)
            item.setData(Qt.UserRole, profile.id)
            item.setToolTip(f"助手名称：{profile.assistant_name}")
            self._profile_list.addItem(item)
            if profile.id == select_id:
                selected_item = item
        self._profile_list.blockSignals(False)
        self._update_active_status()
        if selected_item:
            self._profile_list.setCurrentItem(selected_item)
            self._load_profile(selected_item.data(Qt.UserRole))

    def _load_profile(self, profile_id: str):
        profile = self._manager.load_profile(profile_id)
        self._loading = True
        self._current_profile = profile
        for field, editor in self._editors.items():
            value = getattr(profile, field)
            if isinstance(editor, QTextEdit):
                editor.setPlainText(value)
            else:
                editor.setText(value)
        self._loading = False
        self._set_dirty(False)
        self._delete_btn.setEnabled(profile.id != DEFAULT_PERSONA_ID)
        self._restore_btn.setEnabled(profile.id == DEFAULT_PERSONA_ID)
        self._update_preview()
        self._refresh_growth()

    def _growth_service(self):
        from brain.persona.growth import get_persona_growth_service
        return get_persona_growth_service()

    def _load_growth_settings(self):
        settings = self._growth_service().settings()
        self._growth_mode.blockSignals(True)
        self._allow_requests.blockSignals(True)
        self._allow_photo_invites.blockSignals(True)
        self._growth_mode.setCurrentIndex(max(0, self._growth_mode.findData(settings["mode"])))
        self._allow_requests.setChecked(bool(settings["allow_proactive_requests"]))
        self._allow_photo_invites.setChecked(bool(settings["allow_photo_invites"]))
        self._growth_mode.blockSignals(False)
        self._allow_requests.blockSignals(False)
        self._allow_photo_invites.blockSignals(False)

    def _save_growth_settings(self):
        if not hasattr(self, "_growth_mode"):
            return
        self._growth_service().save_settings({
            "mode": self._growth_mode.currentData(),
            "allow_proactive_requests": self._allow_requests.isChecked(),
            "allow_photo_invites": self._allow_photo_invites.isChecked(),
        })

    def _refresh_growth(self, select_id: int = 0):
        if self._current_profile is None or not hasattr(self, "_growth_list"):
            return
        events = self._growth_service().store.list(self._current_profile.id)
        selected_status = self._growth_filter.currentData() if hasattr(self, "_growth_filter") else ""
        if selected_status:
            events = [event for event in events if event.status == selected_status]
        summary = self._growth_service().summary(self._current_profile.id)
        active = summary["counts"].get("applied", 0)
        paused = "成长已暂停" if self._growth_service().growth_is_paused() else "成长开启"
        self._growth_summary.setText(f"当前生效 {active} 项 · 本周变化 {summary['weekly_changes']} 次 · 采纳率 {summary['adoption_rate']:.0%} · {paused}")
        self._growth_list.blockSignals(True)
        self._growth_list.clear()
        selected = None
        states = {"pending": "待确认", "applied": "已生效", "reverted": "已撤销", "dismissed": "已忽略", "expired": "已过期"}
        for event in events:
            item = QListWidgetItem(f"{states.get(event.status, event.status)} · {event.title}")
            item.setData(Qt.UserRole, event.id)
            self._growth_list.addItem(item)
            if event.id == select_id:
                selected = item
        self._growth_list.blockSignals(False)
        if selected:
            self._growth_list.setCurrentItem(selected)
        elif self._growth_list.count():
            self._growth_list.setCurrentRow(0)
        else:
            self._growth_detail.setPlainText("还没有成长记录。莲心会先基于明确、可解释的互动反馈形成候选变化。")

    def _selected_growth_event(self):
        item = self._growth_list.currentItem() if hasattr(self, "_growth_list") else None
        if item is None or self._current_profile is None:
            return None
        event_id = int(item.data(Qt.UserRole) or 0)
        return next((event for event in self._growth_service().store.list(self._current_profile.id)
                     if event.id == event_id), None)

    def _on_growth_selected(self, *_):
        event = self._selected_growth_event()
        if event is None:
            return
        self._growth_detail.setPlainText(
            f"{event.title}\n\n变化：{event.detail}\n"
            f"之前：{event.old_value or '未设置'}\n之后：{event.proposed_value or event.detail}\n"
            f"字段：{event.field or '旧版记录'}\n风险：{event.risk}\n\n依据：{event.evidence or '无'}"
            f"\n置信度：{event.confidence:.0%}\n独立依据：{event.evidence_count} 次\n状态：{event.status}\n版本：{event.version_id or '尚未生效'}\n创建于：{event.created_at}"
        )
        self._growth_apply_btn.setEnabled(event.status == "pending")
        self._growth_dismiss_btn.setEnabled(event.status == "pending")
        self._growth_revert_btn.setEnabled(event.status == "applied")
        self._growth_rollback_btn.setEnabled(event.status == "applied" and event.version_id > 0)
        self._growth_preview_btn.setEnabled(bool(event.field))

    def _apply_growth(self):
        event = self._selected_growth_event()
        if event is None:
            return
        updated = self._growth_service().store.set_status(event.id, "applied")
        if updated:
            self._refresh_growth(updated.id)
            self.growth_event_applied.emit(updated)

    def _revert_growth(self):
        event = self._selected_growth_event()
        if event is None:
            return
        updated = self._growth_service().store.set_status(event.id, "reverted")
        if updated:
            self._refresh_growth(updated.id)
            self.growth_event_applied.emit(updated)

    def _rollback_growth_version(self):
        event = self._selected_growth_event()
        if event is None or event.version_id <= 0:
            return
        self._growth_service().store.rollback_to_version(self._current_profile.id, event.version_id)
        self._refresh_growth(event.id)

    def _preview_growth(self):
        event = self._selected_growth_event()
        if event is None:
            return
        examples = {
            "response_length": "示例问题：帮我解释这个概念。\n采纳后会按“简洁/详细”偏好调整篇幅。",
            "response_structure": "示例问题：我该怎么处理？\n采纳后会先给结论，再补充必要依据。",
            "interaction_tone": "示例问题：今天有点累。\n采纳后会减少表情，保持更克制的表达。",
        }
        QMessageBox.information(self, "成长效果预览", examples.get(event.field, event.detail))

    def _pause_growth(self):
        self._growth_service().pause_growth(24 * 7)
        self._refresh_growth()

    def _export_growth(self):
        if self._current_profile is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出成长记录", "persona_growth.json", "JSON (*.json)")
        if path:
            from pathlib import Path
            Path(path).write_text(self._growth_service().export_events(self._current_profile.id), encoding="utf-8")

    def _clear_growth(self):
        if self._current_profile is None:
            return
        if QMessageBox.question(self, "清空成长记录", "将删除该人格全部成长记录和版本，是否继续？") == QMessageBox.Yes:
            self._growth_service().clear_events(self._current_profile.id)
            self._refresh_growth()

    def _proactive_kind(self) -> str:
        reason = self._growth_service().settings().get("last_proactive_reason", {}) or {}
        return str(reason.get("kind") or "curiosity")

    def _show_proactive_reason(self):
        reason = self._growth_service().settings().get("last_proactive_reason", {}) or {}
        if not reason:
            QMessageBox.information(self, "主动联系依据", "最近没有由成长偏好触发的主动诉求。")
            return
        QMessageBox.information(self, "主动联系依据",
                                f"类型：{reason.get('kind', '未知')}\n来源：{reason.get('source', '未知')}\n说明：{reason.get('summary', '无')}")

    def _reduce_proactive_kind(self):
        self._growth_service().record_proactive_result(self._proactive_kind(), "reject")
        QMessageBox.information(self, "已调整", "已减少这类主动消息；再次拒绝同类消息会自动停止。")

    def _stop_proactive_kind(self):
        kind = self._proactive_kind()
        settings = self._growth_service().settings()
        rejected = dict(settings.get("proactive_rejections", {}) or {})
        rejected[kind] = 2
        self._growth_service().save_settings({"proactive_rejections": rejected})
        QMessageBox.information(self, "已停止", "已停止这类主动消息，可随时在此重新开启相关偏好。")

    def _dismiss_growth(self):
        event = self._selected_growth_event()
        if event is not None:
            self._growth_service().store.set_status(event.id, "dismissed")
            self._refresh_growth(event.id)

    def show_growth_event(self, event_id: int):
        self._tabs.setCurrentWidget(self._growth_tab)
        self._refresh_growth(int(event_id or 0))

    def _on_profile_changed(self, current, previous):
        if current is None or self._loading:
            return
        if self._dirty and previous is not None:
            decision = QMessageBox.question(
                self, "未保存的修改", "当前人格有未保存修改，是否先保存？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if decision == QMessageBox.Cancel:
                self._profile_list.blockSignals(True)
                self._profile_list.setCurrentItem(previous)
                self._profile_list.blockSignals(False)
                return
            if decision == QMessageBox.Save and not self._save_current():
                self._profile_list.blockSignals(True)
                self._profile_list.setCurrentItem(previous)
                self._profile_list.blockSignals(False)
                return
        self._load_profile(current.data(Qt.UserRole))

    def _editor_value(self, field: str) -> str:
        editor = self._editors[field]
        return editor.toPlainText() if isinstance(editor, QTextEdit) else editor.text()

    def _profile_from_editors(self) -> PersonaProfile:
        if self._current_profile is None:
            raise PersonaValidationError(["请先选择人格"])
        values = {field: self._editor_value(field).strip() for field in self._editors}
        return self._current_profile.updated(**values)

    def _on_editor_changed(self):
        if self._loading:
            return
        self._set_dirty(True)
        self._update_preview()

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        marker = " · 有未保存修改" if dirty else ""
        self._status_label.setText("正在编辑" + marker if self._current_profile else "就绪")

    def _update_preview(self):
        try:
            profile = self._profile_from_editors()
            current = self._manager.get_snapshot()
            snapshot = PersonaSnapshot(
                profile=profile,
                revision=current.revision,
                enabled=True,
                activated_at=current.activated_at,
            )
            compiled = PersonaPromptComposer.compose(
                snapshot,
                user_name=get_user_name(),
                core_policy=get_core_system_policy(),
                scene_policy="不同渠道会在运行时追加各自的场景规则。",
            )
            self._preview.setPlainText(compiled.text)
            self._preview_meta.setText(
                f"约 {compiled.estimated_tokens} Token · {len(compiled.layers)} 个分层 · 配置有效"
            )
        except Exception as exc:
            self._preview_meta.setText(f"配置暂不可用：{exc}")
            self._preview.clear()

    def _save_current(self) -> bool:
        try:
            profile = self._profile_from_editors()
            self._manager.save_profile(profile)
            self._current_profile = profile
            self._set_dirty(False)
            active = self._manager.get_snapshot()
            current_item = self._profile_list.currentItem()
            if current_item is not None and current_item.data(Qt.UserRole) == profile.id:
                prefix = "● " if active.enabled and active.profile.id == profile.id else "  "
                current_item.setText(prefix + profile.profile_name)
                current_item.setToolTip(f"助手名称：{profile.assistant_name}")
            if active.profile.id == profile.id:
                self._status_label.setText("草稿已保存；点击“保存并激活”后应用修改")
            else:
                self._status_label.setText("草稿已保存")
            return True
        except (PersonaValidationError, PersonaStoreError, OSError) as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return False

    def _activate_current(self):
        if not self._save_current() or self._current_profile is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("激活人格")
        box.setText(f"准备激活“{self._current_profile.profile_name}”。")
        box.setInformativeText("继续当前对话会保留事实并抑制旧人格风格；新建对话可获得最纯净的切换效果。")
        continue_btn = box.addButton("继续当前对话", QMessageBox.AcceptRole)
        new_btn = box.addButton("新建对话并切换", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.exec_()
        clicked = box.clickedButton()
        if clicked not in (continue_btn, new_btn):
            return
        try:
            snapshot = self._manager.activate(self._current_profile.id, enable=True)
            start_new = clicked is new_btn
            self._update_active_status()
            self._refresh_profiles(self._current_profile.id)
            self._status_label.setText(
                f"已激活 {snapshot.profile.profile_name}，从下一条新请求生效"
            )
            self.persona_activated.emit(snapshot.profile.profile_name, start_new)
        except Exception as exc:
            QMessageBox.critical(self, "激活失败", str(exc))

    def _new_profile(self):
        name, ok = QInputDialog.getText(self, "新建人格", "人格档案名称：")
        if ok and name.strip():
            try:
                profile = self._manager.create_profile(name.strip())
                self._refresh_profiles(profile.id)
            except Exception as exc:
                QMessageBox.warning(self, "新建失败", str(exc))

    def _copy_profile(self):
        if self._current_profile is None:
            return
        name, ok = QInputDialog.getText(
            self, "复制人格", "新档案名称：", text=f"{self._current_profile.profile_name} 副本"
        )
        if ok and name.strip():
            profile = self._manager.create_profile(name.strip(), self._current_profile.id)
            self._refresh_profiles(profile.id)

    def _delete_profile(self):
        if self._current_profile is None:
            return
        if QMessageBox.question(
            self, "删除人格", f"确定删除“{self._current_profile.profile_name}”吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            self._manager.delete_profile(self._current_profile.id)
            self._current_profile = None
            self._refresh_profiles(DEFAULT_PERSONA_ID)
        except Exception as exc:
            QMessageBox.warning(self, "无法删除", str(exc))

    def _restore_default(self):
        if self._current_profile is None or self._current_profile.id != DEFAULT_PERSONA_ID:
            return
        if QMessageBox.question(
            self, "恢复官方设定", "将覆盖默认莲心的当前草稿，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes:
            profile = self._manager.restore_default()
            self._refresh_profiles(profile.id)

    def _import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入人格", "", "人格配置 (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            profile = PersonaProfile.from_dict(data)
            now = utc_now_iso()
            profile = replace(
                profile, id=uuid.uuid4().hex, is_builtin=False,
                created_at=now, updated_at=now,
            )
            self._manager.save_profile(profile)
            self._refresh_profiles(profile.id)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))

    def _export_profile(self):
        if self._current_profile is None:
            return
        if self._dirty and not self._save_current():
            return
        default_name = f"{self._current_profile.profile_name}.json"
        path, _ = QFileDialog.getSaveFileName(self, "导出人格", default_name, "人格配置 (*.json)")
        if path:
            try:
                Path(path).write_text(
                    json.dumps(self._current_profile.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:
                QMessageBox.warning(self, "导出失败", str(exc))

    def _filter_profiles(self, text: str):
        query = text.strip().casefold()
        for index in range(self._profile_list.count()):
            item = self._profile_list.item(index)
            item.setHidden(query not in item.text().casefold())

    def _toggle_persona_system(self):
        snapshot = self._manager.get_snapshot()
        try:
            if snapshot.enabled:
                self._manager.set_enabled(False)
            else:
                # 重新从磁盘加载当前档案，避免启用尚未应用的旧内存快照。
                self._manager.activate(snapshot.profile.id, enable=True)
            self._update_active_status()
            self._refresh_profiles()
        except Exception as exc:
            QMessageBox.warning(self, "切换失败", str(exc))

    def _update_active_status(self):
        snapshot = self._manager.get_snapshot()
        if snapshot.enabled:
            self._active_label.setText(f"已激活：{snapshot.profile.profile_name}")
            self._toggle_enabled_btn.setText("停用人格系统")
        else:
            self._active_label.setText("使用旧版人格 Prompt")
            self._toggle_enabled_btn.setText("启用人格系统")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self._fullscreen_btn.setText("全屏")
        else:
            self.showFullScreen()
            self._fullscreen_btn.setText("退出全屏")

    def _restore_window_state(self):
        geometry = self._settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event):
        if self._dirty:
            result = QMessageBox.question(
                self, "未保存的修改", "关闭前保存当前人格吗？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if result == QMessageBox.Cancel:
                event.ignore()
                return
            if result == QMessageBox.Save and not self._save_current():
                event.ignore()
                return
        self._settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)

    @staticmethod
    def _style_sheet() -> str:
        return """
            QWidget#personaRoot { background: #171729; color: #EEF0F8; }
            QWidget#panel { background: #202033; border: 1px solid #353551; border-radius: 12px; }
            QLabel { color: #EEF0F8; background: transparent; }
            QLabel#muted { color: #9399B2; }
            QLabel#activeBadge { color: #C9CEFF; background: #292A48; border: 1px solid #555EAE; border-radius: 8px; padding: 6px 10px; }
            QLabel#notice { color: #B8BED5; background: #292A3F; border-left: 3px solid #6C7BFF; padding: 8px; }
            QLineEdit, QTextEdit, QListWidget { background: #19192A; color: #EEF0F8; border: 1px solid #3A3A58; border-radius: 8px; padding: 7px; selection-background-color: #5865D8; }
            QLineEdit:focus, QTextEdit:focus { border-color: #6C7BFF; }
            QListWidget::item { padding: 9px 7px; margin: 2px; border-radius: 7px; }
            QListWidget::item:selected { background: #34365B; color: white; }
            QPushButton { background: #2A2A41; color: #DDE0EE; border: 1px solid #41415E; border-radius: 8px; padding: 7px 12px; }
            QPushButton:hover { background: #353551; border-color: #6C7BFF; }
            QPushButton#primaryButton { background: #5B67E8; color: white; border-color: #7480FF; font-weight: bold; }
            QPushButton#primaryButton:hover { background: #6C78F4; }
            QPushButton#dangerButton { color: #F0A1AD; }
            QTabWidget::pane { border: none; background: transparent; }
            QTabBar::tab { background: #24243A; color: #9FA5BE; padding: 9px 14px; border: none; }
            QTabBar::tab:selected { color: white; background: #343653; border-bottom: 2px solid #6C7BFF; }
            QScrollArea { border: none; background: transparent; }
            QScrollArea#editorScroll, QWidget#editorScrollContent { background: #202033; }
            QScrollBar:vertical { background: #1B1B2D; width: 8px; margin: 0; }
            QScrollBar::handle:vertical { background: #4A4C69; min-height: 28px; border-radius: 4px; }
            QScrollBar::handle:vertical:hover { background: #62658A; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            QSplitter::handle { background: transparent; width: 8px; }
        """
