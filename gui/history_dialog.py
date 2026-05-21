"""
HistoryDialog：历史对话查看器
功能：搜索 / 智能摘要 / 导出 / 删除 / 置顶
"""

import json
import re
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QTextBrowser, QPushButton, QLabel, QSplitter, QWidget,
    QInputDialog, QLineEdit, QMenu, QFileDialog, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QColor

from memory.history_manager import HistoryManager


# ── 后台摘要生成线程 ──────────────────────────────────────────────

class SummaryWorker(QThread):
    """调用 DeepSeek API 为一条会话生成摘要（后台线程）。"""
    summary_ready  = pyqtSignal(int, str)   # (session_id, summary_text)
    error_occurred = pyqtSignal(int, str)   # (session_id, error_msg)

    def __init__(self, session_id: int, messages: list, parent=None):
        super().__init__(parent)
        self._session_id = session_id
        self._messages   = messages

    def run(self):
        try:
            from openai import OpenAI
            from config import get_api_config
            cfg    = get_api_config()
            client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])

            # 最多取前 60 条，每条内容截取 200 字，控制 token 消耗
            lines = []
            for m in self._messages[:60]:
                role_name = "主人" if m["role"] == "user" else "莲心"
                lines.append(f"{role_name}：{m['content'][:200]}")
            conversation = "\n".join(lines)

            resp = client.chat.completions.create(
                model=cfg["model"],
                max_tokens=80,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个对话摘要助手。"
                            "请用1~2句简洁的中文概括以下对话的主要内容，不超过50个字。"
                        ),
                    },
                    {"role": "user", "content": f"请总结以下对话：\n{conversation}"},
                ],
            )
            summary = resp.choices[0].message.content.strip()
            self.summary_ready.emit(self._session_id, summary)
        except Exception as e:
            self.error_occurred.emit(self._session_id, str(e))


# ── 主对话框 ─────────────────────────────────────────────────────

