"""
心跳自检：对话结束后延迟 N 分钟，LLM 回顾对话 + 待办清单，检查遗漏事项。
灵感来自 NagaAgent DogTag 的心跳系统，适配莲心 PyQt5 单进程架构。
"""

import json
import uuid
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import litellm

from config import get_api_config, get_heartbeat_config

logger = logging.getLogger("Heartbeat")

_CHECKLIST_PATH = Path.home() / ".lianxin" / "heartbeat_checklist.json"

_HEARTBEAT_SYSTEM = """你是莲心AI的心跳自检助手。一轮对话刚刚结束，请你回顾以下内容：

1. **待办清单** — 是否有需要提醒用户的事项
2. **对话内容** — 用户是否提到了需要跟进、提醒、或未完成的事项

你的任务：
- 如果一切正常，无需任何提醒，**只回复 HEARTBEAT_OK**（不要加任何其他文字）
- 如果有需要提醒用户的事项，用莲心的语气简洁汇报（不超过200字），像朋友关心一样自然

你可以使用以下指令操作待办清单（每条指令独占一行，不会展示给用户）：
- [ADD_ITEM] 内容 — 新增一条待办事项
- [DONE_ITEM] 内容关键词 — 将匹配的待办条目标记为已完成

指令行之外的文本才是展示给用户的内容。"""

_HEARTBEAT_USER = "请执行心跳自检。审查待办清单和最近的对话记录，判断是否有需要提醒用户的事项。如无事则只回复 HEARTBEAT_OK。"


# ── 待办清单管理 ──────────────────────────────────────────

class HeartbeatChecklist:
    """持久化待办清单，存储在 ~/.lianxin/heartbeat_checklist.json"""

    def __init__(self):
        self._items: list[dict] = []
        self._load()

    def _load(self):
        try:
            if _CHECKLIST_PATH.exists():
                data = json.loads(_CHECKLIST_PATH.read_text(encoding="utf-8"))
                self._items = data.get("items", [])
            else:
                self._items = []
        except Exception:
            self._items = []

    def _save(self):
        _CHECKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "items": self._items,
        }
        _CHECKLIST_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, content: str) -> str:
        """添加待办事项，返回 ID。"""
        item = {
            "id": uuid.uuid4().hex[:12],
            "content": content.strip(),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "status": "pending",
        }
        self._items.append(item)
        self._save()
        return item["id"]

    def done(self, keyword: str) -> int:
        """将匹配关键词的待办事项标记为完成。返回标记数。"""
        count = 0
        for item in self._items:
            if item["status"] == "pending" and keyword.strip().lower() in item["content"].lower():
                item["status"] = "done"
                item["done_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                count += 1
        if count > 0:
            self._save()
        return count

    def get_pending(self) -> list[dict]:
        """获取所有未完成的待办事项。"""
        return [i for i in self._items if i["status"] == "pending"]

    def format_for_prompt(self) -> str:
        """格式化为 LLM prompt 可读文本。"""
        pending = self.get_pending()
        if not pending:
            return "（暂无待办事项）"
        lines = ["【当前待办清单】"]
        for i, item in enumerate(pending, 1):
            lines.append(f"  {i}. [{item['id']}] {item['content']}")
        return "\n".join(lines)


# ── 心跳执行器 ────────────────────────────────────────────

def perform_heartbeat(recent_messages: list[dict]) -> Optional[str]:
    """执行心跳自检。返回要展示给用户的文本，或 None（无需提醒）。"""
    cfg = get_heartbeat_config()
    if not cfg.get("enabled", True):
        return None

    if not recent_messages:
        return None

    # 构建最近对话文本
    lines = []
    for msg in recent_messages[-30:]:  # 最多取最近 30 条
        role = "用户" if msg.get("role") == "user" else "莲心"
        content = msg.get("content", "")
        if content:
            lines.append(f"[{role}]: {content}")
    conversation_text = "\n".join(lines)
    if len(conversation_text) < 50:
        return None

    # 待办清单
    checklist = HeartbeatChecklist()
    checklist_text = checklist.format_for_prompt()

    # LLM 调用
    from config import normalize_model_for_litellm
    api_cfg = get_api_config()
    model = normalize_model_for_litellm(
        api_cfg.get("model", "deepseek-v4-flash"),
        api_cfg.get("base_url", ""),
    )

    system_text = _HEARTBEAT_SYSTEM
    user_text = f"{_HEARTBEAT_USER}\n\n{checklist_text}\n\n【最近对话记录】\n{conversation_text[:4000]}"

    try:
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ],
            api_key=api_cfg["api_key"],
            api_base=api_cfg["base_url"],
            temperature=0.3,
            max_tokens=400,
            timeout=30,
        )
        raw = response.choices[0].message.content or ""
    except Exception as e:
        error_msg = str(e).lower()
        is_retryable = any(kw in error_msg for kw in [
            "timeout", "connection", "getaddrinfo", "name or service not known",
            "rate limit", "server", "500", "502", "503", "504",
        ])
        if is_retryable:
            import time as _time
            print(f"[心跳] 首次调用失败，3秒后重试: {e}", flush=True)
            _time.sleep(3.0)
            try:
                response = litellm.completion(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_text},
                        {"role": "user", "content": user_text},
                    ],
                    api_key=api_cfg["api_key"],
                    api_base=api_cfg["base_url"],
                    temperature=0.3,
                    max_tokens=400,
                    timeout=30,
                )
                raw = response.choices[0].message.content or ""
            except Exception as e2:
                logger.warning(f"心跳自检 LLM 调用失败（重试后仍失败）: {e2}")
                return None
        else:
            logger.warning(f"心跳自检 LLM 调用失败: {e}")
            return None

    # 解析指令
    result_text = _parse_checklist_commands(raw, checklist)

    # 判断是否静默
    stripped = result_text.strip()
    if not stripped:
        return None
    if "HEARTBEAT_OK" in stripped and len(stripped) <= cfg.get("ack_max_chars", 300):
        return None

    return stripped


def _parse_checklist_commands(raw: str, checklist: HeartbeatChecklist) -> str:
    """从 LLM 回复中解析 [ADD_ITEM] / [DONE_ITEM] 指令，返回纯文本。"""
    clean_lines = []
    for line in raw.split("\n"):
        add_match = re.match(r"\[ADD_ITEM\]\s*(.+)", line.strip(), re.IGNORECASE)
        done_match = re.match(r"\[DONE_ITEM\]\s*(.+)", line.strip(), re.IGNORECASE)

        if add_match:
            content = add_match.group(1).strip()
            if content:
                cid = checklist.add(content)
                logger.info(f"心跳自检: 新增待办 [{cid}] {content[:60]}")
            continue

        if done_match:
            keyword = done_match.group(1).strip()
            if keyword:
                n = checklist.done(keyword)
                logger.info(f"心跳自检: 标记完成 {n} 条待办 (关键词: {keyword})")
            continue

        clean_lines.append(line)

    return "\n".join(clean_lines).strip()