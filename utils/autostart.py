"""
AutoStart：莲心AI 开机自启动管理
通过 Windows 注册表 HKCU\...\Run 实现当前用户开机自启。
启动命令携带 --autostart 参数，用于区分自动启动与手动启动。
"""

import os
import sys
import socket

try:
    import winreg
    _WINREG_AVAILABLE = True
except ImportError:
    _WINREG_AVAILABLE = False

_REG_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "LianxinAI"   # 注册表值名（纯英文，避免编码问题）


# ── 注册表操作 ────────────────────────────────────────────────

def _get_startup_command() -> str:
    """构建开机自启命令，支持开发环境（.py）和打包后（.exe）"""
    if getattr(sys, 'frozen', False):
        # 打包成 exe 的情况：直接运行 exe 自身
        exe_path = sys.executable
        return f'"{exe_path}" --autostart'
    else:
        # 开发环境：使用 pythonw.exe 运行 main.py（避免黑窗）
        python_dir = os.path.dirname(sys.executable)
        pythonw = os.path.join(python_dir, "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable   # 回退：用 python.exe（会有黑窗）
        main_py = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "main.py"
        )
        return f'"{pythonw}" "{main_py}" --autostart'


def enable_autostart() -> tuple[bool, str]:
    """
    写入注册表开机自启项。
    返回 (成功, 错误信息)，成功时错误信息为空字符串。
    """
    if not _WINREG_AVAILABLE:
        return False, "winreg 模块不可用（非 Windows 系统）"
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_KEY,
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _get_startup_command())
        winreg.CloseKey(key)
        return True, ""
    except Exception as e:
        return False, str(e)


def disable_autostart() -> tuple[bool, str]:
    """
    从注册表删除开机自启项。
    返回 (成功, 错误信息)，成功时错误信息为空字符串。
    """
    if not _WINREG_AVAILABLE:
        return False, "winreg 模块不可用（非 Windows 系统）"
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_KEY,
            0, winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(key, _APP_NAME)
        winreg.CloseKey(key)
        return True, ""
    except FileNotFoundError:
        return True, ""   # 本来就不存在，视为成功
    except Exception as e:
        return False, str(e)


def is_autostart_enabled() -> bool:
    """检查注册表里是否存在莲心AI开机自启项。"""
    if not _WINREG_AVAILABLE:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_KEY,
            0, winreg.KEY_READ
        )
        winreg.QueryValueEx(key, _APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


# ── 网络连通性检测 ────────────────────────────────────────────

def check_network(timeout: float = 3.0) -> bool:
    """
    检测当前是否有可用的网络连接。
    尝试连接 DNS 服务器（8.8.8.8:53），不依赖具体域名解析。
    """
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=timeout)
        return True
    except OSError:
        return False
