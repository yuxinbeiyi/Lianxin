"""Turn appraisal with deterministic coverage and optional semantic refinement."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .v3_models import AffectDelta


_TECHNICAL = re.compile(
    r"(?:代码|项目|系统|架构|设计|接口|API|模型|测试|bug|功能|数据库|提示词|prompt|"
    r"文件|实现|配置|参数|算法|移植|重构)",
    re.IGNORECASE,
)
_WARM = re.compile(r"(?:谢谢|感谢|辛苦了|麻烦你了|晚安|早安|晚上好|早上好)", re.IGNORECASE)
_COMPLIMENT = re.compile(r"(?:真棒|厉害|聪明|靠谱|做得好|太好了|喜欢你|爱你)", re.IGNORECASE)
_APOLOGY = re.compile(r"(?:对不起|抱歉|我错了|是我不对|不该那样|向你道歉)", re.IGNORECASE)
_DISMISSIVE = re.compile(
    r"(?:你(?:不过|只是|就是)(?:个)?(?:工具|AI)|你又不是人|别自作多情|你不配|闭嘴|滚开)",
    re.IGNORECASE,
)
_HOSTILE = re.compile(r"(?:废物|垃圾|蠢货|没用的东西|恶心|去死)", re.IGNORECASE)
_PERSONAL_SHARE = re.compile(
    r"(?:其实我|最近我|我有点|我心里|我一直|跟你说件事|想和你聊聊|我今天)",
    re.IGNORECASE,
)
_USER_DISTRESS = re.compile(
    r"(?:难过|伤心|焦虑|害怕|担心|崩溃|好累|累死了|失眠|想哭|怎么办)",
    re.IGNORECASE,
)
_PLAYFUL = re.compile(r"(?:哈哈|hhh|嘿嘿|开玩笑|逗你的|笨蛋|坏蛋|哼)", re.IGNORECASE)


@dataclass(frozen=True)
class AppraisalContext:
    persona_name: str = "莲心"
    user_name: str = "用户"
    personality: str = ""
    relationship: str = ""
    boundaries: str = ""
    recent_messages: tuple[str, ...] = ()


def appraise_deterministic(text: str, context: AppraisalContext | None = None) -> AffectDelta:
    """Conservative baseline that never interprets ordinary tool use as mistreatment."""
    context = context or AppraisalContext()
    message = str(text or "").strip()
    if not message:
        return AffectDelta(event_type="empty", confidence=1.0)

    delta = AffectDelta(
        connection=-0.04 if len(message) <= 3 else -0.09,
        pride=-0.035 if len(message) > 3 else -0.015,
        event_type="ordinary_reply",
        confidence=0.62,
        summary="对方回复了",
    )
    is_technical = bool(_TECHNICAL.search(message))

    if _DISMISSIVE.search(message) or _HOSTILE.search(message):
        severity = 0.34 if _HOSTILE.search(message) else 0.24
        return AffectDelta(
            connection=0.05,
            pride=0.12,
            guardedness=0.18,
            valence=-0.22,
            arousal=0.18,
            trust=-0.035,
            intimacy=-0.05,
            rupture=severity,
            repair=-0.05,
            event_type="boundary_violation",
            confidence=0.94,
            significance=0.88,
            summary="对方使用了明确贬低或敌意表达",
        ).bounded()

    if _APOLOGY.search(message):
        return AffectDelta(
            connection=-0.18,
            pride=-0.10,
            guardedness=-0.10,
            valence=0.07,
            arousal=-0.08,
            trust=0.018,
            intimacy=0.025,
            rupture=-0.08,
            repair=0.20,
            event_type="repair_attempt",
            confidence=0.90,
            significance=0.72,
            summary="对方表达了道歉或修复意愿",
        ).bounded()

    warm = bool(_WARM.search(message))
    compliment = bool(_COMPLIMENT.search(message))
    playful = bool(_PLAYFUL.search(message))
    personal = bool(_PERSONAL_SHARE.search(message))
    distressed = bool(_USER_DISTRESS.search(message))

    if warm or compliment:
        delta.connection = -0.18 if warm else -0.14
        delta.guardedness = -0.035 if warm else 0.025
        delta.pride = -0.08 if warm else -0.035
        delta.valence = 0.08 + (0.04 if compliment else 0.0)
        delta.arousal = -0.025 if warm else 0.045
        delta.trust = 0.006
        delta.intimacy = 0.012
        delta.repair = 0.025
        delta.event_type = "warm_connection"
        delta.confidence = 0.84
        delta.significance = 0.30
        delta.summary = "对方以温暖、感谢或肯定的方式回应"
    elif personal and not is_technical:
        delta.connection = -0.15
        delta.guardedness = -0.035
        delta.pride = -0.06
        delta.valence = 0.025
        delta.arousal = 0.02 if distressed else -0.01
        delta.trust = 0.008
        delta.intimacy = 0.020
        delta.event_type = "personal_sharing"
        delta.confidence = 0.78
        delta.significance = 0.40
        delta.summary = "对方分享了个人感受或近况"
    elif playful and not is_technical:
        delta.connection = -0.12
        delta.guardedness = -0.025
        delta.pride = -0.05
        delta.valence = 0.055
        delta.arousal = 0.035
        delta.intimacy = 0.008
        delta.event_type = "playful_exchange"
        delta.confidence = 0.76
        delta.significance = 0.20
        delta.summary = "对方使用了轻松或玩笑式表达"
    elif is_technical:
        delta.event_type = "task_discussion"
        delta.connection = -0.075
        delta.immersion = 0.05
        delta.confidence = 0.88
        delta.summary = "这是任务或系统讨论，不作为关系褒贬"

    if distressed and delta.event_type != "boundary_violation":
        delta.valence -= 0.045
        delta.arousal += 0.075
        delta.connection -= 0.025
        if delta.event_type == "ordinary_reply":
            delta.event_type = "user_distress"
            delta.summary = "对方表现出难过、疲惫或焦虑"
        delta.significance = max(delta.significance, 0.38)

    return delta.bounded()


def _semantic_prompt(text: str, context: AppraisalContext) -> list[dict[str, str]]:
    recent = "\n".join(context.recent_messages[-4:])
    system = (
        "你是AI角色的情绪评估器，只评估用户这条消息对角色内部状态造成的轻微变化。"
        "任务、技术讨论和正常工具请求不是不尊重。玩笑必须结合上下文，不能仅凭贬义词判断攻击。"
        "输出严格JSON，不生成角色回复。所有delta应克制，关系慢变量通常接近0。"
    )
    user = f"""角色：{context.persona_name}
