"""将不可编辑策略、人格、场景和动态上下文组合为可审计 Prompt。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from brain.persona.models import PersonaProfile, PersonaSnapshot


@dataclass(frozen=True)
class PromptLayer:
    name: str
    content: str
    editable: bool = False


@dataclass(frozen=True)
class CompiledPrompt:
    persona_id: str
    persona_revision: int
    layers: tuple[PromptLayer, ...]

    def as_messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": layer.content}
            for layer in self.layers
            if layer.content.strip()
        ]

    @property
    def text(self) -> str:
        return "\n\n".join(
            f"【{layer.name}】\n{layer.content.strip()}"
            for layer in self.layers
            if layer.content.strip()
        )

    @property
    def estimated_tokens(self) -> int:
        # 仅供未来 UI 预览；中英文混排采用保守近似，不参与实际计费。
        return max(1, len(self.text) // 2)


class PersonaPromptComposer:
    """纯函数式编排器，不读文件、不持有全局状态。"""

    _FIELD_LABELS = (
        ("summary", "角色摘要"),
        ("identity", "身份与背景"),
        ("appearance", "外貌设定"),
        ("personality", "性格设定"),
        ("speaking_style", "语言风格"),
        ("habits", "行为习惯"),
        ("relationship", "与用户的关系"),
        ("user_address", "对用户的称呼"),
        ("boundaries", "表达边界"),
        ("custom_instructions", "补充人格指令"),
    )

    @classmethod
    def render_persona(cls, profile: PersonaProfile, user_name: str) -> str:
        replacements = {
            "{user_name}": user_name,
            "{assistant_name}": profile.assistant_name,
        }

        def render(value: str) -> str:
            for source, target in replacements.items():
                value = value.replace(source, target)
            return value.strip()

        sections = [f"你的名字是“{profile.assistant_name}”。"]
        for field, label in cls._FIELD_LABELS:
            content = render(getattr(profile, field))
            if content:
                sections.append(f"【{label}】\n{content}")
        return "\n\n".join(sections)

    @classmethod
    def render_persona_compact(cls, profile: PersonaProfile, user_name: str) -> str:
        """日常聊天运行版：保留身份、性格、关系和硬边界，省略重复细节。"""
        replacements = {"{user_name}": user_name, "{assistant_name}": profile.assistant_name}

        def render(value: str) -> str:
            result = str(value or "")
            for source, target in replacements.items():
                result = result.replace(source, target)
            return result.strip()

        sections = [f"你的名字是“{profile.assistant_name}”。"]
        for field, label in (
            ("summary", "角色摘要"), ("identity", "身份"),
            ("personality", "性格"), ("speaking_style", "语言风格"),
            ("relationship", "与用户的关系"), ("user_address", "称呼"),
            ("boundaries", "硬边界"), ("custom_instructions", "补充约束"),
        ):
            content = render(getattr(profile, field))
            if content:
                sections.append(f"【{label}】\n{content}")
        return "\n\n".join(sections)

    @classmethod
    def compose(
        cls,
        snapshot: PersonaSnapshot,
        *,
        user_name: str,
        core_policy: str,
        scene_policy: str = "",
        dynamic_context: Iterable[str] = (),
        compact: bool = False,
    ) -> CompiledPrompt:
        layers: list[PromptLayer] = [
            PromptLayer(
                "人格设定",
                (cls.render_persona_compact(snapshot.profile, user_name)
                 if compact else cls.render_persona(snapshot.profile, user_name)),
                editable=True,
            )
        ]
        if scene_policy.strip():
            layers.append(PromptLayer("场景规则", scene_policy.strip()))
        for index, content in enumerate(dynamic_context, start=1):
            if content and content.strip():
                layers.append(PromptLayer(f"动态上下文 {index}", content.strip()))
        from brain.persona.authority import persona_authority_policy
        layers.append(PromptLayer(
            "人格档案权威边界",
            persona_authority_policy(snapshot.profile.assistant_name),
        ))
        # 核心策略单独成层并置于最后，未来 UI 无法通过编辑人格删除它。
        if core_policy.strip():
            layers.append(PromptLayer("不可编辑的系统规则", core_policy.strip()))
        return CompiledPrompt(
            persona_id=snapshot.profile.id,
            persona_revision=snapshot.revision,
            layers=tuple(layers),
        )
