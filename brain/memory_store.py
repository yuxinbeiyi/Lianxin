"""
memory_store.py — 莲心AI 分类记忆存储引擎

记忆类型（分类）：
  profile      — 个人档案（姓名、外貌、性格、背景故事等稳定信息）
  preferences  — 偏好（喜欢的音乐、游戏、食物、颜色等）
  events       — 事件（过去发生的事、经历、计划）
  knowledge    — 知识（路径配置、工作原理、规则等事实）
  behaviors    — 行为模式（沟通风格、习惯、互动偏好）
  skills       — 技能（莲心学会的能力、工具使用经验）

数据结构（long_term.json v2）：
{
  "version": 2,
  "profile": [
    {
      "id": "uuid",
      "content": "事实文本",
      "source": "user_saved | auto_extracted",
      "created_at": "2026-05-15",
      "strength": 1
    }
  ],
  ...
  "updated_at": "2026-05-15 10:00"
}
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

# 支持的记忆分类
MEMORY_CATEGORIES = Literal[
    "profile", "preferences", "events", "knowledge", "behaviors", "skills"
]
ALL_CATEGORIES: list[str] = [
    "profile", "preferences", "events", "knowledge", "behaviors", "skills"
]

# 各分类的中文描述（用于 LLM 提取和分类）
CATEGORY_DESCRIPTIONS = {
    "profile": "个人档案：用户的姓名、年龄、外貌、性格、职业、背景故事等长期稳定的个人信息",
    "preferences": "偏好：用户喜欢的音乐、游戏、食物、颜色、动漫、风格等喜好信息",
    "events": "事件：用户过去经历的事、旅行、比赛、重要日期、未来的计划等",
    "knowledge": "知识：路径配置、工作原理、规则、使用方法等客观事实",
    "behaviors": "行为模式：沟通风格偏好、习惯、互动方式、期望的回应方式等",
    "skills": "技能：莲心学会的能力、工具使用经验、新掌握的领域知识",
}


def _get_memory_path() -> Path:
    """获取 long_term.json 的路径。"""
    from utils.paths import get_user_data_dir
    return get_user_data_dir() / "long_term.json"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ── 读写 ────────────────────────────────────────────────

def load() -> dict[str, Any]:
    """加载 long_term.json，返回完整数据字典。"""
    path = _get_memory_path()
    if not path.exists():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, Exception):
        return _empty_store()

    # 检测 v1 旧格式（含 "facts" 列表），触发迁移
    if "facts" in data and isinstance(data["facts"], list):
        data = _migrate_v1_to_v2(data)
        _save_raw(data)

    # 确保 v2 的必要字段存在
    if not isinstance(data.get("version"), int) or data.get("version") < 2:
        data = _empty_store()

    for cat in ALL_CATEGORIES:
        if cat not in data or not isinstance(data[cat], list):
            data[cat] = []

    return data


def _save_raw(data: dict[str, Any]) -> None:
    """直接写入 long_term.json。"""
    path = _get_memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _empty_store() -> dict[str, Any]:
    return {
        "version": 2,
        "updated_at": _now_str(),
        **{cat: [] for cat in ALL_CATEGORIES},
    }


# ── 迁移 ────────────────────────────────────────────────

def _migrate_v1_to_v2(old_data: dict[str, Any]) -> dict[str, Any]:
    """
    将 v1 格式（扁平 facts 列表）迁移到 v2 格式。
    每条事实先用关键词启发式分类，未匹配的暂归为 "knowledge"。
    """
    store = _empty_store()
    old_facts = old_data.get("facts", [])

    keyword_map: list[tuple[list[str], str]] = [
        # 顺序很重要：更具体的规则在前
        (["莲心"], "profile"),          # 关于莲心自身设定的信息
        (["生日", "年龄", "岁"], "profile"),
        (["姓名", "名字", "昵称", "笔名", "性别", "男生", "女生"], "profile"),
        (["外貌", "长相", "戴", "穿", "头发", "瞳孔", "眼镜"], "profile"),
        (["性格", "个性", "喜欢思考", "喜欢阅读", "梦想"], "profile"),
        (["小说", "写作", "笔名"], "profile"),

        (["喜欢", "最爱", "偏好", "爱好"], "preferences"),
        (["动漫", "游戏", "音乐", "歌曲", "纯音乐", "口琴", "插画"], "preferences"),
        (["Steam", "Epic", "网易云"], "preferences"),
        (["命运石之门", "狼与香辛料"], "preferences"),

        (["路径", "位于", "保存在", "目录"], "knowledge"),
        (".exe", "knowledge"),
        (["配置文件", "配置"], "knowledge"),

        (["答辩", "毕业", "论文", "初辩", "二辩"], "events"),
        (["比赛", "竞赛", "获奖", "二等奖", "三等奖"], "events"),
        (["旅行", "去过", "分手", "交往", "表白"], "events"),
        (["2024年", "2025年", "2026年"], "events"),
        (["发售", "销量"], "events"),

        (["希望", "期待", "批准", "允许", "授权"], "behaviors"),
        (["不要", "禁止", "不准", "不能", "不得"], "behaviors"),
        (["风格", "语气", "称呼"], "behaviors"),
        (["记得", "提醒", "建议"], "behaviors"),
        (["简短", "缩短"], "behaviors"),
        (["不用称呼", "不必称呼"], "behaviors"),
    ]

    unmapped: list[str] = []

    for fact in old_facts:
        fact_lower = fact.lower()
        matched = False
        for keywords, category in keyword_map:
            if any(kw.lower() in fact_lower for kw in keywords):
                store[category].append({
                    "id": _new_id(),
                    "content": fact,
                    "source": "migrated",
                    "created_at": _today_str(),
                    "strength": 1,
                })
                matched = True
                break
        if not matched:
            unmapped.append(fact)

    # 未匹配的归为 knowledge
    for fact in unmapped:
        store["knowledge"].append({
            "id": _new_id(),
            "content": fact,
            "source": "migrated",
            "created_at": _today_str(),
            "strength": 1,
        })

    # 记录迁移统计
    store["_migration_info"] = {
        "total": len(old_facts),
        "mapped": len(old_facts) - len(unmapped),
        "date": _now_str(),
    }

    return store


# ── 查询 ────────────────────────────────────────────────

def search(keyword: str, category: str | None = None) -> list[dict[str, Any]]:
    """
    在所有分类（或指定分类）中搜索包含关键词的记忆条目。
    返回匹配条目列表，按 strength 降序排列。
    """
    data = load()
    keyword_lower = keyword.strip().lower()
    if not keyword_lower:
        return []

    candidates: list[dict[str, Any]] = []
    cats = [category] if category else ALL_CATEGORIES

    for cat in cats:
        for item in data.get(cat, []):
            if keyword_lower in item.get("content", "").lower():
                candidates.append({**item, "_category": cat})

    candidates.sort(key=lambda x: x.get("strength", 1), reverse=True)
    return candidates


def search_by_category(category: str) -> list[dict[str, Any]]:
    """获取指定分类下的所有条目。"""
    data = load()
    return data.get(category, [])


def get_all() -> dict[str, list[dict[str, Any]]]:
    """获取全部分类的所有条目（不含元数据）。"""
    data = load()
    return {cat: data.get(cat, []) for cat in ALL_CATEGORIES}


def _prune_category(data: dict[str, Any], category: str) -> None:
    """
    如果 category 的条目数超出上限，淘汰最旧且强度最低的条目。
    上限从配置读取，默认 200。
    """
    try:
        from config import get_memory_config
        cfg = get_memory_config()
        max_items = cfg.get("max_items_per_category", 200)
    except Exception:
        max_items = 200

    items = data.get(category, [])
    if len(items) <= max_items:
        return

    # 按 (strength, created_at) 升序排序：强度低且旧的优先淘汰
    excess = len(items) - max_items
    items.sort(key=lambda x: (x.get("strength", 1), x.get("created_at", "")))
    # 只移除 excess 条
    kept = items[excess:]
    # 恢复原有顺序（按创建时间升序）
    kept.sort(key=lambda x: x.get("created_at", ""))
    data[category] = kept


# ── 写入 ────────────────────────────────────────────────

def add(content: str, category: str = "knowledge",
        source: str = "user_saved") -> str:
    """添加一条新记忆到指定分类。返回条目 ID。"""
    data = load()

    if category not in ALL_CATEGORIES:
        category = "knowledge"

    # 去重检查：同分类下完全相同的 content 不重复添加，只增强 strength
    for item in data[category]:
        if item.get("content", "").strip() == content.strip():
            item["strength"] = item.get("strength", 1) + 1
            item["source"] = source
            data["updated_at"] = _now_str()
            _save_raw(data)
            return item["id"]

    entry = {
        "id": _new_id(),
        "content": content.strip(),
        "source": source,
        "created_at": _today_str(),
        "strength": 1,
    }
    data[category].append(entry)

    # 检查该分类是否超出上限，超出则淘汰最旧的最低强度条目
    _prune_category(data, category)

    data["updated_at"] = _now_str()
    _save_raw(data)
    return entry["id"]


def update(old_keyword: str, new_content: str,
           category: str | None = None) -> int:
    """
    更新包含 old_keyword 的记忆条目。
    如果指定 category，只在该分类下搜索。
    返回更新的条目数；如果没找到，将 new_content 作为新记忆添加。
    """
    data = load()
    keyword_lower = old_keyword.strip().lower()
    if not keyword_lower:
        return 0

    cats = [category] if category else ALL_CATEGORIES
    updated = 0

    for cat in cats:
        for item in data[cat]:
            if keyword_lower in item.get("content", "").lower():
                item["content"] = new_content.strip()
                item["source"] = "user_saved"
                data["updated_at"] = _now_str()
                updated += 1

    if updated > 0:
        _save_raw(data)
    else:
        # 没找到，作为新记忆添加
        add(new_content, category or "knowledge", source="user_saved")
        # 返回 0 表示是新增而不是更新
        # 但为了语义清晰，返回 0 表示未找到

    return updated


def delete(keyword: str, category: str | None = None) -> int:
    """
    删除包含 keyword 的记忆条目。
    如果指定 category，只在该分类下删除。
    返回删除的条目数。
    """
    data = load()
    keyword_lower = keyword.strip().lower()
    if not keyword_lower:
        return 0

    cats = [category] if category else ALL_CATEGORIES
    deleted = 0

    for cat in cats:
        before = len(data[cat])
        data[cat] = [
            item for item in data[cat]
            if keyword_lower not in item.get("content", "").lower()
        ]
        deleted += before - len(data[cat])

    if deleted > 0:
        data["updated_at"] = _now_str()
        _save_raw(data)

    return deleted


# ── 工具层封装（供 tools.py 调用） ─────────────────────

def format_search_result(matches: list[dict[str, Any]]) -> str:
    """将搜索结果格式化为可读文本。"""
    if not matches:
        return "未找到匹配的记忆。"

    lines = [f"找到 {len(matches)} 条相关记忆："]
    for i, m in enumerate(matches, 1):
        cat = m.get("_category", "unknown")
        source = m.get("source", "user_saved")
        strength = m.get("strength", 1)
        lines.append(f"{i}. [{cat}] {m['content']} (强度:{strength}, 来源:{source})")
    return "\n".join(lines)


def format_all_memories() -> str:
    """格式化输出全部记忆（用于 LLM 查看）。"""
    data = load()
    lines = []
    for cat in ALL_CATEGORIES:
        items = data.get(cat, [])
        if items:
            lines.append(f"\n【{cat} ({CATEGORY_DESCRIPTIONS.get(cat, '')})】")
            for item in items:
                src = "自动" if item.get("source") == "auto_extracted" else "手动"
                lines.append(f"  · {item['content']} (强度:{item.get('strength', 1)}, {src})")
    if len(lines) == 0:
        return "还没有任何记忆。"
    return "\n".join(lines)


# ── 自动提取 ────────────────────────────────────────────

def build_extraction_prompt(recent_conversation: str) -> str:
    """
    构建用于自动记忆提取的 prompt。
    让 LLM 分析最近的对话，提取值得记住的信息。
    """
    cat_desc = "\n".join(f"  - {k}：{v}" for k, v in CATEGORY_DESCRIPTIONS.items())

    return f"""分析以下最近的对话内容，从中提取值得长期记忆的信息。

