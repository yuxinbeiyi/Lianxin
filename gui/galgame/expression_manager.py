"""
ExpressionManager：莲心 Galgame 窗口的表情识别与图片映射
"""
import re
from pathlib import Path

# ── 情绪关键词 → 图片文件名映射 ──────────────────────────
# 等你准备好表情 PNG 后，把文件名填进来即可
# 例如: {"开心": "开心.png", "生气": "生气.png"}
EMOTION_IMAGE_MAP: dict[str, str] = {}

# 情绪正则匹配模式（优先级从高到低）
_EMOTION_PATTERNS: list[tuple[str, str]] = [
    ("开心",   r"(开心|高兴|快乐|愉快|喜悦|哈哈哈|嘿嘿|嘻嘻|好开心)"),
    ("生气",   r"(生气|愤怒|不满|不爽|气死|烦死了|火大)"),
    ("伤心",   r"(伤心|难过|哭泣|悲伤|泪|哭哭|呜呜|好难过)"),
    ("惊讶",   r"(惊讶|吃惊|震惊|意外|真的吗|不会吧|天哪|哇)"),
    ("疑惑",   r"(疑惑|困惑|不解|奇怪|嗯？|啥？|为什么)"),
    ("害羞",   r"(害羞|不好意思|脸红|羞羞|难为情)"),
    ("撒娇",   r"(撒娇|嘛~|人家|讨厌|不要嘛)"),
    ("疲惫",   r"(疲惫|累|好累|困|想睡|没精神)"),
    ("默认",   ""),  # 兜底
]


class ExpressionManager:
    """管理情绪识别与图片映射。"""

    def __init__(self, assets_dir: str | Path):
        self._assets_dir = Path(assets_dir)
        self._fallback_image = "莲心形象透明背景.png"

    def match(self, text: str) -> str:
        """从 AI 回复文本中匹配情绪关键词，返回情绪名称。"""
        for emotion, pattern in _EMOTION_PATTERNS:
            if not pattern:
                continue
            if re.search(pattern, text):
                return emotion
        return "默认"

    def get_image_path(self, emotion: str) -> str:
        """获取情绪对应的立绘图片路径，没有则回退到默认图。"""
        filename = EMOTION_IMAGE_MAP.get(emotion)
        if filename:
            img_path = self._assets_dir / filename
            if img_path.exists():
                return str(img_path)
        # 回退到默认图
        fallback = self._assets_dir / self._fallback_image
        return str(fallback) if fallback.exists() else ""
