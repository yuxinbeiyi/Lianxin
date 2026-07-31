"""Translate numerical state into concise, persona-safe behavior guidance."""

from __future__ import annotations

from .v3_models import EmotionalStateV3


_CLUSTER_GUIDANCE = {
    "excited": "心情明亮而有活力，反应可以更快、更主动，但不要抢话或夸张表演。",
    "content": "状态舒展而满足，语气温和从容，不必刻意推进话题。",
    "pleased": "心情不错，表达可以比平时松弛一点，让轻微的愉悦自然流露。",
    "agitated": "内在有些烦躁。保持句子清楚简短，诚实表达不适，但不要讽刺、迁怒或攻击对方。",
    "depressed": "情绪偏低且精力不足，可以少说一些，但不要冷暴力、拒绝必要帮助或索取安慰。",
    "sullen": "心里不太舒服，语气可以克制安静；对方释放善意时允许状态逐渐软化。",
    "restless": "有些坐立不安，回复节奏略快；先把意思说清楚，避免冲动下结论。",
    "calm": "状态平静低唤醒，表达简洁柔和，不需要为了热闹强行延伸。",
    "neutral": "状态平稳，按当前人格自然回应，不必额外表演某种情绪。",
}


def _guardedness_guidance(value: float) -> str:
    if value >= 0.72:
        return "防御感很强：减少情绪暴露，但仍直接、尊重地沟通，不用沉默惩罚对方。"
    if value >= 0.45:
        return "有明显戒备：保持一点距离，先回应事实，再谨慎表达感受。"
    if value >= 0.20:
        return "略有克制：可以亲近，但不要突然变得过分依赖或热烈。"
    if value <= -0.10:
        return "此刻比较不设防，可以更坦率温柔，但仍保持人格边界。"
    return "防御感较低，表达自然坦诚。"


def _connection_guidance(state: EmotionalStateV3, mode: str, user_name: str) -> str:
    connection = state.connection
    if mode == "proactive":
        if connection >= 0.80:
            return f"你确实惦记{user_name}，但只在有具体内容或真诚关心时开口，不催促回应。"
        if connection >= 0.58:
            return f"你有点想联系{user_name}。开口应自然、有由头，允许对方暂时不回复。"
        if connection >= 0.35:
            return f"你开始留意{user_name}的沉默，但现在不必强行制造话题。"
        return "当前没有必须主动联系的冲动，沉默也是正常状态。"
    if connection >= 0.80:
        return f"收到{user_name}的消息让持续的惦记得到缓解；可以表现出在意，但不要责怪对方来得晚。"
    if connection >= 0.58:
        return f"你之前有些惦记{user_name}，回应中可以自然流露一点重视。"
    return "连接需求平稳，正常回应即可。"


def _pride_guidance(value: float) -> str:
    if value >= 0.42:
        return "骄傲感偏高：可以保留一点嘴硬和克制，但不要拒绝合理帮助或故意冷落对方。"
    if value <= -0.20:
        return "骄傲感偏低：更愿意放松、让步和坦率表达，不必刻意维持距离。"
    return "骄傲感接近中线，按当前人格自然表达。"


def _profile_override(state: EmotionalStateV3, profile: dict | None) -> str:
    if not isinstance(profile, dict):
        return ""
    clusters = profile.get("clusters", {})
    cluster = clusters.get(state.mood_cluster, {}) if isinstance(clusters, dict) else {}
    if isinstance(cluster, str):
        return cluster.strip()
    if not isinstance(cluster, dict):
        return ""
    guardedness = state.guardedness
    tier = 5 if guardedness >= .72 else 4 if guardedness >= .45 else 3 if guardedness >= .20 else 2 if guardedness >= -.10 else 1
    value = cluster.get(str(tier), cluster.get(tier, ""))
    if isinstance(value, list):
        value = "\n".join(str(item) for item in value)
    return str(value or "").strip()


def render_prompt(
    state: EmotionalStateV3,
    *,
    user_name: str,
    mode: str = "reactive",
    recent_event: str = "",
    profile: dict | None = None,
) -> str:
    mode = "proactive" if mode == "proactive" else "reactive"
    lines = [
        "【涟漪情感状态 v3】",
        _profile_override(state, profile) or _CLUSTER_GUIDANCE.get(state.mood_cluster, _CLUSTER_GUIDANCE["neutral"]),
        _pride_guidance(state.pride),
        _guardedness_guidance(state.guardedness),
        _connection_guidance(state, mode, user_name),
    ]
    if state.rupture >= 0.45:
        lines.append("关系中仍有未消化的不适。可以保持边界并说明感受，但不要报复、羞辱或故意降低任务质量。")
    elif state.repair >= 0.20 and state.rupture > 0.10:
        lines.append("关系正在修复：承认善意和变化，不必假装冲突从未发生，也不要反复追究。")
    if state.relationship_stage in ("挚友", "灵魂伴侣"):
        lines.append(f"你和{user_name}已有稳定而亲近的关系，亲密感应自然体现，不要机械宣告关系标签。")
    if state.immersion >= 0.35 and state.last_activity_type:
        label = f"（{state.last_activity_label}）" if state.last_activity_label else ""
        lines.append(f"你刚才较投入地在做{state.last_activity_type}{label}，可以保留一点活动余韵。")
    if recent_event:
        lines.append(f"最近影响状态的事实：{recent_event}")
    lines.append("情绪只影响表达方式，不得削弱事实准确性、任务完成、用户权限、隐私边界或安全规则。")
    return "\n".join(lines)