## 记忆分类说明
{cat_desc}

## 提取规则
1. 只提取用户明确表达的稳定事实，不要从你自己的回复中提取
2. 不要记录临时状态（如"今天天气好"、"我现在很累"等一次性信息）
3. 每条记忆应该自我完整，脱离上下文也能理解
4. 如果某条信息与已有记忆相似，可以合并或强化（在 review 中注明）
5. 宁少勿多：没有值得记的就不记

## 输出格式（JSON）
{{
    "memories": [
        {{
            "category": "profile|preferences|events|knowledge|behaviors|skills",
            "content": "完整的记忆文本",
            "reason": "为什么这条信息值得记住"
        }}
    ]
}}

如果没有值得记忆的内容，返回 {{"memories": []}}。

## 对话内容
{recent_conversation}
"""


def extract_auto(messages: list[dict[str, str]],
                 llm_client: Any, model: str) -> list[dict[str, str]]:
    """
    调用 LLM 从 messages 中自动提取记忆。
    messages 是 OpenAI 格式的消息列表（含 user 和 assistant 角色）。
    返回提取到的记忆列表 [{"category": "...", "content": "..."}, ...]
    """
    # 拼接对话文本
    lines = []
    for msg in messages:
        role = "用户" if msg.get("role") == "user" else "莲心"
        content = msg.get("content", "")
        if content:
            lines.append(f"[{role}]: {content}")

    conversation_text = "\n".join(lines)
    if len(conversation_text) < 20:
        return []  # 对话太短，不提取

    prompt = build_extraction_prompt(conversation_text)

    try:
        response = llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的记忆提取助手，从对话中提取值得长期记住的信息。"},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=30,
        )
        raw = response.choices[0].message.content or "{}"
        result = json.loads(raw)
        memories = result.get("memories", [])
        return memories
    except Exception:
        return []
