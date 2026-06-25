"""
莲心AI — GUI 版入口
运行方式：python main.py
"""

import sys
import os
import ctypes
import warnings

# 屏蔽 pydub/TTS 临时文件未关闭的 ResourceWarning 刷屏
warnings.simplefilter("ignore", ResourceWarning)

# ── 第7条：工作目录修正 ────────────────────────────────────────
# 通过注册表开机自启时，Windows 默认将 CWD 设为 C:\Windows\System32。
# 在任何 import 之前强制切换到项目根目录，保证相对路径行为一致。
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(_PROJECT_ROOT)

# ── 终端防卡：双通道输出（终端 + 日志文件）─────────────────────
# Windows 终端"快速编辑模式"（点击选中文本）会锁定 stdout 缓冲区，
# 导致 print() 调用阻塞。解决：终端写入走独立线程，日志文件实时落盘。
# 终端可正常查看 print，选中复制不影响程序运行。
if sys.platform == "win32":
    import threading
    import queue as _queue_mod

    _LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
    os.makedirs(_LOG_DIR, exist_ok=True)
    _LOG_PATH = os.path.join(_LOG_DIR, "debug.log")
    try:
        if os.path.getsize(_LOG_PATH) > 5 * 1024 * 1024:
            _backup = _LOG_PATH + ".old"
            if os.path.exists(_backup):
                os.remove(_backup)
            os.rename(_LOG_PATH, _backup)
    except OSError:
        pass

    _REAL_STDOUT = sys.stdout
    _REAL_STDERR = sys.stderr

    class _TeeWriter:
        """同时写入日志文件和终端；终端写入走独立线程，避免 Quick Edit 阻塞。"""
        def __init__(self, log_path, real_stream):
            self._log = open(log_path, "a", encoding="utf-8", buffering=1)
            self._real = real_stream
            self._queue = _queue_mod.Queue()
            self._worker = threading.Thread(target=self._drain, daemon=True)
            self._worker.start()

        def _drain(self):
            while True:
                text = self._queue.get()
                if text is None:
                    break
                try:
                    self._real.write(text)
                    self._real.flush()
                except Exception:
                    pass

        def write(self, text):
            self._log.write(text)
            self._log.flush()
            self._queue.put(text)

        def flush(self):
            self._log.flush()

    sys.stdout = _TeeWriter(_LOG_PATH, _REAL_STDOUT)
    sys.stderr = _TeeWriter(_LOG_PATH, _REAL_STDERR)

# 确保项目根目录在路径中
sys.path.insert(0, _PROJECT_ROOT)

# 禁用 Anthropic SDK 内部 OpenTelemetry 追踪，避免 protobuf UTF-8 序列化报错
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

# 导入迁移函数（必须在切换工作目录后）
from utils.paths import migrate_legacy_files   # 新增

# 执行数据迁移（仅首次运行会移动旧文件）
migrate_legacy_files()

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt
import qdarkstyle

from gui.main_window import MainWindow


# ── 第5条：多实例保护 ─────────────────────────────────────────
# 使用 Windows 命名互斥量确保同一时刻只有一个莲心AI进程运行。
# 句柄存为模块级变量，防止进程退出前被意外回收。
_MUTEX_HANDLE = None


def _acquire_single_instance_mutex() -> bool:
    """
    尝试创建命名互斥量。
    返回 True 表示当前进程获得唯一运行权；
    返回 False 表示已有另一个实例在运行。
    """
    global _MUTEX_HANDLE
    _MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(
        None, False, "LianxinAI_SingleInstance_v1"
    )
    # GetLastError() == 183 (ERROR_ALREADY_EXISTS) 说明互斥量已存在
    return ctypes.windll.kernel32.GetLastError() != 183


def main():
    autostart_mode = "--autostart" in sys.argv

    # ── 第5条：单实例检测（在创建 QApplication 之前执行）────────
    if not _acquire_single_instance_mutex():
        if not autostart_mode:
            # 手动启动时提示用户（需要先建 QApplication 才能弹窗）
            _app = QApplication(sys.argv)
            QMessageBox.information(
                None, "莲心AI",
                "莲心已经在运行了哦，请在任务栏找到她~"
            )
        # 无论手动还是自启，直接退出，不创建第二个窗口
        sys.exit(0)

    # 高 DPI 支持（Windows 缩放适配）
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("莲心AI")
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())   # ← 加这行
    # 全局字体
    font = QFont("Microsoft YaHei UI", 10)
    app.setFont(font)

    window = MainWindow(autostart_mode=autostart_mode)

    # ── 自动激活标记为 auto_activate 的技能 ────────────────────
    from brain.skill_manager import activate_all_skills
    activate_all_skills()

    # ── 初始化 MCP 系统 ──────────────────────────────────
    from brain.mcp.mcp_manager import get_mcp_manager
    _mcp_mgr = get_mcp_manager()
    _mcp_mgr.initialize()

    import atexit
    atexit.register(_mcp_mgr.shutdown)


    # ── QQ 桥接（由 MainWindow 管理，详见 main_window.py）─────

    # ── 第6条：自启动时最小化，不打扰用户 ────────────────────────
    # 欢迎消息和 TTS 在后台运行，等网络就绪后自动触发；
    # 用户可随时点击任务栏图标展开莲心窗口。
    if autostart_mode:
        window.showMinimized()
    else:
        window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()