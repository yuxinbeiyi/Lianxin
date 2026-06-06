"""
日记与备忘技能 — 自定义工具
日记读写、备忘本管理与 AI 整理
"""

import brain.tools as _brain_tools

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_diary",
            "description": (
                    "【强制】当用户要求读日记、回忆某天内容或搜索日记关键词时，必须调用此工具。"
                    "不要直接输出任何日记内容。工具会返回真实日记文本。"
                    "参数：date (YYYY-MM-DD) 或 keyword (搜索词) 或 limit (最近几篇)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "要查询的日期，格式 YYYY-MM-DD，例如 '2026-04-17'。"
                    },
                    "keyword": {
                        "type": "string",
                        "description": "在日记中搜索的关键词，例如 '开心' 或 '读书'。"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回最近几篇日记的数量（仅在不提供 date 和 keyword 时有效），默认 1。"
                    }
                },
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_diary",
            "description": (
                "【强制】当用户要求写日记、生成日记、记日记时，必须调用此工具。"
                "工具会基于今日对话记录自动生成一篇日记并保存到日记本。"
                "不要直接回复'好的已写好'之类的话，必须调用此工具。"
                "参数：message_count (可选, 使用最近N条消息, 默认取配置值), force (可选, 当日已有日记时是否覆盖, 默认false)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message_count": {
                        "type": "integer",
                        "description": "使用最近N条今日消息生成日记，不传则使用全局配置的默认值（30条）"
                    },
                    "force": {
                        "type": "boolean",
                        "description": "如果今天已有日记是否覆盖重写，默认false（保留已有日记）"
                    }
                },
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_note",
            "description": "读取备忘本的全部文字内容。当用户要求查看备忘本、看一下备忘本、备忘本里写了什么时调用。不要直接朗读，而是理解内容后与用户聊天。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "organize_note",
            "description": "调用 AI 智能整理备忘本内容，使它更整洁、有条理。当用户要求整理备忘本、清理备忘本时调用。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
]


def _read_diary(date: str = None, keyword: str = None, limit: int = 1) -> str:
    from utils.diary import get_diary_by_date, search_diaries_by_keyword, get_recent_diaries
    if date:
        diary = get_diary_by_date(date)
        if not diary:
            return f"没有找到 {date} 的日记。"
        return f"【{date}】 {diary['content']}"
    elif keyword:
        results = search_diaries_by_keyword(keyword, limit=limit)
        if not results:
            return f"没有找到包含「{keyword}」的日记。"
        output = f"找到 {len(results)} 篇包含「{keyword}」的日记：\n"
        for r in results:
            output += f"\n- {r['date']}：{r['content'][:100]}...\n"
        return output
    else:
        results = get_recent_diaries(limit=limit)
        if not results:
            return "日记本还是空的，还没有写过日记。"
        output = f"最近 {len(results)} 篇日记：\n"
        for r in results:
            output += f"\n- {r['date']}：{r['content'][:100]}...\n"
        return output


def _write_diary(message_count: int = None, force: bool = False) -> str:
    """基于今日对话记录生成日记并保存。"""
    from datetime import datetime
    from config import get_diary_config
    from utils.diary import generate_diary_content, save_diary, has_diary_for_date

    msg_source = _brain_tools._diary_message_source
    if msg_source is None:
        return "无法获取聊天记录：日记消息源未设置。请从桌面端或QQ端调用此功能。"

    today_str = datetime.now().strftime("%Y-%m-%d")
    if not force and has_diary_for_date(today_str):
        return f"今天（{today_str}）已经有一篇日记了。如果你确实想重新生成，请明确告诉我'重新写日记'或'覆盖今天的日记'，我会帮你重写。"

    cfg = get_diary_config()
    max_msgs = message_count or cfg.get("max_messages", 30)
    direction = cfg.get("direction", "latest")

    messages = msg_source()
    if not messages:
        return "今天还没有任何聊天记录，无法生成日记。等聊了一会儿再试试吧～"

    if direction == "earliest":
        selected = messages[:max_msgs]
    else:
        selected = messages[-max_msgs:] if len(messages) > max_msgs else messages

    if not selected:
        return "今天还没有任何聊天记录，无法生成日记。"

    msgs_for_diary = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in selected]

    data = generate_diary_content(msgs_for_diary)
    if not data:
        return "日记生成失败，AI 返回的内容无法解析。可能网络不稳定，请稍后再试。"

    try:
        save_diary(
            date_str=today_str,
            content=data.get("content", ""),
            weather=data.get("weather", "⛅ 多云"),
            is_red_line=data.get("is_red_line", False),
            echo_text=data.get("echo_text", ""),
        )
    except Exception as e:
        return f"日记保存失败: {e}"

    weather = data.get("weather", "⛅ 多云")
    is_red = data.get("is_red_line", False)
    red_note = " 🔴红线日" if is_red else ""
    preview = data.get("content", "")[:200]
    return (
        f"日记已写好！{today_str} {weather}{red_note}\n\n"
        f"{preview}…\n\n"
        f"（完整日记已保存到日记本，可以说【指令】读日记来回顾）"
    )


def _read_note() -> str:
    from utils.note_manager import read_note as _read
    content = _read()
    if content.strip():
        return content
    return "备忘本当前是空的。"


def _organize_note() -> str:
    """使用 AI 整理备忘本内容"""
    from utils.note_manager import read_note, write_note
    import json
    from brain.agent import AgentCore

    old_content = read_note()
    if not old_content.strip():
        return "备忘本为空，无需整理。"

    prompt = f"""请整理以下备忘本内容，目标：
1. 删除重复行
2. 按主题归类（如果有多个主题）
3. 保持内容清晰、整洁，使用中文
4. 输出时只输出整理后的文本，不要添加额外解释。

备忘本内容：
{old_content}
"""

    try:
        agent = AgentCore()
        response = agent._call_api_with_retry([{"role": "user", "content": prompt}])
        new_content = response.choices[0].message.content.strip()
        if new_content and new_content != old_content:
            write_note(new_content)
            refresh_cb = _brain_tools._note_refresh_callback
            if refresh_cb:
                refresh_cb()
            return "已使用 AI 智能整理备忘本，内容已更新。"
        else:
            return "整理后内容无变化，未更新。"
    except Exception as e:
        return f"AI 整理失败：{e}"


TOOL_EXECUTORS = {
    "read_diary":     lambda inp: _read_diary(date=inp.get("date"), keyword=inp.get("keyword"), limit=inp.get("limit", 1)),
    "write_diary":    lambda inp: _write_diary(message_count=inp.get("message_count"), force=inp.get("force", False)),
    "read_note":      lambda inp: _read_note(),
    "organize_note":  lambda inp: _organize_note(),
}
