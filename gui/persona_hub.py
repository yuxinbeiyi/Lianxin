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