class HistoryDialog(QDialog):
    """历史对话查看器（含搜索、摘要、导出、删除、置顶）。"""

    import_memory = pyqtSignal(int)   # 携带 session_id，供主窗口导入记忆

    def __init__(self, history_manager: HistoryManager,
                 current_session_id: int = -1, parent=None):
        super().__init__(parent)
        self._mgr                = history_manager
        self._current_session_id = current_session_id   # 主窗口当前会话，删除时判断
        self._sessions: list     = []
        self._summary_workers: list = []   # 防止 QThread 被 GC

        self.setWindowTitle("历史对话记录")
        self.resize(960, 620)
        self.setStyleSheet("background-color: #F5F6FA;")
        self._build_ui()
        self._load_sessions()

    # ── 界面构建 ─────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # 顶部标题
        title_label = QLabel("历史对话记录")
        title_label.setFont(QFont("Microsoft YaHei UI", 13, QFont.Bold))
        title_label.setStyleSheet("color: #3A3A5C; padding: 4px 0;")
        root.addWidget(title_label)

        # ── 主体分割器 ────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet("QSplitter::handle { background: #D8D8E8; }")

        # ── 左侧：搜索框 + 会话列表 ───────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        left_layout.addWidget(
            self._make_label("对话列表")
        )

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("搜索标题、内容、摘要…")
        self._search_box.setFont(QFont("Microsoft YaHei UI", 9))
        self._search_box.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D8D8E8; border-radius: 6px;
                padding: 4px 8px; background: #FFFFFF; color: #3A3A5C;
            }
            QLineEdit:focus { border-color: #6C7BFF; }
        """)
        self._search_box.textChanged.connect(self._on_search_changed)
        left_layout.addWidget(self._search_box)

        self._session_list = QListWidget()
        self._session_list.setFont(QFont("Microsoft YaHei UI", 9))
        self._session_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #D8D8E8; border-radius: 8px;
                background: #FFFFFF; outline: none;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-bottom: 1px solid #F0F0F8;
                color: #3A3A5C;
            }
            QListWidget::item:selected {
                background-color: #EEF0FF; color: #5060DD;
            }
            QListWidget::item:hover { background-color: #F5F6FF; }
        """)
        self._session_list.currentRowChanged.connect(self._on_session_selected)
        self._session_list.itemDoubleClicked.connect(self._on_rename_session)
        self._session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._session_list.customContextMenuRequested.connect(self._on_context_menu)
        left_layout.addWidget(self._session_list)
        splitter.addWidget(left)

        # ── 右侧：摘要 + 消息内容 ──────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        right_layout.addWidget(self._make_label("对话内容"))

        self._content_browser = QTextBrowser()
        self._content_browser.setFont(QFont("Microsoft YaHei UI", 10))
        self._content_browser.setOpenExternalLinks(False)
        self._content_browser.setStyleSheet("""
            QTextBrowser {
                border: 1px solid #D8D8E8; border-radius: 8px;
                background: #FFFFFF; padding: 10px; color: #2C2C2C;
            }
        """)
        right_layout.addWidget(self._content_browser)

        # 摘要显示条（有摘要时显示）
        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setFont(QFont("Microsoft YaHei UI", 9))
        self._summary_label.setStyleSheet("""
            QLabel {
                background: #F0F2FF; border: 1px solid #D0D4F0;
                border-radius: 6px; padding: 6px 10px; color: #5060AA;
            }
        """)
        self._summary_label.hide()
        right_layout.addWidget(self._summary_label)

        splitter.addWidget(right)
        splitter.setSizes([250, 690])
        root.addWidget(splitter)

        # ── 底部按钮区 ────────────────────────────────────────
        S_PURPLE = """
            QPushButton { background:#6C7BFF; color:white; border-radius:8px; border:none; }
            QPushButton:hover   { background:#5A6AEE; }
            QPushButton:pressed { background:#4A5ADE; }
            QPushButton:disabled{ background:#E0E0E8; color:#AAAAAA; }"""
        S_LIGHT = """
            QPushButton { background:#F0F0F8; color:#5060DD; border-radius:8px; border:1px solid #C8CCF0; }
            QPushButton:hover   { background:#E4E4F8; }
            QPushButton:pressed { background:#D8D8EE; }
            QPushButton:disabled{ background:#F5F5F5; color:#BBBBBB; border-color:#E0E0E8; }"""
        S_RED = """
            QPushButton { background:#FF5555; color:white; border-radius:8px; border:none; }
            QPushButton:hover   { background:#EE4444; }
            QPushButton:pressed { background:#DD3333; }
            QPushButton:disabled{ background:#E0E0E8; color:#AAAAAA; }"""
        S_PINK = """
            QPushButton { background:#E05080; color:white; border-radius:8px; border:none; }
            QPushButton:hover   { background:#C8406A; }
            QPushButton:pressed { background:#B03060; }
            QPushButton:disabled{ background:#E0E0E8; color:#AAAAAA; }"""
        S_GOLD = """
            QPushButton { background:#F0A800; color:white; border-radius:8px; border:none; }
            QPushButton:hover   { background:#E09800; }
            QPushButton:pressed { background:#CC8800; }
            QPushButton:disabled{ background:#E0E0E8; color:#AAAAAA; }"""

        def btn(text, w, style, enabled=True):
            b = QPushButton(text)
            b.setFixedSize(w, 32)
            b.setFont(QFont("Microsoft YaHei UI", 9))
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(style)
            b.setEnabled(enabled)
            return b

        # 选中会话才能用的按钮
        self._btn_pin     = btn("☆ 置顶",  80, S_GOLD,   False)
        self._btn_summary = btn("生成摘要", 80, S_LIGHT,  False)
        self._btn_export  = btn("导出 ▼",  72, S_LIGHT,  False)
        self._btn_delete  = btn("删除",    60, S_RED,    False)
        self._btn_import  = btn("导入记忆", 88, S_PINK,   False)

        # 全局按钮
        self._btn_batch   = btn("批量摘要", 80, S_LIGHT)
        self._btn_exp_all = btn("导出全部", 80, S_LIGHT)
        btn_close         = btn("关闭",    64, S_PURPLE)

        self._btn_pin.clicked.connect(self._on_pin_clicked)
        self._btn_summary.clicked.connect(self._on_generate_summary)
        self._btn_export.clicked.connect(self._on_export_clicked)
        self._btn_delete.clicked.connect(self._on_delete_clicked)
        self._btn_import.clicked.connect(self._on_import_memory_clicked)
        self._btn_batch.clicked.connect(self._on_batch_summary)
        self._btn_exp_all.clicked.connect(self._on_export_all)
        btn_close.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        for b in (self._btn_pin, self._btn_summary, self._btn_export, self._btn_delete):
            btn_row.addWidget(b)
        btn_row.addStretch()
        for b in (self._btn_batch, self._btn_exp_all, self._btn_import, btn_close):
            btn_row.addWidget(b)
        root.addLayout(btn_row)

    @staticmethod
    def _make_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Microsoft YaHei UI", 9))
        lbl.setStyleSheet("color: #888; padding: 2px 4px;")
        return lbl

    # ── 数据加载 ─────────────────────────────────────────────

    def _load_sessions(self, keyword: str = ""):
        """加载（或按关键词过滤）会话列表，保持当前选中行。"""
        cur_row = self._session_list.currentRow()
        cur_id  = self._sessions[cur_row]["id"] if 0 <= cur_row < len(self._sessions) else -1

        if keyword.strip():
            self._sessions = self._mgr.search_sessions(keyword.strip())
        else:
            self._sessions = self._mgr.get_sessions()

        self._session_list.clear()
        if not self._sessions:
            item = QListWidgetItem("（暂无历史记录）")
            item.setFlags(Qt.NoItemFlags)
            self._session_list.addItem(item)
            self._set_sel_buttons(False)
            self._content_browser.clear()
            self._summary_label.hide()
            return

        kw_lower = keyword.strip().lower()
        restore_row = 0
        for i, s in enumerate(self._sessions):
            date_str  = s["created_at"][:10]
            count     = self._mgr.get_message_count(s["id"])
            pin_mark  = "★ " if s.get("is_pinned") else ""
            display   = f"{pin_mark}{date_str}\n{s['title']}  [{count}条]"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, s["id"])
            if s.get("is_pinned"):
                item.setBackground(QColor("#FFFBEE"))
            # 高亮匹配关键词的条目
            if kw_lower and (
                kw_lower in s["title"].lower()
                or kw_lower in (s.get("summary") or "").lower()
            ):
                item.setForeground(QColor("#5060DD"))
            self._session_list.addItem(item)
            if s["id"] == cur_id:
                restore_row = i

        # 尽量恢复原来选中的行
        self._session_list.setCurrentRow(restore_row)

    def _on_session_selected(self, row: int):
        """切换会话时刷新右侧内容、摘要、按钮状态。"""
        has_valid = 0 <= row < len(self._sessions)
        self._set_sel_buttons(has_valid)

        if not has_valid:
            self._content_browser.clear()
            self._summary_label.hide()
            return

        s = self._sessions[row]

        # 置顶按钮文字
        self._btn_pin.setText("★ 取消置顶" if s.get("is_pinned") else "☆ 置顶")

        # 摘要
        summary = (s.get("summary") or "").strip()
        if summary:
            self._summary_label.setText(f"摘要：{summary}")
            self._summary_label.show()
        else:
            self._summary_label.hide()

        # 消息内容
        messages = self._mgr.get_messages(s["id"])
        if not messages:
            self._content_browser.setHtml("<p style='color:#999;'>（该会话暂无消息）</p>")
            return

        kw = self._search_box.text().strip()
        html_parts = []
        for msg in messages:
            raw     = msg["content"]
            escaped = (raw.replace("&", "&amp;")
                          .replace("<", "&lt;")
                          .replace(">", "&gt;"))
            # 高亮搜索词
            if kw:
                escaped = re.sub(
                    f"({re.escape(kw)})",
                    r'<mark style="background:#FFE066;border-radius:3px;">\1</mark>',
                    escaped,
                    flags=re.IGNORECASE,
                )
            content_html = escaped.replace("\n", "<br>")
            time_str = msg["timestamp"][11:16]

            if msg["role"] == "user":
                html_parts.append(
                    f'<div style="margin:8px 0;">'
                    f'<span style="color:#6C7BFF;font-weight:bold;">主人</span>'
                    f'<span style="color:#AAA;font-size:11px;margin-left:8px;">{time_str}</span><br>'
                    f'<div style="background:#EEF0FF;border-radius:8px;'
                    f'padding:8px 12px;margin-top:4px;color:#3A3A5C;">{content_html}</div>'
                    f'</div>'
                )
            else:
                html_parts.append(
                    f'<div style="margin:8px 0;">'
                    f'<span style="color:#E05080;font-weight:bold;">莲心</span>'
                    f'<span style="color:#AAA;font-size:11px;margin-left:8px;">{time_str}</span><br>'
                    f'<div style="background:#FFF0F5;border-radius:8px;'
                    f'padding:8px 12px;margin-top:4px;color:#3A3A5C;">{content_html}</div>'
                    f'</div>'
                )

        self._content_browser.setHtml(
            "<html><body style='font-family:Microsoft YaHei UI;font-size:10pt;'>"
            + "".join(html_parts)
            + "</body></html>"
        )
        self._content_browser.verticalScrollBar().setValue(0)

    def _set_sel_buttons(self, enabled: bool):
        """批量设置"需选中会话"才可用的按钮状态。"""
        for b in (self._btn_pin, self._btn_summary,
                  self._btn_export, self._btn_delete, self._btn_import):
            b.setEnabled(enabled)

    # ── 搜索 ─────────────────────────────────────────────────

    def _on_search_changed(self, text: str):
        self._load_sessions(keyword=text)

    # ── 双击重命名 ───────────────────────────────────────────

    def _on_rename_session(self, item: QListWidgetItem):
        session_id = item.data(Qt.UserRole)
        if session_id is None:
            return
        row = self._session_list.row(item)
        old = self._sessions[row]["title"] if row < len(self._sessions) else ""
        new_title, ok = QInputDialog.getText(
            self, "重命名会话", "输入新标题：", text=old
        )
        if ok and new_title.strip():
            self._mgr.update_session_title(session_id, new_title.strip())
            self._load_sessions(self._search_box.text())

    # ── 置顶 ─────────────────────────────────────────────────

    def _on_pin_clicked(self):
        row = self._session_list.currentRow()
        if not (0 <= row < len(self._sessions)):
            return
        self._mgr.toggle_pin(self._sessions[row]["id"])
        self._load_sessions(self._search_box.text())

    # ── 智能摘要 ─────────────────────────────────────────────

    def _on_generate_summary(self):
        """为当前选中会话生成摘要。"""
        row = self._session_list.currentRow()
        if not (0 <= row < len(self._sessions)):
            return
        s    = self._sessions[row]
        msgs = self._mgr.get_messages(s["id"])
        if not msgs:
            QMessageBox.information(self, "提示", "该会话没有消息内容，无法生成摘要。")
            return
        self._btn_summary.setEnabled(False)
        self._btn_summary.setText("生成中…")
        self._launch_summary_worker(s["id"], msgs,
                                    self._on_summary_done,
                                    self._on_summary_error_single)

    def _on_summary_done(self, session_id: int, summary: str):
        self._mgr.update_summary(session_id, summary)
        self._btn_summary.setEnabled(True)
        self._btn_summary.setText("生成摘要")
        self._load_sessions(self._search_box.text())

    def _on_summary_error_single(self, _sid: int, err: str):
        self._btn_summary.setEnabled(True)
        self._btn_summary.setText("生成摘要")
        QMessageBox.warning(self, "摘要生成失败", f"调用 API 出错：{err}")

    def _on_batch_summary(self):
        """批量为所有消息数 ≥10 条且没有摘要的会话生成摘要。"""
        all_sessions = self._mgr.get_sessions()
        candidates = [
            s for s in all_sessions
            if not (s.get("summary") or "").strip()
            and self._mgr.get_message_count(s["id"]) >= 10
        ]
        if not candidates:
            QMessageBox.information(
                self, "批量摘要",
                "没有需要生成摘要的会话（条件：消息数≥10 且尚无摘要）。"
            )
            return
        reply = QMessageBox.question(
            self, "批量摘要",
            f"找到 {len(candidates)} 个符合条件的会话，\n"
            f"批量生成摘要将消耗一定 API token，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._batch_queue = list(candidates)
        self._batch_done  = 0
        self._batch_total = len(candidates)
        self._btn_batch.setEnabled(False)
        self._btn_batch.setText(f"0/{self._batch_total}")
        self._next_batch()

    def _next_batch(self):
        if not self._batch_queue:
            self._btn_batch.setEnabled(True)
            self._btn_batch.setText("批量摘要")
            self._load_sessions(self._search_box.text())
            QMessageBox.information(
                self, "批量摘要完成",
                f"已完成 {self._batch_done}/{self._batch_total} 个会话的摘要生成。"
            )
            return
        s    = self._batch_queue.pop(0)
        msgs = self._mgr.get_messages(s["id"])
        self._launch_summary_worker(s["id"], msgs,
                                    self._on_batch_item_done,
                                    self._on_batch_item_done_err)

    def _on_batch_item_done(self, session_id: int, summary: str):
        self._mgr.update_summary(session_id, summary)
        self._batch_done += 1
        self._btn_batch.setText(f"{self._batch_done}/{self._batch_total}")
        self._next_batch()

    def _on_batch_item_done_err(self, _sid: int, _err: str):
        self._batch_done += 1
        self._btn_batch.setText(f"{self._batch_done}/{self._batch_total}")
        self._next_batch()

    def _launch_summary_worker(self, session_id: int, msgs: list,
                                on_ready, on_error):
        """创建并启动 SummaryWorker，连接回调后防 GC。"""
        worker = SummaryWorker(session_id, msgs, self)
        worker.summary_ready.connect(on_ready)
        worker.error_occurred.connect(on_error)
        worker.finished.connect(
            lambda w=worker: self._summary_workers.remove(w)
            if w in self._summary_workers else None
        )
        self._summary_workers.append(worker)
        worker.start()

    # ── 导出 ─────────────────────────────────────────────────

    def _on_export_clicked(self):
        """弹出下拉菜单选择导出格式。"""
        menu = QMenu(self)
        menu.addAction("导出为 TXT",  self._export_txt)
        menu.addAction("导出为 JSON", self._export_json)
        menu.exec_(self._btn_export.mapToGlobal(
            self._btn_export.rect().bottomLeft()
        ))

    def _selected_session_and_msgs(self):
        row = self._session_list.currentRow()
        if not (0 <= row < len(self._sessions)):
            return None, None
        s = self._sessions[row]
        return s, self._mgr.get_messages(s["id"])

    def _export_txt(self):
        s, msgs = self._selected_session_and_msgs()
        if s is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出为 TXT",
            f"{s['title'][:20]}.txt", "文本文件 (*.txt)"
        )
        if not path:
            return
        lines = [f"会话标题：{s['title']}", f"创建时间：{s['created_at']}", ""]
        if (s.get("summary") or "").strip():
            lines += [f"摘要：{s['summary']}", ""]
        lines.append("=" * 40)
        for m in msgs:
            role_name = "主人" if m["role"] == "user" else "莲心"
            lines.append(f"[{m['timestamp'][11:16]}] {role_name}：{m['content']}")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            QMessageBox.information(self, "导出成功", f"已保存到：{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _export_json(self):
        s, msgs = self._selected_session_and_msgs()
        if s is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出为 JSON",
            f"{s['title'][:20]}.json", "JSON 文件 (*.json)"
        )
        if not path:
            return
        data = {
            "session": {
                "id":         s["id"],
                "title":      s["title"],
                "created_at": s["created_at"],
                "summary":    s.get("summary") or "",
                "is_pinned":  bool(s.get("is_pinned")),
            },
            "messages": [
                {"role": m["role"], "content": m["content"],
                 "timestamp": m["timestamp"]}
                for m in msgs
            ],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "导出成功", f"已保存到：{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _on_export_all(self):
        """将所有会话一次性导出为单个 JSON 文件。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出全部会话",
            "莲心AI全部对话.json", "JSON 文件 (*.json)"
        )
        if not path:
            return
        all_sessions = self._mgr.get_sessions()
        result = []
        for s in all_sessions:
            msgs = self._mgr.get_messages(s["id"])
            result.append({
                "session": {
                    "id":         s["id"],
                    "title":      s["title"],
                    "created_at": s["created_at"],
                    "summary":    s.get("summary") or "",
                    "is_pinned":  bool(s.get("is_pinned")),
                },
                "messages": [
                    {"role": m["role"], "content": m["content"],
                     "timestamp": m["timestamp"]}
                    for m in msgs
                ],
            })
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            QMessageBox.information(
                self, "导出成功",
                f"共导出 {len(result)} 个会话到：{path}"
            )
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    # ── 删除 ─────────────────────────────────────────────────

    def _on_delete_clicked(self):
        row = self._session_list.currentRow()
        if not (0 <= row < len(self._sessions)):
            return
        s     = self._sessions[row]
        count = self._mgr.get_message_count(s["id"])

        extra = ""
        if s["id"] == self._current_session_id:
            extra = "\n\n⚠️ 这是当前正在使用的会话，删除后将自动切换到其他会话。"

        reply = QMessageBox.question(
            self, "删除会话",
            f"确定要删除「{s['title']}」吗？\n"
            f"（共 {count} 条消息，删除后不可恢复）{extra}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._mgr.delete_session(s["id"])
        self._load_sessions(self._search_box.text())

    # ── 导入记忆 ─────────────────────────────────────────────

    def _on_import_memory_clicked(self):
        row = self._session_list.currentRow()
        if not (0 <= row < len(self._sessions)):
            return
        self.import_memory.emit(self._sessions[row]["id"])
        self.accept()

    # ── 右键菜单 ─────────────────────────────────────────────

    def _on_context_menu(self, pos):
        item = self._session_list.itemAt(pos)
        if item is None:
            return
        row = self._session_list.row(item)
        if not (0 <= row < len(self._sessions)):
            return
        s = self._sessions[row]

        menu = QMenu(self)
        menu.addAction("重命名",
                       lambda: self._on_rename_session(item))
        pin_text = "取消置顶" if s.get("is_pinned") else "置顶"
        menu.addAction(pin_text,
                       lambda: (self._mgr.toggle_pin(s["id"]),
                                self._load_sessions(self._search_box.text())))
        menu.addSeparator()
        menu.addAction("导出为 TXT",  self._export_txt)
        menu.addAction("导出为 JSON", self._export_json)
        menu.addSeparator()
        menu.addAction("删除", self._on_delete_clicked)
        menu.exec_(self._session_list.mapToGlobal(pos))
