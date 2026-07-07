"""
莲心AI — GUI 版入口
运行方式：python main.py
"""

import sys
import os
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
import ctypes
import warnings
import traceback

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

    _REAL_STDOUT = sys.stdout
    _REAL_STDERR = sys.stderr

    class _TeeWriter:
        """同时写入日志文件和终端；终端写入走独立线程，避免 Quick Edit 阻塞。"""
        def __init__(self, log_path, real_stream):
            self._log_path = log_path
            self._log = self._open_log()
            self._real = real_stream
            self._queue = _queue_mod.Queue()
            self._worker = threading.Thread(target=self._drain, daemon=True)
            self._worker._tee_writer_alive = True
            self._worker.start()

        def _open_log(self):
            try:
                # 启动时轮转日志：超过 5MB 就备份
                if os.path.exists(self._log_path):
                    try:
                        if os.path.getsize(self._log_path) > 5 * 1024 * 1024:
                            _backup = self._log_path + ".old"
                            if os.path.exists(_backup):
                                os.remove(_backup)
                            os.rename(self._log_path, _backup)
                    except OSError:
                        pass
                return open(self._log_path, "a", encoding="utf-8", buffering=1)
            except Exception:
                return None

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
            if self._log is not None:
                try:
                    self._log.write(text)
                    self._log.flush()
                except Exception:
                    try:
                        self._log.close()
                    except Exception:
                        pass
                    self._log = self._open_log()
            try:
                self._queue.put_nowait(text)
            except _queue_mod.Full:
                pass

        def flush(self):
            if self._log is not None:
                try:
                    self._log.flush()
                except Exception:
                    pass

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


def _global_exception_handler(exc_type, exc_value, exc_tb):
    """全局未处理异常捕获：记录到日志文件后优雅退出。"""
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        log_dir = os.path.join(_PROJECT_ROOT, "logs")
        os.makedirs(log_dir, exist_ok=True)
        crash_path = os.path.join(log_dir, "crash.log")
        with open(crash_path, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"\n{'='*60}\n")
            f.write(f"崩溃时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"异常类型: {exc_type.__name__}\n")
            f.write(f"异常信息: {exc_value}\n")
            f.write(f"堆栈跟踪:\n{tb_text}\n")
        print(f"\n[致命错误] {exc_type.__name__}: {exc_value}", file=sys.stderr)
        print(f"详细堆栈已写入: {crash_path}", file=sys.stderr)
    except Exception:
        print(f"\n[致命错误] {exc_type.__name__}: {exc_value}", file=sys.stderr)
        print(tb_text, file=sys.stderr)

sys.excepthook = _global_exception_handler

# 捕获后台线程中未处理的异常（Python 3.8+）
_threading_excepthook = threading.excepthook if hasattr(threading, "excepthook") else None


def _thread_exception_handler(args):
    exc_type, exc_value, exc_tb, thread = args.thread if hasattr(args, "thread") else (args.exc_type, args.exc_value, args.exc_traceback, args.thread)
    _global_exception_handler(exc_type, exc_value, exc_tb)


if _threading_excepthook is not None:
    threading.excepthook = _thread_exception_handler


def main():
    autostart_mode = "--autostart" in sys.argv

    # ── 第5条：单实例检测（在创建 QApplication 之前执行）────────
    if not _acquire_single_instance_mutex():
        if not autostart_mode:
            _app = QApplication(sys.argv)
            QMessageBox.information(
                None, "莲心AI",
                "莲心已经在运行了哦，请在任务栏找到她~"
            )
        sys.exit(0)

    # 高 DPI 支持（Windows 缩放适配）
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("莲心AI")
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())

    # ── 全局异常处理：确保 Qt 事件循环中的异常也被捕获 ──
    def _qt_exception_handler(exc_type, exc_value, tb_obj):
        _global_exception_handler(exc_type, exc_value, tb_obj)
        app.quit()
    sys.excepthook = _qt_exception_handler

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