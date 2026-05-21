"""
CameraDialog：摄像头预览和拍照对话框
支持拍照后保存到本地文件夹（可选）
"""

import cv2
import tempfile
import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QPushButton, QMessageBox, QCheckBox, QFileDialog)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap
from datetime import datetime
from pathlib import Path

from config import get_camera_config, save_camera_config


class CameraDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("拍照OCR - 对准图像后点击拍照")
        self.setModal(True)
        self.resize(640, 600)

        self.cap = None
        self.current_index = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)

        # 加载保存的设置
        self.settings = self._load_settings()

        self._init_ui()
        self._load_camera_list()
        self._load_last_used_camera()
        self._restore_settings()
        self.start_camera()

    def _load_settings(self):
        """从配置文件加载保存的选项"""
        cfg = get_camera_config()
        return {
            "save_to_local": cfg.get("save_to_local", False),
            "save_folder": cfg.get("save_folder", str(Path.home() / "Desktop"))
        }

    def _save_settings(self):
        """保存选项到配置文件"""
        cfg = {
            "device_index": self.cam_combo.currentData(),
            "save_to_local": self.save_checkbox.isChecked(),
            "save_folder": self.folder_path_label.text()
        }
        save_camera_config(cfg)

    def _restore_settings(self):
        """恢复保存的复选框状态和文件夹路径"""
        self.save_checkbox.setChecked(self.settings["save_to_local"])
        self.folder_path_label.setText(self.settings["save_folder"])
        self.folder_btn.setEnabled(self.settings["save_to_local"])
        self.folder_path_label.setEnabled(self.settings["save_to_local"])

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 摄像头选择栏
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("选择摄像头:"))
        self.cam_combo = QComboBox()
        self.cam_combo.currentIndexChanged.connect(self.on_camera_changed)
        top_layout.addWidget(self.cam_combo)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        # 保存选项行
        save_layout = QHBoxLayout()
        self.save_checkbox = QCheckBox("保存到本地")
        self.save_checkbox.stateChanged.connect(self.on_save_checkbox_changed)
        save_layout.addWidget(self.save_checkbox)
        
        self.folder_btn = QPushButton("选择文件夹")
        self.folder_btn.clicked.connect(self.choose_folder)
        save_layout.addWidget(self.folder_btn)
        
        self.folder_path_label = QLabel("未选择")
        self.folder_path_label.setStyleSheet("color: gray;")
        save_layout.addWidget(self.folder_path_label)

        # 添加红色提示文字
        warning_label = QLabel("提示：注意文件夹路径不能包含中文哦~")
        warning_label.setStyleSheet("color: red; font-size: 9pt;")
        save_layout.addWidget(warning_label)

        save_layout.addStretch()
        layout.addLayout(save_layout)

        # 视频显示区域
        self.video_label = QLabel()
        self.video_label.setMinimumSize(640, 480)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("border: 2px solid #6C7BFF; background-color: #000000;")
        layout.addWidget(self.video_label)

        # 按钮区域
        btn_layout = QHBoxLayout()
        self.snapshot_btn = QPushButton("📸 拍照")
        self.snapshot_btn.setFixedSize(100, 36)
        self.snapshot_btn.clicked.connect(self.take_photo)
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 36)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.snapshot_btn)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def on_save_checkbox_changed(self):
        enabled = self.save_checkbox.isChecked()
        self.folder_btn.setEnabled(enabled)
        self.folder_path_label.setEnabled(enabled)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择保存图片的文件夹")
        if folder:
            self.folder_path_label.setText(folder)

    def _load_camera_list(self):
        self.cam_combo.clear()
        for i in range(5):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                cap.release()
                self.cam_combo.addItem(f"摄像头 {i}", i)

    def _load_last_used_camera(self):
        cfg = get_camera_config()
        last_index = cfg.get("device_index", 0)
        idx = self.cam_combo.findData(last_index)
        if idx >= 0:
            self.cam_combo.setCurrentIndex(idx)
        elif self.cam_combo.count() > 0:
            self.cam_combo.setCurrentIndex(0)

    def on_camera_changed(self):
        if self.cap is not None:
            self.cap.release()
        self.start_camera()

    def start_camera(self):
        idx = self.cam_combo.currentData()
        if idx is None:
            return
        self.current_index = idx
        self.cap = cv2.VideoCapture(idx)
        if not self.cap.isOpened():
            QMessageBox.warning(self, "错误", f"无法打开摄像头 {idx}，请检查设备")
            return
        self.timer.start(30)

    def update_frame(self):
        if self.cap is None or not self.cap.isOpened():
            return
        ret, frame = self.cap.read()
        if not ret:
            return
        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image)
        scaled_pixmap = pixmap.scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.video_label.setPixmap(scaled_pixmap)

    def take_photo(self):
        if self.cap is None or not self.cap.isOpened():
            QMessageBox.warning(self, "错误", "摄像头未打开")
            return
        ret, frame = self.cap.read()
        if not ret:
            QMessageBox.warning(self, "错误", "拍照失败，无法捕获图像")
            return

        # 临时文件（用于OCR和聊天显示）
        fd, tmp_path = tempfile.mkstemp(suffix='.jpg', prefix='lianxin_cam_')
        os.close(fd)
        cv2.imwrite(tmp_path, frame)

        # 如果需要保存到本地
        saved_msg = None
        if self.save_checkbox.isChecked():
            folder = self.folder_path_label.text().strip()
            if folder:
                # 规范化路径（将 / 转换为 \ 并去除末尾斜杠）
                folder = os.path.abspath(os.path.normpath(folder))
                print(f"[调试] 规范化后的文件夹路径: {folder}")
                if not os.path.exists(folder):
                    try:
                        os.makedirs(folder)
                        print(f"[拍照] 自动创建文件夹: {folder}")
                    except Exception as e:
                        QMessageBox.warning(self, "错误", f"无法创建文件夹 {folder}\n{e}")
                        folder = None
                if folder and os.path.exists(folder):
                    # 测试文件夹是否可写
                    test_file = os.path.join(folder, "test_write.tmp")
                    try:
                        with open(test_file, 'w') as f:
                            f.write("test")
                        os.remove(test_file)
                        writable = True
                    except:
                        writable = False
                        QMessageBox.warning(self, "错误", f"文件夹不可写，请检查权限:\n{folder}")
                    if writable:
                        timestamp = datetime.now().strftime("%m_%d-%H_%M_%S")
                        filename = f"{timestamp}.jpg"
                        saved_path = os.path.join(folder, filename)
                        print(f"[调试] 尝试保存到: {saved_path}")
                        success = cv2.imwrite(saved_path, frame)
                        if success:
                            saved_msg = f"图片已保存至:\n{saved_path}"
                            print(f"[拍照] 已保存副本: {saved_path}")
                        else:
                            # 尝试 PNG 格式
                            alt_path = saved_path.replace('.jpg', '.png')
                            success = cv2.imwrite(alt_path, frame)
                            if success:
                                saved_msg = f"图片已保存至（PNG格式）:\n{alt_path}"
                            else:
                                QMessageBox.warning(self, "错误", f"保存图片失败，请检查文件夹权限\n{saved_path}")
            else:
                QMessageBox.warning(self, "警告", "保存文件夹路径为空，未保存副本")

        # 保存当前摄像头选择到配置
        current_idx = self.cam_combo.currentData()
        if current_idx is not None:
            self._save_settings()

        # 关闭资源
        self.timer.stop()
        if self.cap:
            self.cap.release()

        # 保存临时路径供外部使用
        self.photo_path = tmp_path

        # 如果有保存成功的消息，弹出提示
        if saved_msg:
            QMessageBox.information(self, "保存成功", saved_msg)

        self.accept()

    def reject(self):
        if self.cap:
            self.timer.stop()
            self.cap.release()
        super().reject()

    def get_photo_path(self):
        return getattr(self, 'photo_path', '')