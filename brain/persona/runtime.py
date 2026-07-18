"""供独立 Worker 使用的人格运行时适配层。"""

from __future__ import annotations

from brain.persona.composer import PersonaPromptComposer
from brain.persona.models import PersonaSnapshot


_LEGACY_IDENTITY_PREFIXES = (
    "你是莲心，一个聪明、温柔但偶尔有点毒舌的AI助手。",
    "你是莲心，一个温柔细腻的AI助手。",
    "你是莲心，一个温柔细腻、有点小俏皮的AI助手，",
    "你是莲心，刚刚通过肩载摄像头看了一眼周围环境。",
)


def capture_persona_snapshot() -> PersonaSnapshot | None:
    """为一项后台生成任务捕获一次快照；失败时由调用方走旧 Prompt。"""
    try:
        from brain.persona.manager import get_persona_manager
        return get_persona_manager().get_snapshot()
    except Exception:
        return None


def active_assistant_name(snapshot: PersonaSnapshot | None, default: str = "莲心") -> str:
    if snapshot is not None and snapshot.enabled:
        return snapshot.profile.assistant_name
    return default


def compose_scene_prompt(
    legacy_template: str,
    *,
    user_name: str,
    snapshot: PersonaSnapshot | None,
) -> str:
    """启用人格时用统一人格替换旧身份；关闭时逐字保留旧模板语义。"""
    legacy = legacy_template.replace("{user_name}", user_name)
    if snapshot is None or not snapshot.enabled:
        return legacy

    scene = legacy.strip()
    for prefix in _LEGACY_IDENTITY_PREFIXES:
        if scene.startswith(prefix):
            scene = scene[len(prefix):].lstrip(" ，,\n")
            break
    scene = scene.replace("莲心", snapshot.profile.assistant_name)
    compiled = PersonaPromptComposer.compose(
        snapshot,
        user_name=user_name,
        core_policy="",
        scene_policy=scene,
    )
    return compiled.text

