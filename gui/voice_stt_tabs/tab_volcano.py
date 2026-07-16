"""
VolcanoTab：火山引擎语音识别配置选项卡
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QLineEdit, QFrame,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
import webbrowser


class _TestVolcanoThread(QThread):
    """后台线程：测试火山引擎连接"""
    finished = pyqtSignal(bool, str)
    
    def __init__(self, appid: str, token: str, parent=None):
        super().__init__(parent)
        self._appid = appid
        self._token = token
    
    def run(self):
        try:
            import time
            start = time.time()
            
            # 生成测试音频（1秒静音）
            import numpy as np, io, wave
            sample_rate = 16000
            samples = np.zeros(sample_rate, dtype=np.float32)
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sample_rate)
                w.writeframes((samples * 32767).astype(np.int16).tobytes())
            
            from brain.stt_volcano import transcribe
            result = transcribe(buf.getvalue())
            elapsed = time.time() - start
            
            if result and result.strip():
                self.finished.emit(True, f"识别成功 ({elapsed:.2f}s): {result[:30]}")
            else:
                self.finished.emit(False, f"连接成功但未返回结果 ({elapsed:.2f}s)")
        except Exception as e:
            self.finished.emit(False, str(e))


class VolcanoTab(QWidget):
    """火山引擎 STT 配置选项卡"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = {}
        self._test_thread = None
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # ── 标题和徽章 ──
        header = QHBoxLayout()
        
        title = QLabel("☁️ 火山引擎 一句话识别")
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        title.setStyleSheet("color: #3498DB;")
        header.addWidget(title)
        
        badge = QLabel("云端 · 高精度")
        badge.setFont(QFont("Microsoft YaHei UI", 8))
        badge.setStyleSheet("""
            background-color: #3498DB;
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
        """)
        header.addWidget(badge)
        header.addStretch()
        layout.addLayout(header)
        
        # ── 描述 ──
        desc = QLabel(
            "<b>字节跳动火山引擎</b> 语音识别服务<br><br>"
            "✅ <b>优势：</b><br>"
            "• 识别准确率极高（业界领先）<br>"
            "• 免费额度：20,000次/半年<br>"
            "• 支持中英文混合识别<br>"
            "• 适合嘈杂环境<br><br>"
            "💰 <b>费用：</b><br>"
            "• 新用户免费 20,000 次（半年有效期）<br>"
            "• 超出后 ¥1~4.5/小时"
        )
        desc.setWordWrap(True)
        desc.setFont(QFont("Microsoft YaHei UI", 9))
        desc.setStyleSheet("color: #B0B0C0; padding: 8px; line-height: 1.5;")
        desc.setTextFormat(Qt.RichText)
        layout.addWidget(desc)
        
        # ── 启用开关 ──
        enable_row = QHBoxLayout()
        self._enable_cb = QCheckBox("启用此引擎")
        self._enable_cb.setChecked(False)
        self._enable_cb.setFont(QFont("Microsoft YaHei UI", 9))
        self._enable_cb.setStyleSheet("color: #E0E0E0;")
        enable_row.addWidget(self._enable_cb)
        enable_row.addStretch()
        layout.addLayout(enable_row)
        
        # ── 配置表单 ──
        form_frame = QFrame()
        form_frame.setStyleSheet("""
            QFrame {
                background-color: #252538;
                border-radius: 6px;
                padding: 4px;
            }
            QLabel { color: #E0E0E0; background: transparent; }
            QLineEdit { 
                color: #E0E0E0; 
                background: #1E1E30; 
                border: 1px solid #3D3D5A;
                border-radius: 4px;
                padding: 6px 8px;
            }
            QLineEdit:focus { border: 1px solid #6C7BFF; }
        """)
        form_layout = QVBoxLayout(form_frame)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(12, 12, 12, 12)
        
        # AppID
        appid_row = QHBoxLayout()
        appid_label = QLabel("App ID:")
        appid_label.setFont(QFont("Microsoft YaHei UI", 9))
        appid_label.setFixedWidth(90)
        appid_row.addWidget(appid_label)
        
        self._appid_edit = QLineEdit()
        self._appid_edit.setPlaceholderText("如 6062204577")
        appid_row.addWidget(self._appid_edit)
        form_layout.addLayout(appid_row)
        
        # Access Token
        token_row = QHBoxLayout()
        token_label = QLabel("Access Token:")
        token_label.setFont(QFont("Microsoft YaHei UI", 9))
        token_label.setFixedWidth(90)
        token_row.addWidget(token_label)
        
        self._token_edit = QLineEdit()
        self._token_edit.setPlaceholderText("应用级令牌")
        self._token_edit.setEchoMode(QLineEdit.Password)
        token_row.addWidget(self._token_edit)
        
        show_btn = QPushButton("显示")
        show_btn.setFixedSize(50, 28)
        show_btn.setCheckable(True)
        show_btn.setCursor(Qt.PointingHandCursor)
        show_btn.setFont(QFont("Microsoft YaHei UI", 8))
        show_btn.setStyleSheet("""
            QPushButton {
                background-color: #ECEEFF;
                color: #5060DD;
                border-radius: 4px;
                border: 1px solid #C8CCEE;
            }
            QPushButton:checked {
                background-color: #5060DD;
                color: white;
            }
            QPushButton:hover { background-color: #DDE0FF; }
        """)
        show_btn.toggled.connect(
            lambda checked: self._token_edit.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        token_row.addWidget(show_btn)
        form_layout.addLayout(token_row)
        
        layout.addWidget(form_frame)
        
        # ── 状态显示 ──
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setFont(QFont("Microsoft YaHei UI", 9))
        self._status_label.setStyleSheet("color: #888; padding: 8px;")
        layout.addWidget(self._status_label)
        
        # ── 操作按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        
        get_quota_btn = QPushButton("🎁 获取免费额度")
        get_quota_btn.setFixedHeight(30)
        get_quota_btn.setFont(QFont("Microsoft YaHei UI", 9))
        get_quota_btn.setCursor(Qt.PointingHandCursor)
        get_quota_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D3F;
                color: #E0E0E0;
                border: 1px solid #3D3D5A;
                border-radius: 6px;
                padding: 0 12px;
            }
            QPushButton:hover { background-color: #3D3D55; }
        """)
        get_quota_btn.clicked.connect(
            lambda: webbrowser.open("https://console.volcengine.com/asr")
        )
        btn_row.addWidget(get_quota_btn)
        
        test_btn = QPushButton("🔗 测试连接")
        test_btn.setFixedHeight(30)
        test_btn.setFont(QFont("Microsoft YaHei UI", 9))
        test_btn.setCursor(Qt.PointingHandCursor)
        test_btn.setStyleSheet("""
            QPushButton {
                background-color: #6C7BFF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 12px;
            }
            QPushButton:hover { background-color: #5A6AEE; }
        """)
        test_btn.clicked.connect(self._on_test)
        btn_row.addWidget(test_btn)
        
        layout.addLayout(btn_row)
        
        # ── 使用指南 ──
        guide = QLabel(
            "💡 <b>配置步骤：</b><br>"
            "1. 访问 <a href='https://console.volcengine.com/asr'>火山引擎控制台</a><br>"
            "2. 注册/登录账号，进入语音技术页面<br>"
            "3. 创建应用，获取 AppID 和 Access Token<br>"
            "4. 将信息填入上方输入框<br>"
            "5. 点击「测试连接」验证配置<br><br>"
            "⚠️ 注意：Access Token 是应用级令牌，不是账号密码！"
        )
        guide.setOpenExternalLinks(True)
        guide.setWordWrap(True)
        guide.setFont(QFont("Microsoft YaHei UI", 8))
        guide.setStyleSheet("color: #888; padding: 8px; line-height: 1.4;")
        guide.setTextFormat(Qt.RichText)
        layout.addWidget(guide)
        
        layout.addStretch()
    
    def load_config(self, config: dict):
        """加载配置"""
        self._config = config.copy()
        self._enable_cb.setChecked(config.get("enabled", False))
        self._appid_edit.setText(config.get("appid", ""))
        self._token_edit.setText(config.get("access_token", ""))
    
    def collect_config(self) -> dict:
        """收集配置"""
        return {
            "enabled": self._enable_cb.isChecked(),
            "appid": self._appid_edit.text().strip(),
            "access_token": self._token_edit.text().strip(),
        }
    
    def _on_test(self):
        """测试连接"""
        appid = self._appid_edit.text().strip()
        token = self._token_edit.text().strip()
        
        if not appid or not token:
            self._status_label.setText("⚠️ 请先填写 AppID 和 Access Token")
            self._status_label.setStyleSheet("color: #FFA500; padding: 8px;")
            return
        
        self._status_label.setText("正在测试连接...")
        self._status_label.setStyleSheet("color: #FFA500; padding: 8px;")
        
        self._test_thread = _TestVolcanoThread(appid, token, self)
        self._test_thread.finished.connect(self._on_test_finished)
        self._test_thread.start()
    
    def _on_test_finished(self, success: bool, msg: str):
        """测试完成回调"""
        if success:
            self._status_label.setText(f"✅ {msg}")
            self._status_label.setStyleSheet("color: #27AE60; padding: 8px;")
        else:
            self._status_label.setText(f"❌ 测试失败: {msg}")
            self._status_label.setStyleSheet("color: #E74C3C; padding: 8px;")