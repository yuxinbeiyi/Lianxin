"""
PomodoroStats：番茄钟专注统计模块
记录累计专注时长和专注次数，持久化保存到用户目录/.lianxin/pomodoro_stats.json
"""

import json
from pathlib import Path
from datetime import datetime
from utils.paths import get_user_data_dir

_STATS_PATH = get_user_data_dir() / "pomodoro_stats.json"

_DEFAULT_STATS = {
    "total_seconds": 0,      # 累计专注秒数（只统计完整完成的专注）
    "total_sessions": 0,     # 累计专注次数（只统计完整完成的专注）
    "last_updated": "",      # 最后更新时间
}


class PomodoroStats:
    def __init__(self):
        self._stats = {}
        self._load()

    def _load(self):
        try:
            if _STATS_PATH.exists():
                data = json.loads(_STATS_PATH.read_text(encoding="utf-8"))
                self._stats = data
            else:
                self._stats = _DEFAULT_STATS.copy()
        except Exception:
            self._stats = _DEFAULT_STATS.copy()

    def _save(self):
        _STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATS_PATH.write_text(
            json.dumps(self._stats, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def add_completed_session(self, seconds: int):
        """
        添加一次完整完成的专注时长
        :param seconds: 专注的秒数（>0）
        """
        if seconds <= 0:
            return
        self._stats["total_seconds"] = self._stats.get("total_seconds", 0) + seconds
        self._stats["total_sessions"] = self._stats.get("total_sessions", 0) + 1
        self._stats["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._save()

    def get_stats(self) -> dict:
        """获取统计数据"""
        return {
            "total_seconds": self._stats.get("total_seconds", 0),
            "total_sessions": self._stats.get("total_sessions", 0),
        }

    def get_formatted_duration(self) -> str:
        """获取格式化的累计专注时长（时/分/秒）"""
        seconds = self._stats.get("total_seconds", 0)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours}小时{minutes}分钟{secs}秒"

    def reset(self):
        """重置统计数据（谨慎使用）"""
        self._stats = _DEFAULT_STATS.copy()
        self._save()