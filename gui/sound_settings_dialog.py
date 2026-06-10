# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton,
    QScrollArea, QFrame, QComboBox, QLineEdit, QCheckBox, QDialogButtonBox,
    QWidget
)

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from utils.settings import get_settings
from config import get_tts_config, save_tts_config
from .settings_dialog import SettingsDialog


class SoundSettingsDialog(QDialog):
    """声音设置独立对话框（包含音量、音效、TTS引擎、语音合成参数）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = get_settings()
        self._tts_cfg = get_tts_config()

        self.setWindowTitle("🔊 声音设置")
        self.setMinimumSize(500, 620)
        self.resize(520, 660)
        self.setModal(True)
        self.setStyleSheet("background-color: #F8F8FC;")
        self._build_ui()
        self._load_from_settings()

    def _create_frame(self):
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #F0F2F7;
                border-radius: 8px;
                border: 1px solid #E0E0E8;
            }
        """)
        return frame

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        # 标题
        title = QLabel("🔊 声音设置")
        title.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        title.setStyleSheet("color: #3A3A5C;")
        layout.addWidget(title)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #E0E0E8; max-height: 1px;")
        layout.addWidget(line)

        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(14)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        # TTS 音量
        tts_frame = self._create_frame()
        tts_vbox = QVBoxLayout(tts_frame)
        tts_vbox.addWidget(QLabel("🗣️ 莲心语音音量"))
        self.tts_slider = QSlider(Qt.Horizontal)
        self.tts_slider.setRange(0, 100)
        self.tts_slider.setValue(int(self._settings.tts_volume * 100))
        self.tts_slider.valueChanged.connect(self._on_tts_volume_changed)
        tts_vbox.addWidget(self.tts_slider)
        scroll_layout.addWidget(tts_frame)

        # 音效音量
        sfx_frame = self._create_frame()
        sfx_vbox = QVBoxLayout(sfx_frame)
        sfx_vbox.addWidget(QLabel("🔊 按键/反馈音效音量"))
        self.sfx_slider = QSlider(Qt.Horizontal)
        self.sfx_slider.setRange(0, 100)
        self.sfx_slider.setValue(int(self._settings.sfx_volume * 100))
        self.sfx_slider.valueChanged.connect(self._on_sfx_volume_changed)
        sfx_vbox.addWidget(self.sfx_slider)
        scroll_layout.addWidget(sfx_frame)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #D8D8E8; max-height: 1px;")
        scroll_layout.addWidget(sep)

        # 引擎选择
        engine_frame = self._create_frame()
        engine_vbox = QVBoxLayout(engine_frame)
        engine_vbox.setSpacing(6)
        engine_title = QLabel("TTS 引擎")
        engine_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        engine_vbox.addWidget(engine_title)

        self._tts_engine_combo = QComboBox()
        self._tts_engine_combo.addItems([
            "auto — 优先 GPT-SoVITS（不可用则回退 Edge-TTS）",
            "edge_tts — 仅使用 Edge-TTS（云端标准发音）",
        ])
        engine_vbox.addWidget(self._tts_engine_combo)
        engine_desc = QLabel(
            "GPT-SoVits 需要安装并配置路径后方可使用。\n"
            "Edge-TTS 无需安装，配置后即可使用。"
        )
        engine_desc.setWordWrap(True)
        engine_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        engine_vbox.addWidget(engine_desc)
        scroll_layout.addWidget(engine_frame)

        # GPT-SoVits 路径
        gs_frame = self._create_frame()
        gs_vbox = QVBoxLayout(gs_frame)
        gs_vbox.setSpacing(6)
        gs_title = QLabel("GPT-SoVITS 安装路径")
        gs_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        gs_vbox.addWidget(gs_title)

        gs_row = QHBoxLayout()
        self._tts_gs_path_edit = QLineEdit()
        self._tts_gs_path_edit.setPlaceholderText("例如: C:\\GPT-SoVITS-v2pro")
        gs_row.addWidget(self._tts_gs_path_edit)
        gs_browse_btn = QPushButton("浏览…")
        gs_browse_btn.setFixedWidth(80)
        gs_browse_btn.clicked.connect(self._browse_gs_path)
        gs_row.addWidget(gs_browse_btn)
        gs_vbox.addLayout(gs_row)

        self._tts_gs_status = QLabel()
        self._tts_gs_status.setStyleSheet("color: #888; font-size: 11px; padding: 2px 0;")
        gs_vbox.addWidget(self._tts_gs_status)
        scroll_layout.addWidget(gs_frame)

        # 默认情绪
        mood_frame = self._create_frame()
        mood_vbox = QVBoxLayout(mood_frame)
        mood_vbox.setSpacing(6)
        mood_title = QLabel("默认语音情绪")
        mood_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        mood_vbox.addWidget(mood_title)

        self._tts_mood_combo = QComboBox()
        mood_items = [
            ("auto", "自动匹配（根据文本内容自动选择）"),
            ("casual", "日常温柔"),
            ("tsundere", "傲娇"),
            ("romantic", "深情"),
            ("long", "长句稳定"),
        ]
        for val, label in mood_items:
            self._tts_mood_combo.addItem(label, val)
        mood_vbox.addWidget(self._tts_mood_combo)
        scroll_layout.addWidget(mood_frame)

        # 语速
        speed_frame = self._create_frame()
        speed_vbox = QVBoxLayout(speed_frame)
        speed_vbox.setSpacing(6)
        speed_title = QLabel("语速（仅 GPT-SoVITS 生效）")
        speed_title.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        speed_vbox.addWidget(speed_title)

        speed_row = QHBoxLayout()
        self._tts_speed_slider = QSlider(Qt.Horizontal)
        self._tts_speed_slider.setRange(50, 200)
        self._tts_speed_value = QLabel("1.0x")
        self._tts_speed_value.setFixedWidth(45)
        self._tts_speed_slider.valueChanged.connect(self._on_tts_speed_changed)
        speed_row.addWidget(self._tts_speed_slider)
        speed_row.addWidget(self._tts_speed_value)
        speed_vbox.addLayout(speed_row)
        scroll_layout.addWidget(speed_frame)

        # 启动预热选项
        warmup_frame = self._create_frame()
        warmup_vbox = QVBoxLayout(warmup_frame)
        warmup_vbox.setSpacing(6)
        self._tts_warmup_cb = QCheckBox("启动时预热语音引擎")
        self._tts_warmup_cb.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        warmup_vbox.addWidget(self._tts_warmup_cb)
        warmup_desc = QLabel(
            "开启后，莲心启动时会在后台自动加载 GPT-SoVITS 模型。\n"
            "可大幅缩短首次语音回复的等待时间（约 5-15 秒）。\n"
            "仅在 GPT-SoVITS 可用时生效，关闭可节省 GPU 显存。"
        )
        warmup_desc.setWordWrap(True)
        warmup_desc.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0;")
        warmup_vbox.addWidget(warmup_desc)
        scroll_layout.addWidget(warmup_frame)

        # 试听按钮
        test_frame = self._create_frame()
        test_hbox = QHBoxLayout(test_frame)
        test_hbox.addWidget(QLabel("测试语音合成："))
        self._tts_test_btn = QPushButton("🔊 试听")
        self._tts_test_btn.setFixedWidth(120)
        self._tts_test_btn.clicked.connect(self._on_tts_test)
        test_hbox.addWidget(self._tts_test_btn)
        test_hbox.addStretch()
        scroll_layout.addWidget(test_frame)

        # 提示信息
        tts_tip = QLabel(
            "💡 GPT-SoVITS 支持声音克隆和情绪表达。\n"
            "· 在 skills/语音合成/ref_wavs/ 下放置参考音频即可激活声音克隆\n"
            "· 未配置时自动使用 Edge-TTS 标准发音，语音功能不受影响\n"
            "· 参考音频格式：WAV 文件，5-15 秒，24000Hz 采样率"
        )
        tts_tip.setWordWrap(True)
        tts_tip.setStyleSheet("color: #888; font-size: 12px; padding: 8px;")
        scroll_layout.addWidget(tts_tip)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)

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

    def _load_from_settings(self):
        # 加载 TTS 配置
        idx = 0 if self._tts_cfg.get("engine", "auto") != "edge_tts" else 1
        self._tts_engine_combo.setCurrentIndex(idx)
        self._tts_gs_path_edit.setText(self._tts_cfg.get("gpt_sovits_path", ""))
        # 选择默认情绪
        def_mood = self._tts_cfg.get("default_mood", "auto")
        for i in range(self._tts_mood_combo.count()):
            if self._tts_mood_combo.itemData(i) == def_mood:
                self._tts_mood_combo.setCurrentIndex(i)
                break
        speed = int(self._tts_cfg.get("speed", 1.0) * 100)
        self._tts_speed_slider.setValue(speed)
        self._tts_speed_value.setText(f"{speed / 100:.1f}x")
        self._tts_warmup_cb.setChecked(self._tts_cfg.get("tts_warmup", True))
        self._update_gs_status()

    def _browse_gs_path(self):
        from PyQt5.QtWidgets import QFileDialog
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择 GPT-SoVITS 安装目录", ""
        )
        if dir_path:
            self._tts_gs_path_edit.setText(dir_path)
            self._update_gs_status()

    def _update_gs_status(self):
        path = self._tts_gs_path_edit.text().strip()
        if not path:
            self._tts_gs_status.setText("未配置 GPT-SoVITS 路径，将使用 Edge-TTS 标准发音")
            self._tts_gs_status.setStyleSheet("color: #888; font-size: 11px;")
            return
        import os
        if not os.path.isdir(path):
            self._tts_gs_status.setText("路径不存在")
            self._tts_gs_status.setStyleSheet("color: #E74C3C; font-size: 11px;")
            return
        inference_dir = os.path.join(path, "GPT_SoVITS")
        if os.path.isdir(inference_dir):
            self._tts_gs_status.setText("GPT-SoVITS 目录已识别 ✓（具体可用性取决于 GPU 和模型配置）")
            self._tts_gs_status.setStyleSheet("color: #27AE60; font-size: 11px;")
        else:
            self._tts_gs_status.setText("已选择目录但未检测到 GPT_SoVITS 模块，请确认路径正确")
            self._tts_gs_status.setStyleSheet("color: #F39C12; font-size: 11px;")

    def _on_tts_speed_changed(self, value: int):
        speed = value / 100.0
        self._tts_speed_value.setText(f"{speed:.1f}x")

    def _on_tts_volume_changed(self, value):
        from utils.settings import get_settings
        vol = value / 100.0
        get_settings().tts_volume = vol

    def _on_sfx_volume_changed(self, value):
        from utils.settings import get_settings
        vol = value / 100.0
        get_settings().sfx_volume = vol

    def _on_tts_test(self):
        """试听语音合成效果。"""
        test_text = "你好，我是莲心。很高兴见到你。"
        self._tts_test_btn.setEnabled(False)
        self._tts_test_btn.setText("合成中…")

        # 先临时保存当前 UI 选择，保证试听立刻反应最新引擎设置
        engine_idx = self._tts_engine_combo.currentIndex()
        engine = "auto" if engine_idx == 0 else "edge_tts"
        gs_path = self._tts_gs_path_edit.text().strip()
        mood = self._tts_mood_combo.currentData()
        speed_val = self._tts_speed_slider.value() / 100.0

        save_tts_config({
            "engine": engine,
            "gpt_sovits_path": gs_path,
            "default_mood": mood,
            "speed": speed_val,
            "temperature": self._tts_cfg.get("temperature", 0.7),
            "top_k": self._tts_cfg.get("top_k", 5),
            "top_p": self._tts_cfg.get("top_p", 0.9),
            "sample_steps": self._tts_cfg.get("sample_steps", 32),
            "edge_tts_voice": self._tts_cfg.get("edge_tts_voice", "zh-CN-XiaoxiaoNeural"),
            "tts_warmup": self._tts_cfg.get("tts_warmup", True),
        })


        def _test():
            import tempfile, os, threading
            from brain.tts_engine import TtsEngine
            engine = TtsEngine()

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            wav_path = tmp.name
            tmp.close()

            try:
                success = engine.synthesize(test_text, wav_path)
                if not success:
                    return

                import pygame
                if not pygame.mixer.get_init():
                    pygame.init()
                    pygame.mixer.init()
                sound = pygame.mixer.Sound(wav_path)
                channel = pygame.mixer.find_channel()
                if channel:
                    channel.play(sound)
                else:
                    sound.play()
                while pygame.mixer.get_busy():
                    pygame.time.wait(50)
            finally:
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass
                self._tts_test_btn.setText("🔊 试听")
                self._tts_test_btn.setEnabled(True)

        import threading
        threading.Thread(target=_test, daemon=True).start()

    def _on_open_emotion_debug(self):
        from gui.emotional_debug_dialog import EmotionalDebugDialog
        dlg = EmotionalDebugDialog(self)
        dlg.exec_()

    def _on_save(self):
        """保存所有设置：声音+TTS"""
        # 声音设置（音量）在滑块变化时已实时保存
        # 保存 TTS 配置
        engine_idx = self._tts_engine_combo.currentIndex()
        engine = "auto" if engine_idx == 0 else "edge_tts"
        gs_path = self._tts_gs_path_edit.text().strip()
        mood = self._tts_mood_combo.currentData()
        speed = self._tts_speed_slider.value() / 100.0
        warmup = self._tts_warmup_cb.isChecked()

        save_tts_config({
            "engine": engine,
            "gpt_sovits_path": gs_path,
            "default_mood": mood,
            "speed": speed,
            "temperature": self._tts_cfg.get("temperature", 0.7),
            "top_k": self._tts_cfg.get("top_k", 5),
            "top_p": self._tts_cfg.get("top_p", 0.9),
            "sample_steps": self._tts_cfg.get("sample_steps", 32),
            "edge_tts_voice": self._tts_cfg.get("edge_tts_voice", "zh-CN-XiaoxiaoNeural"),
            "tts_warmup": warmup,
        })

        self.accept()
