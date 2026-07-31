"""
utils/resource_path.py — PyInstaller 打包后资源路径兼容

开发模式：基于 __file__ 定位
打包模式：基于 sys._MEIPASS 定位
"""
import sys
from pathlib import Path


def get_base_dir() -> Path:
    """返回项目根目录，兼容开发和 PyInstaller 打包两种模式。"""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def get_asset_path(*parts: str) -> Path:
    """获取 assets 目录下的资源路径。

    Usage:
        get_asset_path("sound", "write.mp3")
        get_asset_path("GIF", "待机", "normal.gif")
    """
    return get_base_dir() / "assets" / Path(*parts)