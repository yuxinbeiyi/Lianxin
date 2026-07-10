"""System Prompt 技能模块加载器。

实现「渐进式披露」：根据用户消息匹配关键词，按需注入技能模块。
"""
import re
from pathlib import Path

_SKILLS_DIR = Path(__file__).parent
_cache: dict[str, dict] = {}


def _load_all():
    """扫描目录，解析所有 .md 文件的 YAML frontmatter，缓存结果。"""
    if _cache:
        return
    for md_file in sorted(_SKILLS_DIR.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', text, re.DOTALL)
        if not match:
            continue
        frontmatter, body = match.group(1), match.group(2)
        triggers = []
        for line in frontmatter.split("\n"):
            if ":" in line:
                key, _, val = line.partition(":")
                if key.strip() == "triggers":
                    triggers = re.findall(r'"([^"]*)"', val)
        _cache[md_file.stem] = {"triggers": triggers, "content": body.strip()}


def get_matching_modules(user_message: str) -> str:
    """根据用户消息返回匹配的技能模块，用双换行拼接。"""
    _load_all()
    if not user_message:
        return ""
    parts = []
    for info in _cache.values():
        if any(t in user_message for t in info["triggers"]):
            parts.append(info["content"])
    return "\n\n".join(parts)
