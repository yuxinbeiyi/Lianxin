"""
SettingsManager：莲心全局设置管理器
管理静默模式、语音设置等全局配置
"""

import json
from pathlib import Path
from utils.paths import get_user_data_dir   # 新增导入

_SETTINGS_PATH = get_user_data_dir() / "global_settings.json"

_DEFAULT_SETTINGS = {
    "silent_mode": False,                # 全局静默模式：True=不朗读，False=朗读
    "last_autostart_welcome_date": "",   # 上次自启动欢迎消息发送日期（YYYY-MM-DD）
    "show_exit_confirmation": True,      # 退出时显示确认弹窗：True=显示，False=不显示
    "font_size": 12,                     # 聊天字体大小（像素）
    "galgame_font_size": 12,             # Galgame 字体大小（像素）
    "galgame_font_bold": False,          # Galgame 字体加粗
    "standby_auto_send": True,           # 待机模式自动发送：True=开启
    "standby_auto_send_delay": 5,        # 自动发送延迟（秒）
    "standby_end_word": "完毕",           # 待机模式结束词
    "note_file_path": "",                # 小纸条文件路径（空表示使用默认路径）
    "tts_volume": 1.0,                   # TTS 语音音量 0.0-1.0
    "sfx_volume": 1.0,                   # 音效音量 0.0-1.0
    "music_playlist_index": 0,
    "music_is_playing": False,
    "music_volume": 0.5,
    "music_position": 0.0,          # 新增：播放位置（秒）
    "emotion_probability": 0.6,   # 发表情包概率    默认 60%
    "user_name": "雨心",           # 用户称呼（莲心对用户的称呼）
}


class SettingsManager:
    def __init__(self):
        self._settings = {}
        self._load()

    def _load(self):
        try:
            if _SETTINGS_PATH.exists():
                data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
                self._settings = data
            else:
                self._settings = _DEFAULT_SETTINGS.copy()
        except Exception:
            self._settings = _DEFAULT_SETTINGS.copy()

    def save(self):
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(
            json.dumps(self._settings, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    @property
    def silent_mode(self) -> bool:
        return self._settings.get("silent_mode", False)

    @silent_mode.setter
    def silent_mode(self, val: bool):
        self._settings["silent_mode"] = val
        self.save()

    @property
    def last_autostart_welcome_date(self) -> str:
        return self._settings.get("last_autostart_welcome_date", "")

    @last_autostart_welcome_date.setter
    def last_autostart_welcome_date(self, val: str):
        self._settings["last_autostart_welcome_date"] = val
        self.save()

    @property
    def show_exit_confirmation(self) -> bool:
        return self._settings.get("show_exit_confirmation", True)

    @show_exit_confirmation.setter
    def show_exit_confirmation(self, val: bool):
        self._settings["show_exit_confirmation"] = val
        self.save()

    @property
    def font_size(self) -> int:
        return self._settings.get("font_size", 12)

    @font_size.setter
    def font_size(self, val: int):
        self._settings["font_size"] = val
        self.save()
    # ========== Galgame 字体 ==========
    @property
    def galgame_font_size(self) -> int:
        return self._settings.get("galgame_font_size", 12)

    @galgame_font_size.setter
    def galgame_font_size(self, val: int):
        self._settings["galgame_font_size"] = val
        self.save()

    @property
    def galgame_font_bold(self) -> bool:
        return self._settings.get("galgame_font_bold", False)

    @galgame_font_bold.setter
    def galgame_font_bold(self, val: bool):
        self._settings["galgame_font_bold"] = val
        self.save()
    # ========== 待机模式 ==========
    @property
    def standby_auto_send(self) -> bool:
        return self._settings.get("standby_auto_send", True)

    @standby_auto_send.setter
    def standby_auto_send(self, val: bool):
        self._settings["standby_auto_send"] = val
        self.save()

    @property
    def standby_auto_send_delay(self) -> int:
        return self._settings.get("standby_auto_send_delay", 5)

    @standby_auto_send_delay.setter
    def standby_auto_send_delay(self, val: int):
        self._settings["standby_auto_send_delay"] = val
        self.save()

    @property
    def standby_end_word(self) -> str:
        return self._settings.get("standby_end_word", "完毕")

    @standby_end_word.setter
    def standby_end_word(self, val: str):
        self._settings["standby_end_word"] = val
        self.save()

    # ========== 小纸条路径 ==========
    @property
    def note_file_path(self) -> str:
        """获取小纸条文件路径，如果未配置则返回默认路径"""
        path = self._settings.get("note_file_path", "")
        if path and Path(path).parent.exists():
            return path
        # 默认路径：用户桌面
        return str(Path.home() / "Desktop" / "小纸条.txt")

    @note_file_path.setter
    def note_file_path(self, val: str):
        self._settings["note_file_path"] = val
        self.save()

    # ========== 音量设置 ==========
    @property
    def tts_volume(self) -> float:
        return self._settings.get("tts_volume", 1.0)

    @tts_volume.setter
    def tts_volume(self, val: float):
        # 确保数值在 0.0-1.0 之间
        val = max(0.0, min(1.0, val))
        self._settings["tts_volume"] = val
        self.save()

    @property
    def sfx_volume(self) -> float:
        return self._settings.get("sfx_volume", 1.0)

    @sfx_volume.setter
    def sfx_volume(self, val: float):
        val = max(0.0, min(1.0, val))
        self._settings["sfx_volume"] = val
        self.save()

    # ========== 音乐盒设置 ==========
    @property
    def music_volume(self) -> float:
        return self._settings.get("music_volume", 0.5)

    @music_volume.setter
    def music_volume(self, val: float):
        self._settings["music_volume"] = max(0.0, min(1.0, val))
        self.save()

    @property
    def music_playlist_index(self) -> int:
        return self._settings.get("music_playlist_index", 0)

    @music_playlist_index.setter
    def music_playlist_index(self, val: int):
        self._settings["music_playlist_index"] = val
        self.save()

    @property
    def music_is_playing(self) -> bool:
        return self._settings.get("music_is_playing", False)

    @music_is_playing.setter
    def music_is_playing(self, val: bool):
        self._settings["music_is_playing"] = val
        self.save()

    @property
    def music_position(self) -> float:
        return self._settings.get("music_position", 0.0)

    @music_position.setter
    def music_position(self, val: float):
        self._settings["music_position"] = val
        self.save()
    @property
    
    def global_smart_reminder(self) -> bool:
        return self._settings.get("global_smart_reminder", False)

    @global_smart_reminder.setter
    def global_smart_reminder(self, val: bool):
        self._settings["global_smart_reminder"] = val
        self.save()

    @property
    def emotion_probability(self) -> float:
        return self._settings.get("emotion_probability", 0.6)

    @emotion_probability.setter
    def emotion_probability(self, val: float):
        val = max(0.0, min(1.0, val))   # 限制在 0~1 之间
        self._settings["emotion_probability"] = val
        self.save()

    # ========== 用户称呼 ==========
    @property
    def user_name(self) -> str:
        return self._settings.get("user_name", "雨心")

    @user_name.setter
    def user_name(self, val: str):
        val = val.strip()
        if val:
            self._settings["user_name"] = val
            self.save()


# 全局单例
_global_settings = None

def get_settings() -> SettingsManager:
    global _global_settings
    if _global_settings is None:
        _global_settings = SettingsManager()
    return _global_settings

