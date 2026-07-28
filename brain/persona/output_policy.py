"""对已激活人格声明的可机械校验格式做最终收口。"""

from __future__ import annotations

import re

from brain.persona.models import PersonaSnapshot


_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF]|[\u2600-\u27BF]|[\uFE00-\uFE0F]"
)


def sanitize_persona_output(text: str, snapshot: PersonaSnapshot | None) -> str:
    value = str(text or "")
    if snapshot is None or not snapshot.enabled:
        return value
    profile = snapshot.profile
    rules = "\n".join((profile.boundaries, profile.custom_instructions)).lower()

    if any(token in rules for token in (
        "不使用 unicode emoji", "禁止使用 unicode emoji", "不用 unicode emoji",
        "不使用emoji", "禁止使用emoji",
    )):
        value = _EMOJI_RE.sub("", value)

    if any(token in rules for token in (
        "不使用 markdown", "禁止使用 markdown", "不用 markdown",
        "不使用markdown", "禁止使用markdown",
        "不使用 markdown 标题", "星号加粗",
    )):
        value = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", value)
        value = re.sub(r"(?m)^\s*(?:-{3,}|_{3,}|\*{3,})\s*$", "", value)
        value = re.sub(r"(?m)^\s*>\s?", "", value)
        value = value.replace("**", "").replace("__", "")

    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()
