"""莲心自习室：沉浸式专注、任务和统计窗口。"""

from datetime import datetime

from PyQt5.QtCore import QRectF, Qt, pyqtProperty, pyqtSignal, QPropertyAnimation
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from .database import StudyDatabase
from .timer import FocusTimer


class FocusRing(QWidget):
    """暖色圆环倒计时，独立绘制避免整页重绘。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.setMaximumSize(360, 360)
        self._remaining = 1500.0
        self._total = 1500.0
        self._phase = "focus"
        self._animation = QPropertyAnimation(self, b"displayRemaining", self)
        self._animation.setDuration(850)

    def set_timer(self, remaining: int, total: int, phase: str = "focus"):
        self._total = max(1.0, float(total))
        self._phase = phase
        self._animation.stop()
        self._animation.setStartValue(self._remaining)
        self._animation.setEndValue(float(max(0, remaining)))
        self._animation.start()

    def reset(self, seconds: int):
        self._animation.stop()
        self._remaining = float(max(0, seconds))
        self._total = float(max(1, seconds))
        self._phase = "focus"
        self.update()

    def get_display_remaining(self):
        return self._remaining

    def set_display_remaining(self, value):
        self._remaining = float(value)
        self.update()

    displayRemaining = pyqtProperty(float, get_display_remaining, set_display_remaining)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        rect = QRectF((self.width() - side) / 2 + 18, (self.height() - side) / 2 + 18,
                      side - 36, side - 36)
        track = QPen(QColor("#E8D7C0"), 7, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(track)
        painter.drawArc(rect, 0, 360 * 16)
        progress = max(0.0, min(1.0, self._remaining / self._total))
        color = QColor("#B9804D") if self._phase == "focus" else QColor("#D19A62")
        painter.setPen(QPen(color, 7, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(rect, 90 * 16, int(-360 * 16 * progress))
        painter.setPen(QColor("#4B352A"))
        painter.setFont(QFont("Consolas", 38, QFont.Bold))
        seconds = max(0, int(round(self._remaining)))
        painter.drawText(rect, Qt.AlignCenter, f"{seconds // 60:02d}:{seconds % 60:02d}")
        painter.setFont(QFont("Microsoft YaHei", 11))
        painter.setPen(QColor("#8A6A50"))
        label = "专注中" if self._phase == "focus" else "休息时间"
        painter.drawText(rect.adjusted(0, 62, 0, 0), Qt.AlignCenter, label)


class StudyRoomWindow(QMainWindow):
    closed = pyqtSignal()
    focus_completed = pyqtSignal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("莲心自习室")
        self.setMinimumSize(900, 620)
        self.resize(1180, 760)
        self._db = StudyDatabase()
        self._visit_id = self._db.open_visit()
        self._timer = FocusTimer(self)
        self._timer.tick.connect(self._on_timer_tick)
        self._timer.phase_changed.connect(self._on_phase_changed)
        self._timer.completed.connect(self._on_timer_completed)
        self._is_fullscreen = False
        self._task_rows = {}
        self._build_ui()
        self.setStyleSheet(STUDY_ROOM_STYLE)
        self._refresh_tasks()
        self._refresh_stats()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("study_root")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("study_sidebar")
        sidebar.setFixedWidth(230)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(22, 28, 18, 20)
        side_layout.setSpacing(10)
        brand = QLabel("莲心自习室")
        brand.setObjectName("study_brand")
        side_layout.addWidget(brand)
        subtitle = QLabel("一起把时间用在重要的事上")
        subtitle.setObjectName("study_subtitle")
        subtitle.setWordWrap(True)
        side_layout.addWidget(subtitle)
        side_layout.addSpacing(24)
        self._nav_buttons = []
        for text, index in (("⌂  今日", 0), ("□  任务", 1), ("▥  统计", 2), ("✦  空间", 3)):
            button = QPushButton(text)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self._switch_view(i))
            side_layout.addWidget(button)
            self._nav_buttons.append(button)
        side_layout.addStretch()
        self._room_hint = QLabel("今天也和莲心一起，安静完成一件事。")
        self._room_hint.setObjectName("study_hint")
        self._room_hint.setWordWrap(True)
        side_layout.addWidget(self._room_hint)
        root_layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(34, 26, 38, 34)
        content_layout.setSpacing(14)
        topbar = QHBoxLayout()
        self._page_title = QLabel("今日专注")
        self._page_title.setObjectName("study_page_title")
        topbar.addWidget(self._page_title)
        topbar.addStretch()
        for label, slot in (("—", self.showMinimized), ("□", self._toggle_fullscreen), ("×", self.close)):
            button = QPushButton(label)
            button.setObjectName("window_button")
            button.setFixedSize(36, 30)
            button.clicked.connect(slot)
            topbar.addWidget(button)
        content_layout.addLayout(topbar)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_home_view())
        self._stack.addWidget(self._build_tasks_view())
        self._stack.addWidget(self._build_stats_view())
        self._stack.addWidget(self._build_space_view())
        content_layout.addWidget(self._stack, 1)
        root_layout.addWidget(content, 1)
        self._switch_view(0)

    def _build_home_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 18, 34, 18)
        layout.setSpacing(12)
        welcome = QLabel("准备好了吗？")
        welcome.setObjectName("study_hero")
        welcome.setAlignment(Qt.AlignCenter)
        layout.addWidget(welcome)
        self._goal_label = QLabel("选择一项今天最重要的事，莲心会陪你专注完成。")
        self._goal_label.setObjectName("study_lead")
        self._goal_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._goal_label)

        timer_panel = QFrame()
        timer_panel.setObjectName("timer_panel")
        timer_layout = QVBoxLayout(timer_panel)
        timer_layout.setContentsMargins(18, 4, 18, 18)
        timer_layout.setSpacing(10)
        self._phase_label = QLabel("标准专注")
        self._phase_label.setObjectName("phase_label")
        self._phase_label.setAlignment(Qt.AlignCenter)
        self._phase_label.hide()
        self._timer_label = QLabel("25:00")
        self._timer_label.setObjectName("timer_label")
        self._timer_label.setAlignment(Qt.AlignCenter)
        self._timer_label.hide()
        self._timer_ring = FocusRing()
        self._timer_ring.reset(25 * 60)
        timer_layout.addWidget(self._timer_ring, 0, Qt.AlignCenter)
        self._task_combo = QComboBox()
        self._task_combo.setPlaceholderText("选择今天要做的任务（可选）")
        timer_layout.addWidget(self._task_combo)
        presets = QHBoxLayout()
        for text, focus, rest in (("标准 25 / 5", 25, 5), ("深度 50 / 10", 50, 10), ("长时 90 / 15", 90, 15)):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, f=focus, r=rest: self._set_preset(f, r))
            presets.addWidget(button)
        timer_layout.addLayout(presets)
        self._home_start = QPushButton("开始专注")
        self._home_start.setObjectName("primary_button")
        self._home_start.clicked.connect(self._start_focus)
        timer_layout.addWidget(self._home_start)
        controls = QHBoxLayout()
        self._pause_button = QPushButton("暂停")
        self._pause_button.clicked.connect(self._toggle_pause)
        self._pause_button.setEnabled(False)
        self._stop_button = QPushButton("结束本次")
        self._stop_button.clicked.connect(self._stop_focus)
        self._stop_button.setEnabled(False)
        controls.addWidget(self._pause_button)
        controls.addWidget(self._stop_button)
        timer_layout.addLayout(controls)
        layout.addWidget(timer_panel, 1)
        support_row = QHBoxLayout()
        support_row.setSpacing(14)
        goal_card = QFrame()
        goal_card.setObjectName("paper_card")
        goal_layout = QVBoxLayout(goal_card)
        goal_kicker = QLabel("今日目标")
        goal_kicker.setObjectName("card_kicker")
        goal_layout.addWidget(goal_kicker)
        goal_title = QLabel("把一件重要的事，安静地推进一点。")
        goal_title.setObjectName("card_title")
        goal_layout.addWidget(goal_title)
        support_row.addWidget(goal_card, 1)
        companion_card = QFrame()
        companion_card.setObjectName("companion_card")
        companion_layout = QVBoxLayout(companion_card)
        companion_kicker = QLabel("莲心在这里")
        companion_kicker.setObjectName("card_kicker")
        companion_layout.addWidget(companion_kicker)
        self._companion_label = QLabel("今天不用一次做完所有事，先认真开始 25 分钟。")
        self._companion_label.setObjectName("companion_label")
        self._companion_label.setWordWrap(True)
        companion_layout.addWidget(self._companion_label)
        support_row.addWidget(companion_card, 1)
        layout.addLayout(support_row)
        self._completion_label = QLabel()
        self._completion_label.setObjectName("completion_label")
        self._completion_label.setWordWrap(True)
        self._completion_label.hide()
        layout.addWidget(self._completion_label)
        layout.addStretch()
        return page

    def _build_tasks_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        row = QHBoxLayout()
        self._task_search = QLineEdit()
        self._task_search.setPlaceholderText("搜索任务...")
        self._task_search.textChanged.connect(self._filter_tasks)
        row.addWidget(self._task_search, 1)
        self._new_task_edit = QLineEdit()
        self._new_task_edit.setPlaceholderText("添加一个任务")
        row.addWidget(self._new_task_edit, 1)
        add = QPushButton("添加")
        add.setObjectName("primary_button")
        add.clicked.connect(self._add_task)
        row.addWidget(add)
        layout.addLayout(row)
        self._task_list = QListWidget()
        self._task_list.itemChanged.connect(self._task_checked)
        layout.addWidget(self._task_list, 1)
        buttons = QHBoxLayout()
        remove = QPushButton("删除选中任务")
        remove.clicked.connect(self._delete_selected_task)
        start = QPushButton("用选中任务开始")
        start.setObjectName("primary_button")
        start.clicked.connect(self._start_selected_task)
        buttons.addWidget(remove)
        buttons.addStretch()
        buttons.addWidget(start)
        layout.addLayout(buttons)
        return page

    def _build_stats_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(18)
        self._metric_grid = QGridLayout()
        self._metric_labels = {}
        for index, (key, title) in enumerate((("focus", "今日专注"), ("room", "打开自习室"), ("sessions", "进入次数"), ("streak", "连续自律"))):
            frame = QFrame()
            frame.setObjectName("metric_panel")
            frame_layout = QVBoxLayout(frame)
            title_label = QLabel(title)
            title_label.setObjectName("metric_title")
            value = QLabel("0")
            value.setObjectName("metric_value")
            frame_layout.addWidget(title_label)
            frame_layout.addWidget(value)
            self._metric_labels[key] = value
            self._metric_grid.addWidget(frame, index // 2, index % 2)
        layout.addLayout(self._metric_grid)
        trend_title = QLabel("最近七天")
        trend_title.setObjectName("section_title")
        layout.addWidget(trend_title)
        self._trend_layout = QVBoxLayout()
        layout.addLayout(self._trend_layout)
        self._growth_label = QLabel()
        self._growth_label.setObjectName("companion_label")
        self._growth_label.setWordWrap(True)
        layout.addWidget(self._growth_label)
        layout.addStretch()
        return page

    def _build_space_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel("空间")
        title.setObjectName("study_hero")
        layout.addWidget(title)
        text = QLabel("这里会逐步加入背景、音乐、莲心陪伴形象和环境偏好。\n当前版本先保持安静、轻量的专注空间。")
        text.setObjectName("study_lead")
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch()
        return page

    def _switch_view(self, index: int):
        self._stack.setCurrentIndex(index)
        titles = ("今日专注", "任务", "统计", "空间")
        self._page_title.setText(titles[index])
        for i, button in enumerate(self._nav_buttons):
            button.setChecked(i == index)
        if index == 2:
            self._refresh_stats()

    def _set_preset(self, focus: int, rest: int):
        self._preset_focus, self._preset_rest = focus, rest
        self._timer_label.setText(f"{focus:02d}:00")
        self._timer_ring.reset(focus * 60)
        self._companion_label.setText(f"莲心：为你准备了 {focus} 分钟专注和 {rest} 分钟休息。")

    def _start_focus(self):
        focus = getattr(self, "_preset_focus", 25)
        rest = getattr(self, "_preset_rest", 5)
        task_id = self._task_combo.currentData()
        task_name = self._task_combo.currentText() if task_id else ""
        self._timer.start_focus(focus * 60, rest * 60, task_name)
        self._home_start.setText("专注进行中")
        self._home_start.setEnabled(False)
        self._pause_button.setText("暂停")
        self._pause_button.setEnabled(True)
        self._stop_button.setEnabled(True)
        self._completion_label.hide()
        self._switch_view(0)

    def _toggle_pause(self):
        if not self._timer.active:
            return
        self._timer.toggle_pause()
        if self._timer.paused:
            self._pause_button.setText("继续")
            self._companion_label.setText("莲心：我会在这里安静等你，准备好后再继续。")
        else:
            self._pause_button.setText("暂停")
            self._companion_label.setText("莲心：回到专注状态，慢慢把当下的事情做好。")

    def _stop_focus(self):
        if not self._timer.active:
            return
        answer = QMessageBox.question(
            self, "结束本次专注", "要结束当前专注并保存已进行的时间吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        phase = self._timer.phase
        started_at = self._timer.started_at
        task_name = self._timer.task_name
        elapsed = self._timer.stop()
        if phase == "focus" and elapsed > 0:
            self._db.add_focus_session(self._task_combo.currentData(), task_name, started_at, elapsed, False)
        self._reset_timer_controls()
        self._timer_label.setText(f"{getattr(self, '_preset_focus', 25):02d}:00")
        self._timer_ring.reset(getattr(self, '_preset_focus', 25) * 60)
        self._phase_label.setText("标准专注")
        self._companion_label.setText("莲心：没关系，每一次开始都是在为自己积累力量。")
        self._refresh_stats()

    def _reset_timer_controls(self):
        self._home_start.setEnabled(True)
        self._home_start.setText("开始专注")
        self._pause_button.setEnabled(False)
        self._pause_button.setText("暂停")
        self._stop_button.setEnabled(False)

    def _start_selected_task(self):
        item = self._task_list.currentItem()
        if item:
            self._task_combo.setCurrentIndex(self._task_combo.findData(item.data(Qt.UserRole)))
        self._switch_view(0)
        self._start_focus()

    def _on_timer_tick(self, remaining: int, phase: str):
        self._timer_label.setText(f"{remaining // 60:02d}:{remaining % 60:02d}")
        self._timer_ring.set_timer(remaining, self._timer.total, phase)
        self._phase_label.setText("专注进行中" if phase == "focus" else "休息时间")
        self._phase_label.setStyleSheet("color: #F2A65A;" if phase == "focus" else "color: #78C7A2;")

    def _on_phase_changed(self, phase: str):
        if phase == "idle":
            self._reset_timer_controls()
        elif phase == "break":
            self._pause_button.setText("暂停")
        elif phase == "paused":
            self._pause_button.setText("继续")

    def _on_timer_completed(self, phase: str, duration: int):
        if phase == "focus":
            task_id = self._task_combo.currentData()
            task_name = self._task_combo.currentText() if task_id else ""
            self._db.add_focus_session(task_id, task_name, self._timer.started_at, duration, True)
            self._companion_label.setText("莲心：辛苦啦，这段时间你确实专注在重要的事情上。")
            self._completion_label.setText(
                f"本次专注已完成  ·  {self._format_duration(duration)}"
                + (f"  ·  任务：{task_name}" if task_name else "  ·  未绑定任务")
            )
            self._completion_label.show()
            self._growth_label.setText("莲心记录：你刚刚完成了一次专注，继续保持自己的节奏。")
            self.focus_completed.emit(task_name, duration)
        else:
            self._companion_label.setText("莲心：休息结束了，准备好继续下一段了吗？")
        if phase == "focus" and self._timer.break_seconds > 0 and self._timer.active:
            self._home_start.setEnabled(False)
            self._home_start.setText("休息进行中")
            self._pause_button.setEnabled(True)
            self._stop_button.setEnabled(True)
        elif phase == "break":
            self._pause_button.setEnabled(True)
            self._stop_button.setEnabled(True)
        else:
            self._reset_timer_controls()
            self._home_start.setText("开始下一段专注")
        self._refresh_stats()

    def _refresh_tasks(self):
        tasks = self._db.tasks()
        self._task_list.blockSignals(True)
        self._task_list.clear()
        self._task_combo.clear()
        self._task_combo.addItem("不绑定任务", None)
        self._task_rows.clear()
        for task in tasks:
            item = QListWidgetItem(("✓  " if task["completed"] else "□  ") + task["title"])
            item.setData(Qt.UserRole, task["id"])
            item.setCheckState(Qt.Checked if task["completed"] else Qt.Unchecked)
            self._task_list.addItem(item)
            self._task_rows[task["id"]] = item
            if not task["completed"]:
                self._task_combo.addItem(task["title"], task["id"])
        self._task_list.blockSignals(False)
        self._filter_tasks(self._task_search.text() if hasattr(self, "_task_search") else "")

    def _filter_tasks(self, text: str):
        query = (text or "").strip().lower()
        for item in self._task_rows.values():
            item.setHidden(query not in item.text().lower())

    def _add_task(self):
        title = self._new_task_edit.text().strip()
        if not title:
            return
        self._db.add_task(title)
        self._new_task_edit.clear()
        self._refresh_tasks()

    def _task_checked(self, item, state):
        task_id = item.data(Qt.UserRole)
        if task_id:
            self._db.toggle_task(task_id)
            self._refresh_tasks()

    def _delete_selected_task(self):
        item = self._task_list.currentItem()
        if not item:
            return
        self._db.delete_task(item.data(Qt.UserRole))
        self._refresh_tasks()

    @staticmethod
    def _format_duration(seconds: int) -> str:
        hours, rest = divmod(max(0, int(seconds)), 3600)
        minutes = rest // 60
        return f"{hours}小时{minutes:02d}分" if hours else f"{minutes}分钟"

    def _refresh_stats(self):
        if not hasattr(self, "_metric_labels"):
            return
        data = self._db.stats()
        self._metric_labels["focus"].setText(self._format_duration(data["focus_seconds"]))
        self._metric_labels["room"].setText(self._format_duration(data["room_seconds"]))
        self._metric_labels["sessions"].setText(str(data["visits"]))
        self._metric_labels["streak"].setText(f"{self._db.streak()} 天")
        while self._trend_layout.count():
            item = self._trend_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        trend = self._db.trend(7)
        maximum = max([row["focus_seconds"] for row in trend] + [1])
        for row in trend:
            line = QHBoxLayout()
            line.addWidget(QLabel(row["date"].strftime("%m/%d")))
            bar = QProgressBar()
            bar.setRange(0, maximum)
            bar.setValue(row["focus_seconds"])
            bar.setTextVisible(False)
            line.addWidget(bar, 1)
            line.addWidget(QLabel(self._format_duration(row["focus_seconds"])))
            self._trend_layout.addLayout(line)
        weekly_seconds = sum(row["focus_seconds"] for row in trend)
        best_day = max(trend, key=lambda row: row["focus_seconds"])
        best_text = "暂未产生专注记录" if best_day["focus_seconds"] <= 0 else (
            f"{best_day['date'].strftime('%m/%d')} · {self._format_duration(best_day['focus_seconds'])}"
        )
        self._growth_label.setText(
            f"莲心记录：近 7 日累计专注 {self._format_duration(weekly_seconds)}，最佳专注日：{best_text}。"
            if weekly_seconds > 0 else
            "莲心记录：这一周还没有专注记录，先从一个 25 分钟的小目标开始吧。"
        )

    def _toggle_fullscreen(self):
        if self._is_fullscreen:
            self.showNormal()
        else:
            self.showFullScreen()
        self._is_fullscreen = not self._is_fullscreen

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._is_fullscreen:
            self._toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._timer.active:
            answer = QMessageBox.question(
                self, "结束专注", "当前专注还在进行，关闭自习室会保存已进行的时间。确定关闭吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            phase = self._timer.phase
            elapsed = self._timer.stop()
            if phase == "focus" and elapsed > 0:
                self._db.add_focus_session(self._task_combo.currentData(), self._timer.task_name,
                                           self._timer.started_at, elapsed, False)
        self._db.close_visit(self._visit_id)
        self.closed.emit()
        event.accept()

    def shutdown(self):
        """在主程序退出时无交互地保存当前进度并关闭访问记录。"""
        if self._timer.active:
            phase = self._timer.phase
            started_at = self._timer.started_at
            task_name = self._timer.task_name
            elapsed = self._timer.stop()
            if phase == "focus" and elapsed > 0:
                self._db.add_focus_session(self._task_combo.currentData(), task_name, started_at, elapsed, False)
        self._db.close_visit(self._visit_id)
        self.hide()
        self.closed.emit()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_stats()


STUDY_ROOM_STYLE = """
QMainWindow, QWidget#study_root { background: #F5E8D5; color: #4B352A; }
QFrame#study_sidebar { background: #5A3E2B; border: none; }
QLabel#study_brand { color: #FFF8F1; font-size: 23px; font-weight: 700; }
QLabel#study_subtitle, QLabel#study_hint { color: #E8CFB3; font-size: 12px; }
QLabel#study_page_title { color: #6A4935; font-size: 21px; font-weight: 700; }
QLabel#study_hero { color: #4B352A; font-size: 30px; font-weight: 700; }
QLabel#study_lead { color: #98785D; font-size: 14px; }
QLabel#phase_label, QLabel#section_title { color: #B9804D; font-size: 14px; font-weight: 600; }
QLabel#timer_label { color: #4B352A; font-family: Consolas; font-size: 72px; font-weight: 700; }
QLabel#card_kicker { color: #B9804D; font-size: 12px; font-weight: 700; }
QLabel#card_title { color: #6A4935; font-size: 15px; font-weight: 600; }
QLabel#companion_label { color: #6A4935; font-size: 14px; padding: 0; }
QLabel#completion_label { color: #8A5C35; font-size: 14px; padding: 10px 12px; background: #FFF1DE; border-left: 3px solid #B9804D; }
QPushButton { background: #FFF8F1; color: #6A4935; border: 1px solid #E2CDB5; border-radius: 8px; padding: 9px 12px; }
QPushButton:hover { background: #FFF1DE; border-color: #C98F58; }
QPushButton:checked { background: #F5E8D5; color: #6A4935; border: none; border-left: 4px solid #F4D08C; }
QPushButton#primary_button { background: #B9804D; color: #FFF8F1; border: none; border-radius: 28px; font-weight: 700; padding: 12px 20px; }
QPushButton#primary_button:hover { background: #C98F58; }
QPushButton#window_button { background: transparent; border: none; color: #98785D; font-size: 16px; padding: 0; }
QPushButton#window_button:hover { color: #6A4935; background: #EBD5BA; }
QFrame#timer_panel { background: transparent; border: none; }
QFrame#paper_card, QFrame#companion_card { background: #FFF8F1; border: 1px solid #E8D5BE; border-radius: 12px; }
QFrame#metric_panel { background: #FFF8F1; border: 1px solid #E8D5BE; border-radius: 10px; }
QLabel#metric_title { color: #98785D; font-size: 12px; }
QLabel#metric_value { color: #6A4935; font-size: 25px; font-weight: 700; }
QLineEdit, QComboBox { background: #FFF8F1; color: #6A4935; border: 1px solid #E2CDB5; border-radius: 8px; padding: 9px; }
QListWidget { background: #FFF8F1; color: #6A4935; border: 1px solid #E2CDB5; border-radius: 10px; padding: 8px; }
QListWidget::item { padding: 12px 8px; border-bottom: 1px solid #F0DECA; }
QListWidget::item:selected { background: #F5E8D5; color: #6A4935; }
QProgressBar { background: #E8D7C0; border: none; border-radius: 5px; height: 10px; }
QProgressBar::chunk { background: #B9804D; border-radius: 5px; }
"""
