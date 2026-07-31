"""
OcrWorker：后台线程执行 OCR 识别，避免界面卡顿
"""
from PyQt5.QtCore import QThread, pyqtSignal
from brain.tools import ocr_image

class OcrWorker(QThread):
    finished = pyqtSignal(str)   # 识别出的文字
    error    = pyqtSignal(str)   # 错误信息

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path

    def run(self):
        try:
            result = ocr_image(self.image_path)
            # ocr_image 返回格式 "图片中的文字识别结果：\n\n...."
            if result.startswith("图片中的文字识别结果：\n\n"):
                text = result[len("图片中的文字识别结果：\n\n"):]
            else:
                text = result
            self.finished.emit(text.strip())
        except Exception as e:
            self.error.emit(str(e))