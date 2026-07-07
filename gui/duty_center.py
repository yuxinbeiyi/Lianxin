"""
DutyCenter：后台职责中心 — 查看和管理莲心的主动行为
"""

from datetime import datetime

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QWidget, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont


_DUTY_ICONS = {
    "proactive":       "💬",
    "slack":           "🐟",
    "heartbeat":       "💓",
    "smart_reminder":  "⏰",
}

_DUTY_TIPS = {
    "proactive":       "主动聊天：根据时段和概率随机找你聊天",
    "slack":           "摸鱼消息：空闲时自己找事做（翻日记/看天气/提醒喝水…）",
    "heartbeat":       "心跳自检：对话结束后回顾是否有遗漏事项",
    "smart_reminder":  "智能提醒：定时检查到期提醒并通知你",
}


class DutyCenter(QDialog):
    def __init__(self, scheduler, parent=None):
        super().__init__(parent)
        self._scheduler = scheduler
        self._cards: dict[str, dict] = {}  # name → {widgets}

        self.setWindowTitle("后台职责中心")
        self.setMinimumSize(480, 360)
        self.resize(500, 420)
        self.setStyleSheet("""
            QDialog { background: #1E2833; }
            QLabel { color: #E0E0E0; background: transparent; }
            QScrollArea { background: transparent; border: none; }
        """)

        self._build_ui()
        self._refresh()

        # 每 10 秒自动刷新
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(10_000)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # 标题
        title = QLabel("后台职责中心")
        title.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        title.setStyleSheet("color: #A0B0FF;")
        root.addWidget(title)

        hint = QLabel("莲心在后台默默做的这些事情，你可以随时暂停或手动触发")
        hint.setFont(QFont("Microsoft YaHei UI", 9))
        hint.setStyleSheet("color: #888; padding-bottom: 4px;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # 可滚动卡片区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self._card_layout = QVBoxLayout(container)
        self._card_layout.setSpacing(8)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll)

        # 底部关闭
        close_btn = QPushButton("关闭")
        close_btn.setFont(QFont("Microsoft YaHei UI", 10))
        close_btn.setFixedWidth(80)
        close_btn.setStyleSheet("""
            QPushButton { background: #3D3D5A; color: #E0E0E0; border-radius: 6px;
                          padding: 6px; border: none; }
            QPushButton:hover { background: #5B5B7A; }
        """)
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ── 刷新 ─────────────────────────────────────────

    def _refresh(self):
        try:
            statuses = self._scheduler.get_all_statuses()
        except Exception:
            return

        existing = set(self._cards.keys())
        current = set()

        for s in statuses:
            current.add(s.name)
            if s.name in self._cards:
                self._update_card(s)
            else:
                self._create_card(s)

        # 移除已不存在的
        for name in existing - current:
            self._remove_card(name)

    # ── 卡片 ─────────────────────────────────────────

    def _create_card(self, s):
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background: #2D2D3F; border: 1px solid #3D3D5A;
                     border-radius: 10px; }
        """)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        # 第1行：图标 + 名称 + 状态 + 运行次数
        row1 = QHBoxLayout()
        icon = _DUTY_ICONS.get(s.name, "🔧")
        name_lbl = QLabel(f"{icon}  {s.display_name}")
        name_lbl.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        name_lbl.setStyleSheet("color: #E0E0E0;")
        row1.addWidget(name_lbl)
        row1.addStretch()

        status_lbl = QLabel()
        status_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        row1.addWidget(status_lbl)

        count_lbl = QLabel()
        count_lbl.setFont(QFont("Microsoft YaHei UI", 9))
        count_lbl.setStyleSheet("color: #6C7BFF;")
        row1.addWidget(count_lbl)
        layout.addLayout(row1)

        # 第2行：上次执行 + 成功/失败
        row2 = QHBoxLayout()
        last_lbl = QLabel()
        last_lbl.setFont(QFont("Microsoft YaHei UI", 8))
        last_lbl.setStyleSheet("color: #888;")
        row2.addWidget(last_lbl)

        result_lbl = QLabel()
        result_lbl.setFont(QFont("Microsoft YaHei UI", 8))
        row2.addWidget(result_lbl)
        row2.addStretch()
        layout.addLayout(row2)

        # 第3行：提示 + 按钮
        row3 = QHBoxLayout()
        tip = QLabel(_DUTY_TIPS.get(s.name, ""))
        tip.setFont(QFont("Microsoft YaHei UI", 8))
        tip.setStyleSheet("color: #666;")
        tip.setWordWrap(True)
        row3.addWidget(tip, 1)

        pause_btn = QPushButton()
        pause_btn.setFont(QFont("Microsoft YaHei UI", 8))
        pause_btn.setFixedSize(48, 22)
        pause_btn.clicked.connect(lambda checked, n=s.name: self._toggle_pause(n))
        row3.addWidget(pause_btn)

        trigger_btn = QPushButton("触发")
        trigger_btn.setFont(QFont("Microsoft YaHei UI", 8))
        trigger_btn.setFixedSize(48, 22)
        trigger_btn.setStyleSheet("""
            QPushButton { background: #4A4A6A; color: #A0B0FF; border-radius: 4px; border: none; }
            QPushButton:hover { background: #6C7BFF; color: #FFF; }
        """)
        trigger_btn.clicked.connect(lambda checked, n=s.name: self._manual_trigger(n))
        row3.addWidget(trigger_btn)
        layout.addLayout(row3)

        self._card_layout.insertWidget(self._card_layout.count() - 1, card)
        self._cards[s.name] = {
            "card": card, "status": status_lbl, "count": count_lbl,
            "last": last_lbl, "result": result_lbl, "pause": pause_btn,
        }

    def _update_card(self, s):
        w = self._cards.get(s.name)
        if not w:
            return

        # 状态
        if s.is_running:
            w["status"].setText("● 运行中")
            w["status"].setStyleSheet("color: #FFD700;")
        elif s.enabled:
            w["status"].setText("● 活跃")
            w["status"].setStyleSheet("color: #27AE60;")
        else:
            w["status"].setText("○ 已暂停")
            w["status"].setStyleSheet("color: #888;")

        # 次数
        w["count"].setText(f"运行 {s.run_count} 次")

        # 上次
        if s.last_fire_time > 0:
            dt = datetime.fromtimestamp(s.last_fire_time)
            w["last"].setText(f"上次: {dt.strftime('%H:%M:%S')}")
        else:
            w["last"].setText("等待中…")

        # 结果
        if s.success_count + s.fail_count > 0:
            w["result"].setText(
                f"✅{s.success_count}  ❌{s.fail_count}"
            )
            w["result"].setStyleSheet("color: #AAA;")
        else:
            w["result"].setText("")
            w["result"].setStyleSheet("")

        # 暂停按钮
        if s.enabled:
            w["pause"].setText("暂停")
            w["pause"].setStyleSheet("""
                QPushButton { background: #3D3D5A; color: #E67E22; border-radius: 4px; border: none; }
                QPushButton:hover { background: #E67E22; color: #FFF; }
            """)
        else:
            w["pause"].setText("开启")
            w["pause"].setStyleSheet("""
                QPushButton { background: #3D3D5A; color: #27AE60; border-radius: 4px; border: none; }
                QPushButton:hover { background: #27AE60; color: #FFF; }
            """)

    def _remove_card(self, name):
        w = self._cards.pop(name, None)
        if w:
            w["card"].deleteLater()

    def _toggle_pause(self, name: str):
        duty = self._scheduler._duties.get(name)
        if not duty:
            return
        duty.status.enabled = not duty.status.enabled

    def _manual_trigger(self, name: str):
        try:
            self._scheduler.manual_trigger(name)
        except Exception:
            pass

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
