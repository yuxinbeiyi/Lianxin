"""
AccompanyStats：莲心陪伴统计模块
记录累计使用时长，支持跨会话累加
"""

import json
from datetime import datetime, date
from pathlib import Path
from utils.paths import get_user_data_dir   # 新增导入


class AccompanyStats:
    """陪伴统计管理器"""

    def __init__(self):
        # 使用用户数据目录
        self._data_dir = get_user_data_dir()
        self._stats_file = self._data_dir / "accompany_stats.json"
        self._ensure_data_dir()
        self._load()
        self._session_start_time = None  # 本次启动时间

    def _ensure_data_dir(self):
        """确保用户数据目录存在"""
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _load(self):
        """从文件加载统计数据"""
        if self._stats_file.exists():
            try:
                with open(self._stats_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._total_seconds = data.get("total_seconds", 0)
                    self._session_count = data.get("session_count", 0)
                    self._first_meet_date = data.get("first_meet_date", "")
                    self._avatar_interactions = data.get("avatar_interactions", {}) or {}
                    self._avatar_interactions.setdefault("events", [])
            except (json.JSONDecodeError, IOError):
                self._total_seconds = 0
                self._session_count = 0
                self._first_meet_date = ""
                self._avatar_interactions = {"events": []}
        else:
            self._total_seconds = 0
            self._session_count = 0
            self._first_meet_date = ""
            self._avatar_interactions = {"events": []}

    def reload(self):
        """重新从文件加载数据（用于设置保存后立即更新）"""
        self._load()
        print(f"[陪伴统计] 已重新加载数据，first_meet_date={self._first_meet_date}")

    def _save(self):
        """保存统计数据到文件"""
        data = {
            "total_seconds": self._total_seconds,
            "session_count": self._session_count,
            "first_meet_date": self._first_meet_date,
            "avatar_interactions": self._avatar_interactions,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(self._stats_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # 以下方法保持不变（start_session, end_session, has_first_meet_date 等）
    # 注意：确保 _save() 和 _load() 已正确使用新路径，其他方法无需改动

    def start_session(self):
        """程序启动时调用，记录本次会话开始时间"""
        self._session_start_time = datetime.now()
        self._session_count += 1
        self._save()

    def end_session(self):
        """程序关闭时调用，计算本次使用时长并累加"""
        if self._session_start_time is not None:
            elapsed = (datetime.now() - self._session_start_time).total_seconds()
            if elapsed > 0:
                self._total_seconds += elapsed
                self._save()
        self._session_start_time = None

    # ── 初识日期管理 ─────────────────────────────────────────

    def has_first_meet_date(self) -> bool:
        return bool(self._first_meet_date)

    def get_first_meet_date(self) -> str:
        return self._first_meet_date

    def set_first_meet_date(self, date_str: str):
        self._first_meet_date = date_str
        self._save()

    def record_avatar_interaction(self, interaction_type="user_tap", reaction_type="neutral"):
        """记录头像互动；这是陪伴统计，不写入长期记忆。"""
        data = self._avatar_interactions
        data["interaction_count"] = int(data.get("interaction_count", 0)) + 1
        data["user_tap_count"] = int(data.get("user_tap_count", 0)) + (1 if interaction_type == "user_tap" else 0)
        data["assistant_counter_tap_count"] = int(data.get("assistant_counter_tap_count", 0)) + (1 if interaction_type == "counter_tap" else 0)
        data["last_interaction_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        types = data.setdefault("reaction_types", {})
        types[reaction_type] = int(types.get(reaction_type, 0)) + 1
        events = data.setdefault("events", [])
        events.append({
            "at": datetime.now().isoformat(timespec="seconds"),
            "type": interaction_type,
            "reaction": reaction_type,
        })
        del events[:-100]
        self._save()

    def get_avatar_interactions(self) -> dict:
        return dict(self._avatar_interactions)

    def get_avatar_interaction_summary(self) -> dict:
        events = self._avatar_interactions.get("events", [])
        today = datetime.now().date().isoformat()
        week_start = date.today().toordinal() - date.today().weekday()
        today_count = 0
        week_count = 0
        for event in events:
            stamp = str(event.get("at", ""))
            if stamp[:10] == today:
                today_count += 1
            try:
                if datetime.fromisoformat(stamp).date().toordinal() >= week_start:
                    week_count += 1
            except ValueError:
                pass
        return {
            "total": int(self._avatar_interactions.get("interaction_count", 0)),
            "user_taps": int(self._avatar_interactions.get("user_tap_count", 0)),
            "counter": int(self._avatar_interactions.get("assistant_counter_tap_count", 0)),
            "today": today_count,
            "week": week_count,
            "last_interaction_at": self._avatar_interactions.get("last_interaction_at", ""),
            "events": list(events),
        }

    def get_total_days_since_first_meet(self) -> int:
        if not self._first_meet_date:
            return 0
        try:
            first_date = datetime.strptime(self._first_meet_date, "%Y-%m-%d").date()
            today = date.today()
            return (today - first_date).days + 1
        except ValueError:
            return 0

    # ── 统计数据获取 ─────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "total_seconds": self._total_seconds,
            "session_count": self._session_count
        }

    def get_current_total_seconds(self) -> int:
        current_seconds = self._total_seconds
        if self._session_start_time is not None:
            elapsed = (datetime.now() - self._session_start_time).total_seconds()
            current_seconds += max(0, elapsed)
        return int(current_seconds)

    def get_current_formatted_duration(self) -> str:
        seconds = self.get_current_total_seconds()
        days = seconds // 86400
        seconds %= 86400
        hours = seconds // 3600
        seconds %= 3600
        minutes = seconds // 60
        seconds %= 60
        parts = []
        if days > 0:
            parts.append(f"{days}天")
        if hours > 0 or days > 0:
            parts.append(f"{hours}小时")
        if minutes > 0 or hours > 0 or days > 0:
            parts.append(f"{minutes}分钟")
        parts.append(f"{seconds}秒")
        return "".join(parts)

    def get_formatted_duration(self) -> str:
        seconds = int(self._total_seconds)
        days = seconds // 86400
        seconds %= 86400
        hours = seconds // 3600
        seconds %= 3600
        minutes = seconds // 60
        seconds %= 60
        parts = []
        if days > 0:
            parts.append(f"{days}天")
        if hours > 0 or days > 0:
            parts.append(f"{hours}小时")
        if minutes > 0 or hours > 0 or days > 0:
            parts.append(f"{minutes}分钟")
        parts.append(f"{seconds}秒")
        return "".join(parts)

    def reset(self) -> str:
        self._total_seconds = 0
        self._session_count = 0
        self._first_meet_date = ""
        self._avatar_interactions = {"events": []}
        self._session_start_time = datetime.now()
        self._save()
        return "陪伴统计数据已重置"
