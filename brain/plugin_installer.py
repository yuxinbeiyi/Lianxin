"""
插件安装器 — 莲心AI
支持用户一键安装社区 Skills 和 MCP 服务
格式自动检测：Anthropic SKILL.md、MCP manifest.json、package.json 等
"""

import shutil
import json
from pathlib import Path
from typing import Tuple

# 安装目标目录
_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
_MCP_DIR = Path(__file__).resolve().parent.parent / "mcp_servers"


def detect_plugin_type(source: str) -> str:
    """
    检测插件类型
    返回: "skill" | "mcp" | "unknown"
    """
    src = Path(source)
    if not src.exists() or not src.is_dir():
        return "unknown"

    # 1. 直接检测 SKILL.md
    if (src / "SKILL.md").exists():
        return "skill"

    # 2. 检测 mcp-manifest.json
    if (src / "mcp-manifest.json").exists():
        return "mcp"

    # 3. 子目录中检测（如解压后的 skills-main/skills/xxx/）
    for child in src.iterdir():
        if child.is_dir() and (child / "SKILL.md").exists():
            return "skill"
        if child.is_dir() and (child / "mcp-manifest.json").exists():
            return "mcp"

    # 4. Node.js MCP: package.json 含 mcp 关键词
    pkg_json = src / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            if "mcp" in str(pkg).lower():
                return "mcp"
        except Exception:
            pass

    # 5. Python MCP: pyproject.toml 含 mcp/fastmcp
    pyproject = src / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(encoding="utf-8")
        if "mcp" in content.lower() or "fastmcp" in content.lower():
            return "mcp"

    return "unknown"


def get_plugin_info(source: str) -> dict:
    """获取插件信息（名称、描述、版本、类型）"""
    src = Path(source)
    info = {"type": "unknown", "name": src.name, "description": "", "version": "", "_source_path": str(src)}

    ptype = detect_plugin_type(source)
    info["type"] = ptype

    if ptype == "skill":
        skill_md = src / "SKILL.md"
        if not skill_md.exists():
            for child in src.iterdir():
                if child.is_dir() and (child / "SKILL.md").exists():
                    skill_md = child / "SKILL.md"
                    info["_source_path"] = str(child)
                    break

        if skill_md.exists():
            content = skill_md.read_text(encoding="utf-8")
            lines = content.splitlines()
            if len(lines) >= 2 and lines[0].strip() == "---":
                end = None
                for i in range(1, min(len(lines), 30)):
                    if lines[i].strip() == "---":
                        end = i
                        break
                if end:
                    for line in lines[1:end]:
                        if ":" in line:
                            key, _, val = line.partition(":")
                            key = key.strip()
                            val = val.strip().strip("\"'")
                            if key == "name":
                                info["name"] = val
                            elif key == "description":
                                info["description"] = val
                            elif key == "version":
                                info["version"] = val

    elif ptype == "mcp":
        manifest = src / "mcp-manifest.json"
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                info["name"] = data.get("displayName", data.get("name", src.name))
                info["description"] = data.get("description", "")
                info["version"] = data.get("version", "")
            except Exception:
                pass

    return info


def install_plugin(source: str, target_name: str = None) -> Tuple[bool, str]:
    """
    安装插件到对应目录
    Returns: (成功, 消息)
    """
    src = Path(source)
    if not src.exists() or not src.is_dir():
        return False, f"源目录不存在: {source}"

    ptype = detect_plugin_type(source)
    if ptype == "unknown":
        return False, "无法识别插件类型。\n请确保目录包含 SKILL.md（技能）或 mcp-manifest.json（MCP 服务）。"

    if ptype == "skill":
        target_dir = _SKILLS_DIR
        if not (src / "SKILL.md").exists():
            for child in src.iterdir():
                if child.is_dir() and (child / "SKILL.md").exists():
                    src = child
                    break
    else:
        target_dir = _MCP_DIR

    target_dir.mkdir(parents=True, exist_ok=True)

    name = target_name if target_name else src.name
    dest = target_dir / name

    if dest.exists():
        return False, f"插件「{name}」已存在。\n路径: {dest}\n请先删除旧版本或重命名后重试。"

    try:
        shutil.copytree(src, dest)
    except Exception as e:
        return False, f"复制失败: {e}"

    _refresh_after_install(ptype)
    return True, f"✅ 插件「{name}」安装成功！已自动刷新。"


def _refresh_after_install(ptype: str):
    """安装后刷新注册表"""
    try:
        if ptype == "skill":
            from brain.skill_manager import discover_skills, activate_all_skills
            discover_skills()
            activate_all_skills()
        else:
            from brain.mcp.mcp_registry import scan_mcp_services
            scan_mcp_services()
    except Exception as e:
        print(f"[PluginInstaller] 安装后刷新失败: {e}")


def uninstall_plugin(name: str, plugin_type: str):
    """卸载插件：删除目录 + 刷新注册表"""
    if plugin_type == "skill":
        target_dir = _SKILLS_DIR / name
    elif plugin_type == "mcp":
        target_dir = _MCP_DIR / name
    else:
        return False, f"未知插件类型: {plugin_type}"

    if not target_dir.exists():
        return False, f"插件目录不存在: {target_dir}"

    try:
        shutil.rmtree(target_dir)
    except Exception as e:
        return False, f"删除失败: {e}"

    _refresh_after_install(plugin_type)
    return True, f"✅ 插件「{name}」已卸载。"