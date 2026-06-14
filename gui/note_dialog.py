"""
gui/note_dialog.py - 备忘本对话框（独立窗口，自定义标题栏，支持关键词查找）
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLineEdit, QLabel, QWidget, QSizeGrip
)
from PyQt5.QtCore import Qt, QTimer, QSettings, QEvent
from PyQt5.QtGui import QFont, QTextCursor, QTextCharFormat, QColor
from utils.note_manager import read_note, write_note


class NoteDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 独立窗口，不跟随主窗口最小化
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("📝 备忘本")
        self.setMinimumSize(500, 400)
        self.resize(600, 500)
        self.setMouseTracking(True)

        self.is_pinned = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._auto_save)

        self._build_title_bar()
        self._build_text_edit()
        self._build_find_bar()
        self._load_content()
        self._restore_geometry()

        self.highlight_format = QTextCharFormat()
        self.highlight_format.setBackground(QColor(255, 200, 100))
        self.setAttribute(Qt.WA_ShowWithoutActivating)

    def _build_title_bar(self):
        # 设置无边框
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        title_bar = QWidget()
        title_bar.setStyleSheet("background-color: #3C3C46; border-top-left-radius: 8px; border-top-right-radius: 8px;")
        title_bar.setFixedHeight(40)

        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(10, 0, 10, 0)

        icon_label = QLabel("📝")
        icon_label.setStyleSheet("color: white; font-size: 16px;")
        layout.addWidget(icon_label)

        title_label = QLabel("备忘本")
        title_label.setStyleSheet("color: white; font-size: 12px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label, 1)

        self.pin_btn = QPushButton("📌")
        self.pin_btn.setFixedSize(28, 28)
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("窗口置顶")
        self.pin_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                font-size: 14px;
            }
            QPushButton:checked {
                background-color: #FFD966;
                border-radius: 14px;
            }
        """)
        self.pin_btn.clicked.connect(self.toggle_pin)
        layout.addWidget(self.pin_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #E81123;
                border-radius: 4px;
            }
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        # 窗口拖动
        title_bar.mousePressEvent = self._start_move
        title_bar.mouseMoveEvent = self._perform_move
        self._drag_pos = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(title_bar)

        self._central_widget = QWidget()
        self._central_widget.setStyleSheet("background-color: #D8C8A0;")
        self._central_layout = QVBoxLayout(self._central_widget)
        self._central_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.addWidget(self._central_widget)

        # 大小调整角
        size_grip = QSizeGrip(self)
        size_grip.setStyleSheet("QSizeGrip { width: 10px; height: 10px; }")
        self._central_layout.addWidget(size_grip, 0, Qt.AlignBottom | Qt.AlignRight)
    
    _EDGE_MARGIN = 8

    def event(self, e):
        if e.type() == QEvent.MouseButtonPress:
            if e.button() == Qt.LeftButton:
                edge = self._get_edge(e.globalPos())
                if edge is not None:
                    self._drag_edge = edge
                    self._drag_start_pos = e.globalPos()
                    self._drag_start_geo = self.geometry()
                    return True
        elif e.type() == QEvent.MouseMove:
            if hasattr(self, '_drag_edge') and self._drag_edge is not None:
                delta = e.globalPos() - self._drag_start_pos
                geo = self._drag_start_geo
                nx, ny, nw, nh = geo.x(), geo.y(), geo.width(), geo.height()

                if 'left' in self._drag_edge:
                    nx = geo.x() + delta.x()
                    nw = geo.width() - delta.x()
                if 'right' in self._drag_edge:
                    nw = geo.width() + delta.x()
                if 'top' in self._drag_edge:
                    ny = geo.y() + delta.y()
                    nh = geo.height() - delta.y()
                if 'bottom' in self._drag_edge:
                    nh = geo.height() + delta.y()

                if nw < self.minimumWidth():
                    nw = self.minimumWidth()
                    if 'left' in self._drag_edge:
                        nx = geo.x() + geo.width() - nw
                if nh < self.minimumHeight():
                    nh = self.minimumHeight()
                    if 'top' in self._drag_edge:
                        ny = geo.y() + geo.height() - nh

                self.setGeometry(nx, ny, nw, nh)
                return True

            edge = self._get_edge(e.globalPos())
            if edge in ('left', 'right'):
                self.setCursor(Qt.SizeHorCursor)
            elif edge in ('top', 'bottom'):
                self.setCursor(Qt.SizeVerCursor)
            elif edge in ('top_left', 'bottom_right'):
                self.setCursor(Qt.SizeFDiagCursor)
            elif edge in ('top_right', 'bottom_left'):
                self.setCursor(Qt.SizeBDiagCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        elif e.type() == QEvent.MouseButtonRelease:
            self._drag_edge = None
            self._drag_start_pos = None
            self._drag_start_geo = None
        return super().event(e)

    def _get_edge(self, pos):
        rect = self.geometry()
        x, y = pos.x() - rect.x(), pos.y() - rect.y()
        left = x < self._EDGE_MARGIN
        right = x > rect.width() - self._EDGE_MARGIN
        top = y < self._EDGE_MARGIN
        bottom = y > rect.height() - self._EDGE_MARGIN
        if left and top: return 'top_left'
        if right and top: return 'top_right'
        if left and bottom: return 'bottom_left'
        if right and bottom: return 'bottom_right'
        if left: return 'left'
        if right: return 'right'
        if top: return 'top'
        if bottom: return 'bottom'
        return None   
    def _start_move(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def _perform_move(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)

    def _build_text_edit(self):
        self.text_edit = QTextEdit()
        self.text_edit.setFont(QFont("Microsoft YaHei UI", 12))
        self.text_edit.setStyleSheet("background-color: #FDF8E8; color: #2C2C2C; border: none;")
        self.text_edit.textChanged.connect(self.on_text_changed)
        self._central_layout.addWidget(self.text_edit)

    def _build_find_bar(self):
        find_layout = QHBoxLayout()
        find_layout.setContentsMargins(0, 8, 0, 0)

        find_label = QLabel("查找:")
        find_label.setStyleSheet("color: #2C2C2C;")
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("输入关键词")
        self.find_input.setFixedHeight(26)
        self.find_input.setStyleSheet("color: #2C2C2C; background-color: #FDF8E8; border: 1px solid #B8A080; border-radius: 3px; padding: 2px 6px;")
        self.find_btn = QPushButton("高亮")
        self.find_btn.setFixedSize(60, 26)
        self.find_btn.setStyleSheet("color: #2C2C2C; background-color: #E8D8C0; border: 1px solid #B8A080; border-radius: 3px;")
        self.clear_btn = QPushButton("清除")
        self.clear_btn.setFixedSize(60, 26)
        self.clear_btn.setStyleSheet("color: #2C2C2C; background-color: #E8D8C0; border: 1px solid #B8A080; border-radius: 3px;")

        find_layout.addWidget(find_label)
        find_layout.addWidget(self.find_input, 1)
        find_layout.addWidget(self.find_btn)
        find_layout.addWidget(self.clear_btn)

        self._central_layout.addLayout(find_layout)

        self.find_btn.clicked.connect(self.highlight_keyword)
        self.clear_btn.clicked.connect(self.clear_highlight)

    def _load_content(self):
        content = read_note()
        self.text_edit.setPlainText(content)
        self.clear_highlight()

    def on_text_changed(self):
        self._save_timer.start(800)

    def _auto_save(self):
        content = self.text_edit.toPlainText()
        write_note(content)

    def closeEvent(self, event):
        self._auto_save()
        self._save_geometry()
        event.accept()
        
    def toggle_pin(self):
        if self.is_pinned:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            self.is_pinned = False
        else:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.is_pinned = True
        # 不要使用 show()，直接重新设置窗口标志后调用 show() 似乎必须，但可能会激活窗口，使用 setVisible 代替
        self.setVisible(True)
        # 同时可能需要重新设置窗口标志生效，调用 show 是必要的，但会导致激活。暂时保留 show，观察效果

    def _save_geometry(self):
        settings = QSettings("LianxinAI", "NoteDialog")
        settings.setValue("geometry", self.saveGeometry())

    def _restore_geometry(self):
        settings = QSettings("LianxinAI", "NoteDialog")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def refresh_content(self):
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self._load_content)

    def highlight_keyword(self):
        keyword = self.find_input.text().strip()
        if not keyword:
            self.clear_highlight()
            return
        self.clear_highlight()
        doc = self.text_edit.document()
        cursor = QTextCursor(doc)
        while not cursor.isNull() and not cursor.atEnd():
            cursor = doc.find(keyword, cursor)
            if not cursor.isNull():
                cursor.mergeCharFormat(self.highlight_format)

    def clear_highlight(self):
        cursor = QTextCursor(self.text_edit.document())
        cursor.select(QTextCursor.Document)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(253, 248, 232))
        cursor.mergeCharFormat(fmt)