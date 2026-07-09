"""
SettingsDialog：莲心全局设置对话框
包含：常规设置、日记本、声音设置、记忆系统 四个选项卡
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QFrame, QMessageBox, QSpinBox, QSlider, QLineEdit,
    QFileDialog, QTabWidget, QComboBox, QWidget,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView,
    QTableWidget, QTableWidgetItem, QFormLayout,
    QScrollArea,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from datetime import datetime
import os
from utils.settings import get_settings
from utils.autostart import enable_autostart, disable_autostart, is_autostart_enabled
from utils.accompany_stats import AccompanyStats
from config import get_heartbeat_config
from config import get_quick_launch_apps, save_quick_launch_apps
from brain.graph_memory import ALL_CATEGORIES, CATEGORY_DESCRIPTIONS
from brain.graph_memory import list_all_facts, delete_facts
from gui.quick_launch_dialog import QuickLaunchEditDialog



class SettingsDialog(QDialog):
    date_saved = pyqtSignal()          # 初识日期保存信号
    font_size_changed = pyqtSignal(int)  # 字体大小变化信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = get_settings()
        self._accompany_stats = AccompanyStats()

        self.setWindowTitle("全局设置")
        self.setMinimumSize(540, 780)
        self.resize(580, 800)
        self.setWindowFlags(Qt.Window)
    
        self._build_ui()
        self._load_from_settings()


    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题
        title = QLabel("⚙️ 全局设置")
        title.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        
        layout.addWidget(title)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #3D3D5A; max-height: 1px;")
        layout.addWidget(line)

        # ========== 选项卡 ==========
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet("""
            QTabBar::tab:selected {
                background: #6C7BFF;
                color: white;
            }
        """)

        # ----- 常规设置选项卡（含滚动区域） -----
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_layout.setContentsMargins(0, 0, 0, 0)

        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(16)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        # ---- 所有控件添加到 scroll_layout ----

        # 表情包发送概率设置
        prob_frame = self._create_frame()
        prob_layout = QVBoxLayout(prob_frame)
        prob_layout.setSpacing(8)

        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("表情包发送概率："))
        self.emotion_prob_slider = QSlider(Qt.Horizontal)
        self.emotion_prob_slider.setRange(0, 100)
        self.emotion_prob_slider.setValue(int(self._settings.emotion_probability * 100))
        self.emotion_prob_slider.setTickPosition(QSlider.TicksBelow)
        self.emotion_prob_slider.setTickInterval(10)
        self.emotion_prob_value = QLabel(f"{int(self._settings.emotion_probability * 100)}%")
        self.emotion_prob_slider.valueChanged.connect(self._on_emotion_prob_changed)
        slider_layout.addWidget(self.emotion_prob_slider)
        slider_layout.addWidget(self.emotion_prob_value)
        slider_layout.addStretch()
        prob_layout.addLayout(slider_layout)

        prob_hint = QLabel("💡 提示：若表情包文件夹为空，则不会发送图片。")
        prob_hint.setFont(QFont("Microsoft YaHei UI", 8))
        prob_hint.setStyleSheet("color: #888888;")
        prob_layout.addWidget(prob_hint)

        scroll_layout.addWidget(prob_frame)

        # 用户称呼设置
        name_frame = self._create_frame()
        name_layout = QVBoxLayout(name_frame)
        name_layout.setSpacing(8)

        name_title = QLabel("👤 用户称呼")
        name_title.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        name_title.setStyleSheet("color: #444466;")
        name_layout.addWidget(name_title)

        name_input_layout = QHBoxLayout()
        self._user_name_edit = QLineEdit()
        self._user_name_edit.setPlaceholderText("雨心")
        self._user_name_edit.setFont(QFont("Microsoft YaHei UI", 10))
        self._user_name_edit.setMaxLength(20)
        self._user_name_edit.setFixedWidth(200)
        name_input_layout.addWidget(self._user_name_edit)
        name_input_layout.addStretch()
        name_layout.addLayout(name_input_layout)

        name_hint = QLabel("💡 莲心在对话中会使用这个称呼来叫你，默认为「雨心」")
        name_hint.setFont(QFont("Microsoft YaHei UI", 8))
        name_hint.setStyleSheet("color: #888888;")
        name_layout.addWidget(name_hint)

        scroll_layout.addWidget(name_frame)

        # 退出确认
        exit_frame = self._create_frame()
        exit_layout = QHBoxLayout(exit_frame)
        self._exit_confirm_cb = QCheckBox("退出时显示确认弹窗（防止误触关闭）")
        self._exit_confirm_cb.setFont(QFont("Microsoft YaHei UI", 9))
        self._exit_confirm_cb.setCursor(Qt.PointingHandCursor)
        exit_layout.addWidget(self._exit_confirm_cb)
        scroll_layout.addWidget(exit_frame)

        # 启动体检
        check_frame = self._create_frame()
        check_layout = QHBoxLayout(check_frame)
        self._startup_check_cb = QCheckBox("启动时进行开机体检（取消勾选可加快启动速度）")
        self._startup_check_cb.setFont(QFont("Microsoft YaHei UI", 9))
        self._startup_check_cb.setCursor(Qt.PointingHandCursor)
        check_layout.addWidget(self._startup_check_cb)
        scroll_layout.addWidget(check_frame)

        # 字体大小
        font_frame = self._create_frame()
        font_layout = QVBoxLayout(font_frame)
        font_title = QLabel("🔤 聊天字体大小")
        font_title.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        font_title.setStyleSheet("color: #444466;")
        font_layout.addWidget(font_title)

        slider_layout_font = QHBoxLayout()
        self._font_slider = QSlider(Qt.Horizontal)
        self._font_slider.setRange(10, 20)
        self._font_slider.setTickPosition(QSlider.TicksBelow)
        self._font_slider.setTickInterval(2)
        self._font_slider.setSingleStep(1)
        self._font_slider.setCursor(Qt.PointingHandCursor)
        slider_layout_font.addWidget(self._font_slider)

        self._font_value_label = QLabel("12")
        self._font_value_label.setFixedWidth(30)
        self._font_value_label.setAlignment(Qt.AlignCenter)
        self._font_value_label.setStyleSheet("color: #A0B0FF; font-weight: bold;")
        slider_layout_font.addWidget(self._font_value_label)

        font_layout.addLayout(slider_layout_font)
        font_tip = QLabel("💡 调整聊天气泡中的文字大小（10-20px）")
        font_tip.setFont(QFont("Microsoft YaHei UI", 8))
        
        font_layout.addWidget(font_tip)
        self._font_slider.valueChanged.connect(self._on_font_size_changed)
        scroll_layout.addWidget(font_frame)

        # 小纸条路径
        note_frame = self._create_frame()
        note_layout = QVBoxLayout(note_frame)
        note_title = QLabel("📝 小纸条文件路径")
        note_title.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        note_title.setStyleSheet("color: #444466;")
        note_layout.addWidget(note_title)

        path_layout = QHBoxLayout()
        self._note_path_edit = QLineEdit()
        self._note_path_edit.setPlaceholderText("默认：桌面/小纸条.txt")
        self._note_path_edit.setFont(QFont("Microsoft YaHei UI", 9))
        path_layout.addWidget(self._note_path_edit)
        self._browse_btn = QPushButton("浏览...")
        self._browse_btn.setFixedSize(70, 32)
        self._browse_btn.setCursor(Qt.PointingHandCursor)
        self._browse_btn.clicked.connect(self._browse_note_path)
        path_layout.addWidget(self._browse_btn)
        note_layout.addLayout(path_layout)

        note_tip = QLabel("💡 小纸条是使用待机模式时给莲心用的txt文件，请选择一个合适的路径创建’小纸条.txt’")
        note_tip.setWordWrap(True)
        note_tip.setFont(QFont("Microsoft YaHei UI", 8))
        
        note_layout.addWidget(note_tip)
        scroll_layout.addWidget(note_frame)

        # 开机自启动
        autostart_frame = self._create_frame()
        autostart_layout = QVBoxLayout(autostart_frame)
        self._autostart_cb = QCheckBox("开启开机自启动（下次开机时莲心自动启动）")
        self._autostart_cb.setFont(QFont("Microsoft YaHei UI", 9))
        self._autostart_cb.setCursor(Qt.PointingHandCursor)
        autostart_layout.addWidget(self._autostart_cb)
        autostart_tip = QLabel("启动后若检测到网络，莲心会自动发送一条问候消息（每天仅一次）")
        autostart_tip.setFont(QFont("Microsoft YaHei UI", 8))
    
        autostart_layout.addWidget(autostart_tip)
        scroll_layout.addWidget(autostart_frame)

        # 初识日期
        first_meet_group = QGroupBox("📅 初识日期")
        first_meet_group.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        first_meet_layout = QVBoxLayout(first_meet_group)
        date_input_layout = QHBoxLayout()

        self._year_spin = QSpinBox()
        self._year_spin.setRange(2000, 2100)
        self._year_spin.setFixedWidth(100)
        self._year_spin.setSuffix(" 年")
        date_input_layout.addWidget(self._year_spin)

        self._month_spin = QSpinBox()
        self._month_spin.setRange(1, 12)
        self._month_spin.setFixedWidth(80)
        self._month_spin.setSuffix(" 月")
        date_input_layout.addWidget(self._month_spin)

        self._day_spin = QSpinBox()
        self._day_spin.setRange(1, 31)
        self._day_spin.setFixedWidth(80)
        self._day_spin.setSuffix(" 日")
        date_input_layout.addWidget(self._day_spin)

        today_btn = QPushButton("今天")
        today_btn.setFixedSize(60, 30)
        today_btn.setCursor(Qt.PointingHandCursor)
        today_btn.clicked.connect(self._set_today_date)
        date_input_layout.addWidget(today_btn)
        date_input_layout.addStretch()

        first_meet_layout.addLayout(date_input_layout)
        date_tip = QLabel("💡 设置你与莲心初次见面的日期，用于计算「一起度过的第X天」")
        date_tip.setFont(QFont("Microsoft YaHei UI", 8))
        date_tip.setStyleSheet("color: #888888;")
        first_meet_layout.addWidget(date_tip)
        scroll_layout.addWidget(first_meet_group)

        # ----- 头像显示设置 -----
        avatar_frame = self._create_frame()
        avatar_layout = QVBoxLayout(avatar_frame)
        avatar_layout.setSpacing(8)

        avatar_title = QLabel("🎨 头像显示设置")
        avatar_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        avatar_layout.addWidget(avatar_title)

        from PyQt5.QtWidgets import QRadioButton, QButtonGroup

        group = QButtonGroup(self)
        self._avatar_radio_animated = QRadioButton("动画状态机（动态GIF）")
        self._avatar_radio_static = QRadioButton("静态头像（本地图片）")
        self._avatar_radio_animated.setFont(QFont("Microsoft YaHei UI", 9))
        self._avatar_radio_static.setFont(QFont("Microsoft YaHei UI", 9))
        group.addButton(self._avatar_radio_animated, 0)
        group.addButton(self._avatar_radio_static, 1)
        avatar_layout.addWidget(self._avatar_radio_animated)
        avatar_layout.addWidget(self._avatar_radio_static)

        path_row = QHBoxLayout()
        self._avatar_path_edit = QLineEdit()
        self._avatar_path_edit.setPlaceholderText("选择本地图片...")
        self._avatar_path_edit.setFont(QFont("Microsoft YaHei UI", 9))
        self._avatar_path_edit.setReadOnly(True)
        self._avatar_path_edit.setStyleSheet("background: #1E1E30; border: 1px solid #3D3D5A; border-radius: 6px; padding: 4px 8px;")
        self._avatar_path_edit.setEnabled(False)
        path_row.addWidget(self._avatar_path_edit)

        browse_btn = QPushButton("浏览")
        browse_btn.setFixedWidth(60)
        browse_btn.setFont(QFont("Microsoft YaHei UI", 9))
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.setStyleSheet("background: #6C7BFF; color: white; border-radius: 6px; border: none; padding: 4px;")
        browse_btn.setEnabled(False)
        path_row.addWidget(browse_btn)
        avatar_layout.addLayout(path_row)

        self._avatar_radio_static.toggled.connect(lambda checked: [
            self._avatar_path_edit.setEnabled(checked),
            browse_btn.setEnabled(checked)
        ])

        browse_btn.clicked.connect(self._browse_avatar_image)

        tip = QLabel("💡 选择静态头像可避免动画卡顿，节省 CPU 资源。")
        tip.setFont(QFont("Microsoft YaHei UI", 8))
        tip.setStyleSheet("background: #1E1E30; padding: 8px; border-radius: 6px;")
        tip.setWordWrap(True)
        avatar_layout.addWidget(tip)

        scroll_layout.addWidget(avatar_frame)

        scroll_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        general_layout.addWidget(scroll_area)
        tab_widget.addTab(general_tab, "常规")

        # ----- 快捷启动设置选项卡 -----
        ql_tab = QWidget()
        ql_layout = QVBoxLayout(ql_tab)
        ql_layout.setSpacing(12)

        ql_tip = QLabel(
            "在这里添加你常用的应用，之后在 QQ 或桌面端说「打开xxx」时，莲心会优先从这里匹配。"
        )
        ql_tip.setWordWrap(True)
        ql_tip.setStyleSheet("color: #666; font-size: 12px;")
        ql_layout.addWidget(ql_tip)

        self._ql_table = QTableWidget()
        self._ql_table.setColumnCount(3)
        self._ql_table.setHorizontalHeaderLabels(["应用名称", "可执行文件", "完整路径"])
        self._ql_table.horizontalHeader().setStretchLastSection(True)
        self._ql_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._ql_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._ql_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._ql_table.setSelectionMode(QTableWidget.SingleSelection)
        self._ql_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._ql_table.setAlternatingRowColors(True)
        self._ql_table.verticalHeader().setVisible(False)
        self._ql_table.setMinimumHeight(200)
        ql_layout.addWidget(self._ql_table)

        ql_btn_layout = QHBoxLayout()
        ql_btn_add = QPushButton("＋ 添加")
        ql_btn_add.setFixedWidth(100)
        ql_btn_add.setCursor(Qt.PointingHandCursor)
        ql_btn_add.clicked.connect(self._on_ql_add)
        ql_btn_edit = QPushButton("✏ 编辑")
        ql_btn_edit.setFixedWidth(100)
        ql_btn_edit.setCursor(Qt.PointingHandCursor)
        ql_btn_edit.clicked.connect(self._on_ql_edit)
        ql_btn_del = QPushButton("✕ 删除")
        ql_btn_del.setFixedWidth(100)
        ql_btn_del.setCursor(Qt.PointingHandCursor)
        ql_btn_del.clicked.connect(self._on_ql_delete)
        ql_btn_layout.addWidget(ql_btn_add)
        ql_btn_layout.addWidget(ql_btn_edit)
        ql_btn_layout.addWidget(ql_btn_del)
        ql_btn_layout.addStretch()
        ql_layout.addLayout(ql_btn_layout)

        ql_layout.addStretch()
        tab_widget.addTab(ql_tab, "⚡ 快捷启动")

        layout.addWidget(tab_widget)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedSize(80, 32)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("保存")
        btn_save.setFixedSize(80, 32)
        btn_save.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

        # 初始化记忆设置界面
        self._refresh_ql_table()

    def _create_frame(self):
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #1E1E30;
                border-radius: 8px;
                border: 1px solid #3D3D5A;
            }
        """)
        return frame

    # === 以下为原有方法（保持不变） ===
    def _browse_note_path(self):
        from pathlib import Path
        current_path = self._note_path_edit.text().strip()
        if not current_path:
            current_path = str(Path.home() / "Desktop")
        else:
            current_path = str(Path(current_path).parent)
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "选择小纸条文件保存位置",
            current_path,
            "文本文件 (*.txt)"
        )
        if file_path:
            if not file_path.endswith('.txt'):
                file_path += '.txt'
            self._note_path_edit.setText(file_path)

    def _on_font_size_changed(self, value):
        self._font_value_label.setText(str(value))

    def _set_today_date(self):
        from datetime import date
        today = date.today()
        self._year_spin.setValue(today.year)
        self._month_spin.setValue(today.month)
        self._day_spin.setValue(today.day)

    def _update_day_range(self):
        year = self._year_spin.value()
        month = self._month_spin.value()
        if month in (1, 3, 5, 7, 8, 10, 12):
            max_day = 31
        elif month in (4, 6, 9, 11):
            max_day = 30
        else:
            is_leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
            max_day = 29 if is_leap else 28
        self._day_spin.setRange(1, max_day)
        if self._day_spin.value() > max_day:
            self._day_spin.setValue(max_day)

    def _load_from_settings(self):
        self._exit_confirm_cb.setChecked(self._settings.show_exit_confirmation)
        self._startup_check_cb.setChecked(self._settings.startup_check_enabled)
        self._autostart_cb.setChecked(is_autostart_enabled())
        font_size = self._settings.font_size
        self._font_slider.setValue(font_size)
        self._font_value_label.setText(str(font_size))

        from pathlib import Path
        note_path = self._settings.note_file_path
        default_path = str(Path.home() / "Desktop" / "小纸条.txt")
        if note_path != default_path:
            self._note_path_edit.setText(note_path)
        else:
            self._note_path_edit.setText("")

        self._year_spin.valueChanged.connect(self._update_day_range)
        self._month_spin.valueChanged.connect(self._update_day_range)
        first_date = self._accompany_stats.get_first_meet_date()
        if first_date:
            try:
                y, m, d = map(int, first_date.split('-'))
                self._year_spin.setValue(y)
                self._month_spin.setValue(m)
                self._day_spin.setValue(d)
            except:
                pass
        self._update_day_range()
       
        self.emotion_prob_slider.setValue(int(self._settings.emotion_probability * 100))
        self.emotion_prob_value.setText(f"{int(self._settings.emotion_probability * 100)}%")
        # 头像设置
        from config import get_avatar_config
        avatar_cfg = get_avatar_config()
        mode = avatar_cfg.get("mode", "animated")
        if mode == "static":
            self._avatar_radio_static.setChecked(True)
            path = avatar_cfg.get("static_image_path", "")
            if path:
                self._avatar_path_edit.setText(path)
        else:
            self._avatar_radio_animated.setChecked(True)

        self._user_name_edit.setText(self._settings.user_name)

    def _on_save(self):
        self._settings.show_exit_confirmation = self._exit_confirm_cb.isChecked()
        self._settings.startup_check_enabled = self._startup_check_cb.isChecked()
        self._settings.font_size = self._font_slider.value()
        self.font_size_changed.emit(self._font_slider.value())

        new_path = self._note_path_edit.text().strip()
        if new_path:
            if not new_path.endswith('.txt'):
                new_path += '.txt'
            self._settings.note_file_path = new_path
        else:
            self._settings.note_file_path = ""

        want_autostart = self._autostart_cb.isChecked()
        currently_enabled = is_autostart_enabled()
        if want_autostart != currently_enabled:
            if want_autostart:
                ok, err = enable_autostart()
                if not ok:
                    QMessageBox.warning(self, "自启动设置失败", f"无法写入注册表，请尝试以管理员身份运行。\n\n错误：{err}")
                    return
            else:
                ok, err = disable_autostart()
                if not ok:
                    QMessageBox.warning(self, "自启动设置失败", f"无法删除注册表项。\n\n错误：{err}")
                    return

        date_str = f"{self._year_spin.value():04d}-{self._month_spin.value():02d}-{self._day_spin.value():02d}"
        self._accompany_stats.set_first_meet_date(date_str)
        self.date_saved.emit()

        # ── 保存用户称呼 ──
        self._settings.user_name = self._user_name_edit.text()
        # ── 保存头像设置 ──
        char_widget = self.parent()._char_widget
        if self._avatar_radio_static.isChecked():
            path = self._avatar_path_edit.text().strip()
            if not path or not os.path.exists(path):
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, "提示", "请先选择一张图片作为静态头像。")
                return
            from config import save_avatar_config
            save_avatar_config({"mode": "static", "static_image_path": path})
            char_widget._avatar_mode = "static"
            char_widget._static_image_path = path
            char_widget._apply_static_avatar(path)
        else:
            from config import save_avatar_config
            save_avatar_config({"mode": "animated", "static_image_path": char_widget._static_image_path})
            char_widget._avatar_mode = "animated"
            char_widget._switch_to_animated()

        self.accept()

        self.accept()

    def _on_emotion_prob_changed(self, value: int):
        percent = value
        self.emotion_prob_value.setText(f"{percent}%")
        self._settings.emotion_probability = percent / 100.0

    # ── 快捷启动管理 ─────────────────────────────────────────
    def _refresh_ql_table(self):
        apps = get_quick_launch_apps()
        self._ql_apps = apps
        self._ql_table.setRowCount(len(apps))
        for row, app in enumerate(apps):
            self._ql_table.setItem(row, 0, QTableWidgetItem(app.get("name", "")))
            self._ql_table.setItem(row, 1, QTableWidgetItem(app.get("exe_name", "")))
            self._ql_table.setItem(row, 2, QTableWidgetItem(app.get("path", "")))

    def _on_ql_add(self):
        dlg = QuickLaunchEditDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            self._ql_apps.append(dlg.get_data())
            save_quick_launch_apps(self._ql_apps)
            self._refresh_ql_table()

    def _on_ql_edit(self):
        row = self._ql_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一个应用")
            return
        dlg = QuickLaunchEditDialog(self, data=self._ql_apps[row])
        if dlg.exec_() == QDialog.Accepted:
            self._ql_apps[row] = dlg.get_data()
            save_quick_launch_apps(self._ql_apps)
            self._refresh_ql_table()

    def _on_ql_delete(self):
        row = self._ql_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一个应用")
            return
        name = self._ql_apps[row].get("name", "")
        ok = QMessageBox.question(
            self, "确认删除", f"确定要删除「{name}」吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if ok == QMessageBox.Yes:
            del self._ql_apps[row]
            save_quick_launch_apps(self._ql_apps)
            self._refresh_ql_table()

    def _browse_avatar_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择莲心头像", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            self._avatar_path_edit.setText(file_path)