角色性格：{context.personality[:600]}
关系背景：{context.relationship[:500]}
表达边界：{context.boundaries[:400]}
最近上下文：
{recent[:1600]}

当前用户消息：{text[:1200]}

返回JSON：
{{"connection":-0.60到0.30,"pride":-0.30到0.30,"guardedness":-0.30到0.30,
"valence":-0.35到0.35,"arousal":-0.35到0.35,"immersion":-0.50到0.50,
"trust":-0.08到0.05,"intimacy":-0.08到0.08,"rupture":-0.40到0.50,
"repair":-0.20到0.40,"event_type":"短标签","confidence":0到1,
"significance":0到1,"summary":"不超过40字的事实描述"}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def appraise_semantic(
    text: str,
    context: AppraisalContext,
    *,
    model: str,
    api_key: str,
    api_base: str,
    timeout: float = 8.0,
) -> AffectDelta:
    """Call LiteLLM lazily so the pure engine remains dependency-free."""
    import litellm

    response = litellm.completion(
        model=model,
        messages=_semantic_prompt(text, context),
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=320,
        api_key=api_key,
        api_base=api_base,
        timeout=max(2.0, min(float(timeout), 30.0)),
    )
    raw = response.choices[0].message.content or "{}"
    payload: Any = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("emotion appraisal did not return an object")
    return AffectDelta.from_mapping(payload)


def blend_appraisals(rule: AffectDelta, semantic: AffectDelta) -> AffectDelta:
    """Blend semantic nuance without allowing it to erase high-confidence boundaries."""
    if rule.event_type == "boundary_violation" and rule.confidence >= 0.9:
        return rule
    weight = min(0.72, max(0.0, semantic.confidence) * 0.72)
    values = {}
    for name in (
        "connection", "pride", "guardedness", "valence", "arousal", "immersion",
        "trust", "intimacy", "rupture", "repair",
    ):
        values[name] = getattr(rule, name) * (1.0 - weight) + getattr(semantic, name) * weight
    values.update(
        event_type=semantic.event_type if semantic.confidence >= 0.58 else rule.event_type,
        confidence=max(rule.confidence, semantic.confidence),
        significance=max(rule.significance, semantic.significance),
        summary=semantic.summary if semantic.confidence >= 0.58 and semantic.summary else rule.summary,
    )
    return AffectDelta(**values).bounded()
