"""莲心自习室模块。"""

__all__ = ["StudyRoomWindow", "StudyRoomWebWindow"]


def __getattr__(name):
    """延迟加载 GUI 类，让数据库/报告测试无需初始化 Qt WebEngine。"""
    if name == "StudyRoomWindow":
        from .window import StudyRoomWindow
        return StudyRoomWindow
    if name == "StudyRoomWebWindow":
        from .web_window import StudyRoomWebWindow
        return StudyRoomWebWindow
    raise AttributeError(name)
