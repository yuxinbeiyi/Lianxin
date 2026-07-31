"""
utils/sound.py - 音效播放工具
"""
import pygame
from utils.resource_path import get_asset_path
_SOUNDS_DIR = get_asset_path("sound")
def play_sound(filename: str):
    """播放指定名称的音效文件（位于 assets/sound/ 下），音量跟随系统设置"""
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        sound_path = _SOUNDS_DIR / filename
        if sound_path.exists():
            sound = pygame.mixer.Sound(str(sound_path))
            # 获取当前音效音量
            from utils.settings import get_settings
            volume = get_settings().sfx_volume
            sound.set_volume(volume)
            sound.play()
        else:
            print(f"[音效] 文件不存在: {sound_path}")
    except Exception as e:
        print(f"[音效] 播放失败 {filename}: {e}")