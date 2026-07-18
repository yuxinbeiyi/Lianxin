"""人格档案的数据模型与校验规则。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping


PERSONA_SCHEMA_VERSION = 1
DEFAULT_PERSONA_ID = "default-lianxin"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHORT_FIELD_LIMIT = 120
_TEXT_FIELD_LIMIT = 20_000
_TOTAL_TEXT_LIMIT = 60_000


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PersonaValidationError(ValueError):
    """人格档案内容不合法。"""

    def __init__(self, errors: list[str]):
        self.errors = tuple(errors)
        super().__init__("；".join(errors))


@dataclass(frozen=True)
class PersonaProfile:
    """可持久化的人格档案；实例不可变，适合作为并发请求快照。"""

    id: str
    profile_name: str
    assistant_name: str
    summary: str = ""
    identity: str = ""
    appearance: str = ""
    personality: str = ""
    speaking_style: str = ""
    habits: str = ""
    relationship: str = ""
    user_address: str = "{user_name}"
    boundaries: str = ""
    custom_instructions: str = ""
    is_builtin: bool = False
    schema_version: int = PERSONA_SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PersonaProfile":
        if not isinstance(data, Mapping):
            raise PersonaValidationError(["人格文件必须是 JSON 对象"])
        version = data.get("schema_version", PERSONA_SCHEMA_VERSION)
        if version != PERSONA_SCHEMA_VERSION:
            raise PersonaValidationError([
                f"不支持的人格版本 {version}，当前版本为 {PERSONA_SCHEMA_VERSION}"
            ])

        text_fields = (
            "id", "profile_name", "assistant_name", "summary", "identity",
            "appearance", "personality", "speaking_style", "habits",
            "relationship", "user_address", "boundaries",
            "custom_instructions", "created_at", "updated_at",
        )
        values = {name: str(data.get(name, "") or "") for name in text_fields}
        profile = cls(
            **values,
            is_builtin=bool(data.get("is_builtin", False)),
            schema_version=version,
        )
        profile.validate()
        return profile

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        errors: list[str] = []
        if not _ID_PATTERN.fullmatch(self.id):
            errors.append("人格 ID 只能包含字母、数字、点、下划线和连字符")
        if not self.profile_name.strip():
            errors.append("人格档案名称不能为空")
        elif len(self.profile_name) > _SHORT_FIELD_LIMIT:
            errors.append(f"人格档案名称不能超过 {_SHORT_FIELD_LIMIT} 字符")
        if not self.assistant_name.strip():
            errors.append("助手名称不能为空")
        elif len(self.assistant_name) > _SHORT_FIELD_LIMIT:
            errors.append(f"助手名称不能超过 {_SHORT_FIELD_LIMIT} 字符")

        long_fields = (
            "summary", "identity", "appearance", "personality",
            "speaking_style", "habits", "relationship", "user_address",
            "boundaries", "custom_instructions",
        )
        total = 0
        for name in long_fields:
            value = getattr(self, name)
            total += len(value)
            if len(value) > _TEXT_FIELD_LIMIT:
                errors.append(f"字段 {name} 不能超过 {_TEXT_FIELD_LIMIT} 字符")
        if total > _TOTAL_TEXT_LIMIT:
            errors.append(f"人格文本总长度不能超过 {_TOTAL_TEXT_LIMIT} 字符")
        if errors:
            raise PersonaValidationError(errors)

    def updated(self, **changes: Any) -> "PersonaProfile":
        """返回带新更新时间的副本，原快照保持不变。"""
        profile = replace(self, **changes, updated_at=utc_now_iso())
        profile.validate()
        return profile


@dataclass(frozen=True)
class PersonaSnapshot:
    """一次请求使用的人格快照。"""

    profile: PersonaProfile
    revision: int
    enabled: bool
    activated_at: str

