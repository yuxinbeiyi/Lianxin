"""
MusicListDialog：音乐列表对话框
显示当前播放列表，双击曲目即可切换播放，支持拖拽排序
"""

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal
from pathlib import Path


class MusicListDialog(QDialog):
    track_selected = pyqtSignal(int)     # 发出选中的曲目索引
    order_changed = pyqtSignal(list)     # 当顺序被拖拽改变时，发出新顺序（Path列表）

    def __init__(self, playlist, current_index, parent=None):
        super().__init__(parent)
        self.setWindowTitle("音乐列表")
        self.setMinimumSize(300, 400)
        self.resize(350, 450)
        self.setWindowFlags(Qt.Window)

        # 设置背景图片
        bg_path = Path(__file__).parent.parent / "assets" / "音乐列表.jpg"
        if bg_path.exists():
            self.setStyleSheet(f"""
                QDialog {{
                    background-image: url("{bg_path.as_posix()}");
                    background-position: center;
                    background-repeat: no-repeat;
                    background-attachment: fixed;
                }}
                QListWidget {{
                    background-color: rgba(255, 255, 255, 220);
                    border-radius: 10px;
                    border: none;
                }}
                QListWidget::item {{
                    padding: 10px 10px;
                    border-radius: 4px;
                    color: #1a1a1a;
                }}
                QListWidget::item:selected {{
                    background-color: rgba(255, 235, 140, 0.9);
                    color: #8B4513;
                }}
                QListWidget::item:hover:!selected {{
                    background-color: rgba(255, 248, 220, 0.8);
                }}
                QScrollBar:vertical {{
                    background-color: rgba(222, 184, 135, 0.3);
                    width: 10px;
                    border-radius: 5px;
                }}
                QScrollBar::handle:vertical {{
                    background-color: #8B4513;
                    border-radius: 5px;
                    min-height: 20px;
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                    height: 0px;
                }}

                QPushButton {{
                    background-color: rgba(240,240,240,200);
                    border-radius: 5px;
                    padding: 5px;
                    color: #1a1a1a;
                }}
            """)
        else:
            self.setStyleSheet("""
                QListWidget::item { padding: 6px; }
                QListWidget::item:selected { background-color: #6C7BFF; color: white; }
            """)

        layout = QVBoxLayout(self)

        # 提示：拖动排序
        hint_label = QLabel("💡 拖动排序")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setStyleSheet("color: #8B5A2B; font-size: 9pt; font-weight: bold; background: transparent; margin-bottom: 4px;")
        layout.addWidget(hint_label)

        # 歌曲列表（启用拖拽排序）
        self.list_widget = QListWidget()
        self.list_widget.setSpacing(6)  # 项目间距，用代码方式确保始终生效
        self.list_widget.setDragEnabled(True)
        self.list_widget.setAcceptDrops(True)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)

        # 填充列表
        self._playlist = playlist  # 保存原始路径列表
        self._current_index = current_index
        self._update_list_items()
        self.list_widget.setCurrentRow(current_index)  # 高亮当前播放的歌曲

        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        layout.addWidget(self.list_widget)

        # 底部关闭按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _update_list_items(self):
        """根据 self._playlist 刷新列表显示"""
        self.list_widget.clear()
        for i, path in enumerate(self._playlist):
            label = f"♫ {path.stem}" if i == self._current_index else f"   {path.stem}"
            item = QListWidgetItem(label)
            if i == self._current_index:
                item.setForeground(Qt.green)
            self.list_widget.addItem(item)

    def _on_rows_moved(self, parent, start, end, dest, row):
        """当用户拖拽改变顺序时，更新内部的 playlist 并发出信号"""
        new_order = []
        for i in range(self.list_widget.count()):
            item_text = self.list_widget.item(i).text()
            # 去除 ♫ 和空格后再匹配
            clean_text = item_text.strip().removeprefix('♫ ').removeprefix('   ')
            # 在原始 _playlist 中查找匹配的路径（通过 stem 匹配）
            found = None
            for p in self._playlist:
                if p.stem == clean_text:
                    found = p
                    break
            if found:
                new_order.append(found)
        if new_order and new_order != self._playlist:
            self._playlist = new_order
            # 更新当前播放歌曲的索引（因为位置可能变了）
            old_path = self._playlist[self._current_index] if self._current_index < len(self._playlist) else None
            if old_path:
                for new_idx, p in enumerate(self._playlist):
                    if p == old_path:
                        self._current_index = new_idx
                        break
            # 重新构建所有 item 确保显示正确
            self._update_list_items()
            self.order_changed.emit(new_order)

    def on_item_double_clicked(self, item):
        index = self.list_widget.row(item)
        self.track_selected.emit(index)
        self.accept()