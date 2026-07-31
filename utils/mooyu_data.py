"""
mooyu_data.py — 摸鱼数据源卡片数据模型

MooyuDataSource：记录一次摸鱼动作背后的数据查询结果，
用于在聊天界面以卡片形式展示给用户，证明莲心确实获取了真实数据而非捏造。
"""

from dataclasses import dataclass


@dataclass
class MooyuDataSource:
    """一次摸鱼数据查询的记录"""

    source_name: str       # 编程名称，如 "get_weather"
    friendly_name: str     # 友好名称，如 "天气查询"
    preview: str           # 单行摘要，用户一眼能看到的关键数据
    is_error: bool = False
    detail: str = ""       # 完整数据文本（展开卡片时显示）
    elapsed_ms: float = 0.0


# source_name → 友好描述（用于 thinking 标签和卡片标题）
MOOYU_SOURCE_FRIENDLY: dict[str, str] = {
    # SlackDuty 动作
    "get_weather":              "天气查询",
    "get_diary_today":          "翻阅今天的日记",
    "get_diary_old":            "翻阅旧日记",
    "get_chat_history":         "查看聊天记录",
    "get_todos":                "查看待办",
    "get_random_document":      "浏览电脑文件",
    "get_browser_history":      "查看浏览记录",
    "get_system_status":        "查看系统状态",
    "get_recycle_bin":          "查看回收站",
    "get_uptime":               "查看开机时长",
    "get_anniversary":          "查看相识纪念日",
    "get_current_song":         "查看当前播放",
    "remind_water":             "喝水提醒",
    "remind_rest":              "休息提醒",
    # ProactiveWorker 数据源
    "get_memory_facts":         "检索长期记忆",
    "bilibili_keywords":        "生成 B 站搜索词",
    "bilibili_search":          "B 站搜索",
    "bilibili_select":          "筛选 B 站视频",
}


def format_elapsed(ms: float) -> str:
    """格式化耗时文本"""
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    elif ms > 0:
        return f"{ms:.0f}ms"
    return ""
