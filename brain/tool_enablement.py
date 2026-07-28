"""已停用能力的用户授权启用服务。

Agent 只能请求，GUI 才能代表用户确认；这里负责解析目标并写入既有配置源。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnablementTarget:
    key: str
    display_name: str
    kind: str  # builtin | mcp
    tool_names: tuple[str, ...]


def _builtin_display_name(name: str) -> str:
    try:
        from brain.tool_router import TOOL_DESCRIPTIONS
        return TOOL_DESCRIPTIONS.get(name, name)
    except Exception:
        return name


def resolve_disabled_target(name: str) -> EnablementTarget | None:
    """只返回当前实际已停用的目标，未知名称和已启用目标均不可请求。"""
    requested = str(name or "").strip()
    if not requested:
        return None

    from config import get_builtin_tool_config
    builtin_cfg = get_builtin_tool_config()
    if requested in builtin_cfg and not builtin_cfg[requested]:
        return EnablementTarget(
            key=requested,
            display_name=_builtin_display_name(requested),
            kind="builtin",
            tool_names=(requested,),
        )

    try:
        from brain.mcp.mcp_registry import (
            MANIFEST_CACHE, MCP_REGISTRY, get_disabled_mcp_names, get_mcp_agent,
        )
        disabled = set(get_disabled_mcp_names())
        service_name = requested
        if requested.startswith("mcp__"):
            parts = requested.split("__", 2)
            if len(parts) >= 3:
                service_name = parts[1]
        if service_name not in disabled:
            return None
        agent = get_mcp_agent(service_name) or MCP_REGISTRY.get(service_name)
        definitions = agent.get_tool_definitions_openai() if agent else []
        tool_names = tuple(
            item.get("function", {}).get("name", "")
            for item in definitions
            if item.get("function", {}).get("name")
        )
        manifest = MANIFEST_CACHE.get(service_name, {})
        display = (manifest.get("displayName") or getattr(agent, "display_name", "") or service_name)
        return EnablementTarget(service_name, str(display), "mcp", tool_names)
    except Exception:
        return None


def enable_target(target: EnablementTarget) -> bool:
    """持久启用指定目标；返回最终状态，不做任何 UI。"""
    if target.kind == "builtin":
        from config import get_builtin_tool_config, save_builtin_tool_config
        cfg = get_builtin_tool_config()
        cfg[target.key] = True
        save_builtin_tool_config(cfg)
        return bool(get_builtin_tool_config().get(target.key, False))

    if target.kind == "mcp":
        from brain.mcp.mcp_registry import is_mcp_enabled, toggle_mcp_enabled
        if not is_mcp_enabled(target.key):
            toggle_mcp_enabled(target.key)
        return is_mcp_enabled(target.key)
    return False


def format_disabled_targets() -> str:
    """供模型使用的简短目录，明确告知只能先请求用户授权。"""
    rows: list[str] = []
    try:
        from config import get_builtin_tool_config
        for name, enabled in get_builtin_tool_config().items():
            if not enabled:
                rows.append(f"- {name}（{_builtin_display_name(name)}）")
    except Exception:
        pass
    try:
        from brain.mcp.mcp_registry import get_disabled_mcp_names
        for name in sorted(get_disabled_mcp_names()):
            rows.append(f"- {name}（MCP 服务）")
    except Exception:
        pass
    return "\n".join(rows)


TOOL_ENABLE_REQUEST_DEFINITION = {
    "type": "function",
    "function": {
        "name": "request_enable_tool",
        "description": (
            "当完成用户当前任务确实需要一个已停用的工具或 MCP 服务时，请求用户在界面中确认启用。"
            "不得自行启用；不得对未知或已启用工具调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "已停用的内置工具名、MCP 服务名，或 mcp__服务__工具名。",
                },
                "reason": {
                    "type": "string",
                    "description": "一句话说明当前任务为什么需要它。",
                },
            },
            "required": ["tool_name", "reason"],
        },
    },
}
