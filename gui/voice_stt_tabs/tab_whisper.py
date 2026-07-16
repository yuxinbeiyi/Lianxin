"""
WhisperTab：Whisper 开源语音识别配置选项卡
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QFrame,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont


class _TestWhisperThread(QThread):
    """后台线程：测试 Whisper 识别"""
    finished = pyqtSignal(bool, str, float)
    
    def __init__(self, model_size: str, language: str, device: str, parent=None):
        super().__init__(parent)
        self._model_size = model_size
        self._language = language
        self._device = device
    
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
            
            # 尝试导入 whisper
            try:
                import whisper
                model = whisper.load_model(self._model_size, device=self._device)
                result = model.transcribe(buf.getvalue(), language=self._language)
                text = result.get("text", "")
                elapsed = time.time() - start
                
                success = True
                self.finished.emit(success, text.strip(), elapsed)
            except ImportError:
                self.finished.emit(False, "whisper 库未安装 (pip install openai-whisper)", 0)
            except Exception as e:
                self.finished.emit(False, str(e), 0)
        except Exception as e:
            self.finished.emit(False, str(e), 0)


class WhisperTab(QWidget):
    """Whisper 引擎配置选项卡"""
    
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
        
        title = QLabel("🔧 Whisper 开源模型")
        title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        title.setStyleSheet("color: #E67E22;")
        header.addWidget(title)
        
        badge = QLabel("开源 · 多语言")
        badge.setFont(QFont("Microsoft YaHei UI", 8))
        badge.setStyleSheet("""
            background-color: #E67E22;
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
        """)
        header.addWidget(badge)
        header.addStretch()
        layout.addLayout(header)
        
        # ── 描述 ──
        desc = QLabel(
            "<b>OpenAI Whisper</b> 多语言语音识别模型<br><br>"
            "✅ <b>优势：</b><br>"
            "• 完全开源免费<br>"
            "• 支持 99+ 种语言<br>"
            "• 社区活跃，持续更新<br>"
            "• 可离线使用<br><br>"
            "⚠️ <b>特点：</b><br>"
            "• 模型较大（base: 142MB, large: 3GB）<br>"
            "• CPU 推理速度较慢<br>"
            "• 中文效果略逊于 FunASR"
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
            QComboBox { 
                color: #E0E0E0; 
                background: #1E1E30; 
                border: 1px solid #3D3D5A;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: none; border: none; }
            QComboBox QAbstractItemView {
                background: #1E1E30;
                color: #E0E0E0;
                selection-background-color: #6C7BFF;
            }
        """)
        form_layout = QVBoxLayout(form_frame)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(12, 12, 12, 12)
        
        # 模型大小
        model_row = QHBoxLayout()
        model_label = QLabel("模型大小:")
        model_label.setFont(QFont("Microsoft YaHei UI", 9))
        model_label.setFixedWidth(80)
        model_row.addWidget(model_label)
        
        self._model_combo = QComboBox()
        self._model_combo.addItem("tiny (75MB) — 最快", "tiny")
        self._model_combo.addItem("base (142MB) — 平衡 ✅", "base")
        self._model_combo.addItem("small (466MB) — 更准", "small")
        self._model_combo.addItem("medium (1.5GB) — 高精度", "medium")
        self._model_combo.addItem("large (3GB) — 最高精度", "large")
        model_row.addWidget(self._model_combo)
        form_layout.addLayout(model_row)
        
        # 语言
        lang_row = QHBoxLayout()
        lang_label = QLabel("语言代码:")
        lang_label.setFont(QFont("Microsoft YaHei UI", 9))
        lang_label.setFixedWidth(80)
        lang_row.addWidget(lang_label)
        
        self._lang_combo = QComboBox()
        self._lang_combo.addItem("中文 (zh)", "zh")
        self._lang_combo.addItem("英文 (en)", "en")
        self._lang_combo.addItem("日文 (ja)", "ja")
        self._lang_combo.addItem("韩文 (ko)", "ko")
        self._lang_combo.addItem("自动检测", None)
        lang_row.addWidget(self._lang_combo)
        form_layout.addLayout(lang_row)
        
        # 设备
        device_row = QHBoxLayout()
        device_label = QLabel("推理设备:")
        device_label.setFont(QFont("Microsoft YaHei UI", 9))
        device_label.setFixedWidth(80)
        device_row.addWidget(device_label)
        
        self._device_combo = QComboBox()
        self._device_combo.addItem("🤖 自动检测", "auto")
        self._device_combo.addItem("🎮 GPU (CUDA)", "cuda")
        self._device_combo.addItem("💻 CPU", "cpu")
        device_row.addWidget(self._device_combo)
        form_layout.addLayout(device_row)
        
        layout.addWidget(form_frame)
        
        # ── 模型说明 ──
        info_frame = QFrame()
        info_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                border: 1px solid #3D3D5A;
                border-radius: 6px;
            }
            QLabel { color: #B0B0C0; background: transparent; }
        """)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 8, 10, 8)
        
        info_title = QLabel("📊 模型对比：")
        info_title.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
        info_layout.addWidget(info_title)
        
        info_text = QLabel(
            "• <b>tiny</b>: 75MB | 最快速度 | 一般准确率<br>"
            "• <b>base</b>: 142MB | 平衡之选 ✅ 推荐<br>"
            "• <b>small</b>: 466MB | 更高准确率<br>"
            "• <b>medium</b>: 1.5GB | 高精度（需大量内存）<br>"
            "• <b>large</b>: 3GB | 最高精度（需大量显存）<br><br>"
            "💡 <b>提示：</b>首次使用时会自动下载模型文件"
        )
        info_text.setWordWrap(True)
        info_text.setFont(QFont("Microsoft YaHei UI", 8))
        info_text.setTextFormat(Qt.RichText)
        info_layout.addWidget(info_text)
        
        layout.addWidget(info_frame)
        
        # ── 状态显示 ──
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setFont(QFont("Microsoft YaHei UI", 9))
        self._status_label.setStyleSheet("color: #888; padding: 8px;")
        layout.addWidget(self._status_label)
        
        # ── 操作按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        
        install_btn = QPushButton("📦 安装 Whisper")
        install_btn.setFixedHeight(30)
        install_btn.setFont(QFont("Microsoft YaHei UI", 9))
        install_btn.setCursor(Qt.PointingHandCursor)
        install_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D3F;
                color: #E0E0E0;
                border: 1px solid #3D3D5A;
                border-radius: 6px;
                padding: 0 12px;
            }
            QPushButton:hover { background-color: #3D3D55; }
        """)
        install_btn.clicked.connect(self._on_install_whisper)
        btn_row.addWidget(install_btn)
        
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
            "💡 <b>使用指南：</b><br><br>"
            "<b>模型选择建议：</b><br>"
            "• 追求速度 → tiny 或 base<br>"
            "• 追求准确 → medium 或 large<br>"
            "• 推荐新手使用 base<br><br>"
            "<b>设备选择：</b><br>"
            "• auto = 自动检测（有CUDA则用GPU）<br>"
            "• cuda = 强制使用GPU<br>"
            "• cpu = 强制使用CPU（显存不足时选这个）<br><br>"
            "⚠️ 注意：large 模型需要至少 10GB 内存/显存"
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
        
        model = config.get("model_size", "base")
        idx = self._model_combo.findData(model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        
        lang = config.get("language", "zh")
        idx = self._lang_combo.findData(lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        
        device = config.get("device", "auto")
        idx = self._device_combo.findData(device)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)
    
    def collect_config(self) -> dict:
        """收集配置"""
        return {
            "enabled": self._enable_cb.isChecked(),
            "model_size": self._model_combo.currentData() or "base",
            "language": self._lang_combo.currentData() or "zh",
            "device": self._device_combo.currentData() or "auto",
        }
    
    def _on_install_whisper(self):
        """安装 Whisper"""
        from PyQt5.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "安装 Whisper",
            "即将安装 OpenAI Whisper 及其依赖。<br><br>"
            "这将执行命令：<br>"
            "<code>pip install openai-whisper</code><br><br"
            "是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.Yes:
            self._status_label.setText("正在安装，请稍候...")
            self._status_label.setStyleSheet("color: #FFA500; padding: 8px;")
            
            import subprocess, sys
            installer = QThread(
                target=lambda: subprocess.run(
                    [sys.executable, "-m", "pip", "install", "openai-whisper"],
                    capture_output=True,
                    timeout=300
                )
            )
            installer.finished.connect(
                lambda: self._on_install_finished(installer)
            )
            installer.start()
    
    def _on_install_finished(self, thread: QThread):
        """安装完成回调"""
        try:
            result = thread.result() if hasattr(thread, 'result') else None
            if result and result.returncode == 0:
                self._status_label.setText("✅ Whisper 安装成功！")
                self._status_label.setStyleSheet("color: #27AE60; padding: 8px;")
            else:
                error = result.stderr.decode() if result and result.stderr else "未知错误"
                self._status_label.setText(f"❌ 安装失败: {error[:100]}")
                self._status_label.setStyleSheet("color: #E74C3C; padding: 8px;")
        except Exception as e:
            self._status_label.setText(f"❌ 安装异常: {e}")
            self._status_label.setStyleSheet("color: #E74C3C; padding: 8px;")
    
    def _on_test(self):
        """测试识别"""
        self._status_label.setText("正在测试（首次会下载模型）...")
        self._status_label.setStyleSheet("color: #FFA500; padding: 8px;")
        
        model_size = self._model_combo.currentData() or "base"
        language = self._lang_combo.currentData() or "zh"
        device = self._device_combo.currentData() or "auto"
        
        self._test_thread = _TestWhisperThread(
            model_size, language, device, self
        )
        self._test_thread.finished.connect(self._on_test_finished)
        self._test_thread.start()
    
    def _on_test_finished(self, success: bool, text: str, elapsed: float):
        """测试完成回调"""
        if success:
            display_text = text if text else "(静音)"
            self._status_label.setText(
                f"✅ 识别成功\n"
                f"   结果: {display_text[:50]}{'...' if len(display_text) > 50 else ''}\n"
                f"   耗时: {elapsed:.2f}s"
            )
            self._status_label.setStyleSheet("color: #27AE60; padding: 8px;")
        else:
            self._status_label.setText(f"❌ 测试失败: {text}")
            self._status_label.setStyleSheet("color: #E74C3C; padding: 8px;")