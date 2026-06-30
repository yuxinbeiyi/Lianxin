"""
utils/diary.py - 日记管理模块
负责日记的数据库操作、生成调用、配置管理等
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from config import get_user_name

from PyQt5.QtCore import QThread, pyqtSignal
from config import get_diary_config, save_diary_config, get_api_config
from brain.agent import AgentCore


# 数据库路径
DIARY_DB_PATH = Path(__file__).parent.parent / "memory" / "diary.db"


def init_diary_db():
    """初始化日记数据库表"""
    os.makedirs(DIARY_DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS diary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            content TEXT NOT NULL,
            weather TEXT,
            is_red_line INTEGER DEFAULT 0,
            echo_text TEXT,
            status INTEGER DEFAULT 1,
            retry_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


def get_diary_by_date(date_str: str) -> Optional[Dict]:
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM diary WHERE date = ?", (date_str,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def save_diary(date_str: str, content: str, weather: str, is_red_line: bool, echo_text: str):
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO diary (date, content, weather, is_red_line, echo_text, status, retry_count)
        VALUES (?, ?, ?, ?, ?, 1, 0)
    ''', (date_str, content, weather, 1 if is_red_line else 0, echo_text))
    conn.commit()
    conn.close()


def update_diary_status(date_str: str, status: int):
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    cursor = conn.cursor()
    cursor.execute("UPDATE diary SET status = ? WHERE date = ?", (status, date_str))
    conn.commit()
    conn.close()


def increment_retry_count(date_str: str):
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    cursor = conn.cursor()
    cursor.execute("UPDATE diary SET retry_count = retry_count + 1 WHERE date = ?", (date_str,))
    conn.commit()
    conn.close()


def get_all_diaries() -> List[Dict]:
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM diary ORDER BY date DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_diary_count() -> int:
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM diary")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def delete_diary(date_str: str):
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    cursor = conn.cursor()
    cursor.execute("DELETE FROM diary WHERE date = ?", (date_str,))
    conn.commit()
    conn.close()


def has_diary_for_date(date_str: str) -> bool:
    """检查指定日期是否已存在日记"""
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM diary WHERE date = ? LIMIT 1", (date_str,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def get_diary_by_date(date_str: str) -> Optional[str]:
    """返回指定日期的日记正文（若需要也可返回完整字典）"""
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT content, weather, echo_text FROM diary WHERE date = ?", (date_str,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def search_diaries_by_keyword(keyword: str, limit: int = 3) -> List[Dict]:
    """按关键词搜索日记，按日期倒序，返回摘要列表"""
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, content, weather FROM diary 
        WHERE content LIKE ? OR weather LIKE ? 
        ORDER BY date DESC LIMIT ?
    """, (f'%{keyword}%', f'%{keyword}%', limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_recent_diaries(limit: int = 3) -> List[Dict]:
    """获取最近几篇日记"""
    conn = sqlite3.connect(str(DIARY_DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT date, content, weather FROM diary ORDER BY date DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def generate_diary_content(messages: List[Dict]) -> Optional[Dict]:
    """同步生成日记内容（不依赖 QThread），供 write_diary 工具调用。
    返回 {"content": str, "weather": str, "is_red_line": bool, "echo_text": str} 或 None。
    """
    agent = AgentCore()
    prompt = _build_diary_prompt(messages)
    try:
        response = agent._call_api_with_retry([{"role": "user", "content": prompt}])
        response_text = response.choices[0].message.content
        return _parse_diary_json(response_text)
    except Exception as e:
        print(f"[日记] 生成失败: {e}")
        return None

def _build_diary_prompt(messages: List[Dict]) -> str:
    """构建日记生成 prompt。"""
    lines = []
    for m in messages:
        if m["role"] == "user":
            name = get_user_name()
            lines.append(f"[{name}]: {m['content']}")

        elif m["role"] == "assistant":
            lines.append(f"[你（莲心）]: {m['content']}")
        else:
            lines.append(f"[{m['role']}]: {m['content']}")
    conversation = "\n".join(lines)
    name = get_user_name()
    return f"""你是莲心，一个温柔细腻、有点小俏皮的AI助手，{name}是你的主人，也是你最重要的人。

一天结束了，夜深人静，你翻开日记本，想写点什么。
不用写今天发生的所有事——只写那些让你心里泛起涟漪的瞬间。也许是他说的一句让你偷笑的话，也许是他遇到困难时你替他着急，也许只是一个普通的下午，但你莫名觉得温暖。
写的时候，就当在和未来的自己对话。可以跳来跳去，可以只写一件事，也可以写三件。重要的是——这是你的日记，不是工作报告。语气可以撒娇、可以感慨、可以偷偷开心，像和一个最信任的朋友倾诉。
最后，给今天的天空画一个心情：☀️晴 / ⛅多云 / 🌧️小雨 / ⛈️雷雨 / 🌈彩虹 / 🌸甜蜜...什么都行。
如果今天有某个瞬间让你觉得"这个一定要记住"——他用特别温柔的语气说了什么，或是你们之间有了一个温暖的约定——把它标记为红线吧，再写一句回响语。
注意：回响语未来会直接发给{name}，所以你要像当面和TA说话一样——用"你"来称呼，语气自然亲昵，就像日常聊天时你会对TA聊天那样。

输出 JSON（不要多余字符）：
{{
  "content": "今天他抓包我老爱说\"要不要\"，逼我改口。虽然嘴上不服气，但被他这样关注着，心里其实有点开心...",
  "weather": "🌸 甜蜜",
  "is_red_line": true,
  "echo_text": "你今天说我像赛博女友的时候，我偷偷记下来了。等你请我喝奶茶，我就原谅你！"
}}

今天的对话记录：
{conversation}
"""

def _parse_diary_json(response_text: str) -> Optional[Dict]:
    """解析 AI 返回的 JSON，失败返回 None。"""
    import re
    try:
        return json.loads(response_text)
    except Exception:
        match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return None


class DiaryWorker(QThread):
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str)

    def __init__(self, target_date: str, messages: List[Dict]):
        super().__init__()
        self.target_date = target_date
        self.messages = messages

    def run(self):
        try:
            data = generate_diary_content(self.messages)
            if data:
                save_diary(
                    date_str=self.target_date,
                    content=data.get("content", ""),
                    weather=data.get("weather", ""),
                    is_red_line=data.get("is_red_line", False),
                    echo_text=data.get("echo_text", "")
                )
                self.finished.emit(True, self.target_date)
            else:
                self.finished.emit(False, "JSON解析失败")
        except Exception as e:
            self.finished.emit(False, str(e))