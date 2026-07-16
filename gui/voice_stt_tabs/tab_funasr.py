"""
FunASRTab：FunASR 本地语音识别配置选项卡
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QFrame, QProgressBar,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont


class _CheckModelThread(QThread):
    """后台线程：检查 FunASR 模型状态"""
    finished = pyqtSignal(dict)
    
    def run(self):
        result = {"loaded": False, "device": "", "reason": ""}
        try:
            from brain.stt_funasr import check_model_status
            result = check_model_status()
        except Exception as e:
            result["reason"] = str(e)
        self.finished.emit(result)


class _DownloadModelThread(QThread):
    """后台线程：下载/更新 FunASR 模型"""
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)
    
    def run(self):
        try:
            from brain.stt_funasr import download_model
            for pct in download_model():
                self.progress.emit(pct)
            self.finished.emit(True, "模型下载完成")
        except Exception as e:
            self.finished.emit(False, str(e))


class _TestRecognizeThread(QThread):
    """后台线程：测试 FunASR 识别"""
    finished = pyqtSignal(bool, str, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._audio_data = None
    
    def set_audio(self, audio_bytes: bytes):
        self._audio_data = audio_bytes
    
    def run(self):
        try:
            import time
            start = time.time()
            
            if not self._audio_data:
                # 生成测试音频（1秒静音）
                import numpy as np
                sample_rate = 16000
                samples = np.zeros(sample_rate, dtype=np.float32)
                import io, wave
                buf = io.BytesIO()
                with wave.open(buf, 'wb') as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(sample_rate)
                    w.writeframes((samples * 32767).astype(np.int16).tobytes())
                self._audio_data = buf.getvalue()
            
            from brain.stt_funasr import transcribe
            result = transcribe(self._audio_data)
            elapsed = time.time() - start
            
            success = bool(result and result.strip())
            self.finished.emit(success, result or "", elapsed)
        except Exception as e:
            self.finished.emit(False, str(e), 0)


class FunASRTab(QWidget):
    """FunASR 引擎配置选项卡"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = {}
        self._check_thread = None
        self._download_thread = None
        self._test_thread = None
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        
        # ── 标题和徽章 ──
        header = QHBoxLayout()
        
        title = QLabel("🟢 FunASR 本地识别")
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        title.setStyleSheet("color: #27AE60;")
        header.addWidget(title)
        
        badge = QLabel("推荐 · 免费")
        badge.setFont(QFont("Microsoft YaHei UI", 8))
        badge.setStyleSheet("""
            background-color: #27AE60;
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
        """)
        header.addWidget(badge)
        header.addStretch()
        layout.addLayout(header)
        
        # ── 描述 ──
        desc = QLabel(
            "<b>SenseVoice-Small</b> 中文语音识别模型<br><br>"
            "✅ <b>优势：</b><br>"
            "• 完全免费，无限次使用<br>"
            "• 本地推理，无需网络<br>"
            "• 低延迟（&lt;500ms）<br>"
            "• 中文识别准确率极高<br><br>"
            "⚠️ <b>要求：</b><br>"
            "• 首次使用需下载模型（约200MB）<br>"
            "• 推荐使用 NVIDIA GPU 加速<br>"
            "• CPU 模式也可用但速度较慢"
        )
        desc.setWordWrap(True)
        desc.setFont(QFont("Microsoft YaHei UI", 9))
        desc.setStyleSheet("color: #B0B0C0; padding: 8px; line-height: 1.5;")
        desc.setTextFormat(Qt.RichText)
        layout.addWidget(desc)
        
        # ── 启用开关 ──
        enable_row = QHBoxLayout()
        self._enable_cb = QCheckBox("启用此引擎")
        self._enable_cb.setChecked(True)
        self._enable_cb.setFont(QFont("Microsoft YaHei UI", 9))
        self._enable_cb.setStyleSheet("color: #E0E0E0;")
        enable_row.addWidget(self._enable_cb)
        enable_row.addStretch()
        layout.addLayout(enable_row)
        
        # ── 设备选择 ──
        device_frame = QFrame()
        device_frame.setStyleSheet("""
            QFrame {
                background-color: #252538;
                border-radius: 6px;
                padding: 4px;
            }
            QLabel { color: #E0E0E0; background: transparent; }
            QComboBox { 
                color: #E0E0E0; 
                background: #1E1E30; 
                border: 1px solid #3D3D5A;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)
        device_layout = QHBoxLayout(device_frame)
        device_layout.setContentsMargins(8, 6, 8, 6)
        
        device_label = QLabel("推理设备:")
        device_label.setFont(QFont("Microsoft YaHei UI", 9))
        device_layout.addWidget(device_label)
        
        self._device_combo = QComboBox()
        self._device_combo.addItem("🤖 自动检测", "auto")
        self._device_combo.addItem("🎮 GPU (CUDA)", "cuda")
        self._device_combo.addItem("💻 CPU", "cpu")
        device_layout.addWidget(self._device_combo)
        device_layout.addStretch()
        layout.addWidget(device_frame)
        
        # ── 状态显示区 ──
        status_frame = QFrame()
        status_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                border: 1px solid #3D3D5A;
                border-radius: 6px;
            }
            QLabel { color: #E0E0E0; background: transparent; }
        """)
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(10, 8, 10, 8)
        
        status_header = QHBoxLayout()
        status_title = QLabel("模型状态:")
        status_title.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        status_header.addWidget(status_title)
        status_header.addStretch()
        status_layout.addLayout(status_header)
        
        self._status_label = QLabel("点击「检查状态」查看...")
        self._status_label.setFont(QFont("Microsoft YaHei UI", 9))
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #888; padding: 4px;")
        status_layout.addWidget(self._status_label)
        
        # 进度条（下载时显示）
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setFixedHeight(20)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #2D2D3F;
                border: none;
                border-radius: 10px;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #6C7BFF;
                border-radius: 10px;
            }
        """)
        status_layout.addWidget(self._progress_bar)
        
        layout.addWidget(status_frame)
        
        # ── 操作按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        
        check_btn = QPushButton("🔍 检查状态")
        check_btn.setFixedHeight(30)
        check_btn.setFont(QFont("Microsoft YaHei UI", 9))
        check_btn.setCursor(Qt.PointingHandCursor)
        check_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D3F;
                color: #E0E0E0;
                border: 1px solid #3D3D5A;
                border-radius: 6px;
                padding: 0 12px;
            }
            QPushButton:hover { background-color: #3D3D55; }
        """)
        check_btn.clicked.connect(self._on_check_model)
        btn_row.addWidget(check_btn)
        
        download_btn = QPushButton("⬇️ 下载/更新模型")
        download_btn.setFixedHeight(30)
        download_btn.setFont(QFont("Microsoft YaHei UI", 9))
        download_btn.setCursor(Qt.PointingHandCursor)
        download_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D3F;
                color: #E0E0E0;
                border: 1px solid #3D3D5A;
                border-radius: 6px;
                padding: 0 12px;
            }
            QPushButton:hover { background-color: #3D3D55; }
        """)
        download_btn.clicked.connect(self._on_download_model)
        btn_row.addWidget(download_btn)
        
        test_btn = QPushButton("🎤 测试识别")
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
            "💡 <b>使用指南：</b><br>"
            "1. 点击「检查状态」确认已安装<br>"
            "2. 如未安装，点击「下载模型」（约200MB）<br>"
            "3. 首次使用时会自动加载，请耐心等待<br>"
            "4. 推荐开启 GPU 加速以获得最佳性能"
        )
        guide.setWordWrap(True)
        guide.setFont(QFont("Microsoft YaHei UI", 8))
        guide.setStyleSheet("color: #888; padding: 8px; line-height: 1.4;")
        guide.setTextFormat(Qt.RichText)
        layout.addWidget(guide)
        
        layout.addStretch()
    
    def load_config(self, config: dict):
        """加载配置"""
        self._config = config.copy()
        self._enable_cb.setChecked(config.get("enabled", True))
        
        device = config.get("device", "auto")
        idx = self._device_combo.findData(device)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)
    
    def collect_config(self) -> dict:
        """收集配置"""
        return {
            "enabled": self._enable_cb.isChecked(),
            "device": self._device_combo.currentData() or "auto",
            "model_path": self._config.get("model_path", ""),
        }
    
    def _on_check_model(self):
        """检查模型状态"""
        self._status_label.setText("正在检查...")
        self._status_label.setStyleSheet("color: #FFA500; padding: 4px;")
        
        self._check_thread = _CheckModelThread(self)
        self._check_thread.finished.connect(self._on_check_finished)
        self._check_thread.start()
    
    def _on_check_finished(self, result: dict):
        """检查完成回调"""
        loaded = result.get("loaded", False)
        device = result.get("device", "")
        reason = result.get("reason", "")
        
        if loaded:
            emoji = "✅"
            color = "#27AE60"
            text = f"{emoji} 模型已就绪\n"
            if device:
                text += f"   设备: {device}"
        else:
            emoji = "❌"
            color = "#E74C3C"
            text = f"{emoji} 模型未就绪\n"
            if reason:
                text += f"   原因: {reason}"
            else:
                text += "   请点击「下载/更新模型」"
        
        self._status_label.setText(text)
        self._status_label.setStyleSheet(f"color: {color}; padding: 4px;")
    
    def _on_download_model(self):
        """下载模型"""
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._status_label.setText("正在下载模型...")
        self._status_label.setStyleSheet("color: #FFA500; padding: 4px;")
        
        self._download_thread = _DownloadModelThread(self)
        self._download_thread.progress.connect(
            lambda v: self._progress_bar.setValue(v)
        )
        self._download_thread.finished.connect(self._on_download_finished)
        self._download_thread.start()
    
    def _on_download_finished(self, success: bool, msg: str):
        """下载完成回调"""
        self._progress_bar.setVisible(False)
        
        if success:
            self._status_label.setText(f"✅ {msg}")
            self._status_label.setStyleSheet("color: #27AE60; padding: 4px;")
        else:
            self._status_label.setText(f"❌ 下载失败: {msg}")
            self._status_label.setStyleSheet("color: #E74C3C; padding: 4px;")
    
    def _on_test(self):
        """测试识别"""
        self._status_label.setText("正在测试识别...")
        self._status_label.setStyleSheet("color: #FFA500; padding: 4px;")
        
        self._test_thread = _TestRecognizeThread(self)
        self._test_thread.finished.connect(self._on_test_finished)
        self._test_thread.start()
    
    def _on_test_finished(self, success: bool, text: str, elapsed: float):
        """测试完成回调"""
        if success:
            self._status_label.setText(
                f"✅ 识别成功\n"
                f"   结果: {text[:50]}{'...' if len(text) > 50 else ''}\n"
                f"   耗时: {elapsed:.2f}s"
            )
            self._status_label.setStyleSheet("color: #27AE60; padding: 4px;")
        else:
            self._status_label.setText(f"❌ 识别失败: {text}")
            self._status_label.setStyleSheet("color: #E74C3C; padding: 4px;")