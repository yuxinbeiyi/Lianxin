# -*- coding: utf-8 -*-
"""
auto_task_parser.py — 自然语言 → 自动化任务解析器
使用 LLM 将用户的自然语言指令解析为 AutoTask 结构。
"""

import json
import re
import logging
import requests
from datetime import datetime, timedelta

from config import get_api_config
from utils.auto_task_data import AutoTask, ActionStep

logger = logging.getLogger("AutoTaskParser")

_PARSE_SYSTEM = """你是莲心AI的任务解析器。用户会用自然语言描述一个自动化任务，
你需要将其解析为结构化的 JSON 配置。

## 输出格式（严格 JSON）
{
  "name": "简短的任务名称（不超过15字）",
  "description": "任务描述（保留用户原始意图）",
  "schedule_type": "once|interval|daily|weekly|monthly",
  "schedule_time": "HH:MM 格式的时间（daily/weekly/monthly 时必填）",
  "interval_minutes": 间隔分钟数（仅 schedule_type=interval 时填写，整数）,
  "weekdays": [0,1,2,3,4,5,6]（仅 weekly 时填写，0=周一，例如周一三五 → [0,2,4]）,
  "day_of_month": 月内第几天（仅 monthly 时填写），
  "advance_minutes": 提前多少分钟提醒（支持负数=延后，如提前3天=4320），
  "missed_action": "ask|skip|auto_execute",
  "actions": [
    {
      "order": 0,
      "tool_name": "工具名称",
      "tool_params": {"参数名": "参数值"},
      "description": "这一步做什么"
    }
  ],
  "needs_calendar": true/false（是否需要先查日历确认日期）
}

## 规则
- 如果用户说"下个月X号"，你需要标记 needs_calendar=true，具体日期由执行时查日历确定
- 如果用户说"每隔X分钟/小时"，schedule_type=interval，interval_minutes=分钟数
- 如果用户说"每天X点"，schedule_type=daily，schedule_time=时间
- 如果用户说"每周X"，schedule_type=weekly
- 如果用户说"下个月/每月X号"，schedule_type=monthly
- 如果用户只说了一次性的事情，schedule_type=once
- 工具名称从可用工具列表中选择，不确定时用 actions=[] 空列表
- 如果用户说"提醒我"，actions 只包含一个 notify 步骤
- 如果用户说"清理回收站"，actions 包含 run_shell 步骤
- missed_action 默认 "ask"
- 只输出 JSON，不要任何额外文字"""


def _extract_json(raw: str) -> str:
    """从 LLM 返回中尽力提取 JSON 字符串，自动补全截断的括号。"""
    raw = raw.strip()
    # 1. 去掉 markdown 代码块标记
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    # 2. 用正则提取最外层 { ... }
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
        return m.group(0)
    # 3. JSON 被截断（无闭合 }） → 自动补全
    if raw.startswith("{"):
        # 计算未闭合的括号
        open_count = raw.count("{") - raw.count("}")
        # 去掉最后可能不完整的行
        lines = raw.split("\n")
        # 如果最后一行看起来不完整（不以 " 或 } 或 ] 结尾），去掉
        while lines and not re.search(r'["\}\]\s]\s*$', lines[-1]):
            lines.pop()
        raw = "\n".join(lines)
        # 重新计算
        open_count = raw.count("{") - raw.count("}")
        raw += "}" * max(open_count, 0)
        print(f"   🔧 [AutoTaskParser] JSON 截断，自动补全 {max(open_count, 0)} 个括号")
    return raw


def _call_llm_for_parse(user_text: str, model: str, api_cfg: dict, system_text: str):
    """调用 LLM（优先 litellm，失败降级 requests 直调），返回原始文本。"""
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": f"请解析以下自然语言指令：\n\n{user_text}"},
    ]

    # 方案 A：litellm
    try:
        import litellm
        response = litellm.completion(
            model=model,
            messages=messages,
            api_key=api_cfg["api_key"],
            api_base=api_cfg["base_url"],
            temperature=0.1,
            max_tokens=2000,
            timeout=30,
        )
        content = response.choices[0].message.content
        if content:
            print(f"   [AutoTaskParser] litellm 返回 {len(content)} 字")
            return content
        print(f"   ⚠️ [AutoTaskParser] litellm 返回空内容，降级 requests...")
    except Exception as e:
        print(f"   ⚠️ [AutoTaskParser] litellm 调用失败: {e}，降级 requests...")

    # 方案 B：requests 直调 DeepSeek API
    try:
        base_url = api_cfg["base_url"].rstrip("/")
        url = f"{base_url}/chat/completions"
        # 去掉 litellm 的 provider 前缀，如 deepseek/deepseek-v4-flash → deepseek-v4-flash
        pure_model = model.split("/", 1)[-1] if "/" in model else model
        payload = {
            "model": pure_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 2000,
        }
        headers = {
            "Authorization": f"Bearer {api_cfg['api_key']}",
            "Content-Type": "application/json",
        }
        print(f"   [AutoTaskParser] requests → {url} model={pure_model}")
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        print(f"   [AutoTaskParser] HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   [AutoTaskParser] 响应 keys: {list(data.keys())}")
            try:
                content = data["choices"][0]["message"]["content"]
                if content:
                    print(f"   [AutoTaskParser] requests 返回 {len(content)} 字")
                    return content
                print(f"   ❌ [AutoTaskParser] content 为空字符串")
            except (KeyError, IndexError, TypeError) as e:
                print(f"   ❌ [AutoTaskParser] 响应结构异常: {e}")
                print(f"   📦 完整响应(前500字): {resp.text[:500]}")
        else:
            print(f"   ❌ [AutoTaskParser] requests 失败: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"   ❌ [AutoTaskParser] requests 异常: {e}")

    return ""


def _parse_to_task(user_text: str, available_tools: list[str] = None) -> dict:
    """调用 LLM 解析自然语言为任务配置字典（含重试）。"""
    api_cfg = get_api_config()
    model = api_cfg.get("model", "deepseek-v4-flash")
    if "/" not in model:
        model = f"deepseek/{model}"

    tools_hint = ""
    if available_tools:
        tools_hint = f"\n\n## 当前可用工具列表\n{', '.join(available_tools[:30])}"

    system_text = _PARSE_SYSTEM + tools_hint

    for attempt in range(2):
        try:
            raw = _call_llm_for_parse(user_text, model, api_cfg, system_text)
            json_str = _extract_json(raw)
            print(f"   [AutoTaskParser] 第{attempt+1}次尝试，LLM 原始返回({len(raw)}字): {raw[:150]}...")
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"LLM 返回非 JSON (尝试 {attempt+1}/2): {raw[:200]}")
            print(f"   ⚠️ [AutoTaskParser] 第{attempt+1}次 JSON 解析失败: {e}")
            if attempt == 0:
                # 重试时加强提示
                system_text += "\n\n⚠️ 重要：你上次输出不是合法 JSON。这次请只输出纯 JSON，不要任何 markdown 标记、注释或额外文字。"
        except Exception as e:
            logger.error(f"LLM 解析失败: {e}")
            print(f"   ❌ [AutoTaskParser] LLM 调用异常: {e}")
            raise

    # 降级：规则兜底
    print(f"   🔧 [AutoTaskParser] LLM 两次均失败，启用规则降级...")
    return _fallback_parse(user_text)


def _cn_num_to_int(s: str) -> int:
    """中文数字 → 整数，如 '两'→2, '三'→3, '半'→0.5→0"""
    m = {
        "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        "半": 0.5,
    }
    return int(m.get(s, 0))


def _parse_delay_seconds(user_text: str) -> int:
    """从文本中提取延迟秒数，支持中文数字和阿拉伯数字。"""
    total = 0
    # 阿拉伯数字: "2分钟后" "30秒后" "1小时后"
    for m in re.finditer(r'(\d+)\s*(分钟|秒|小时)后', user_text):
        n = int(m.group(1))
        unit = m.group(2)
        if unit == "小时":
            total += n * 3600
        elif unit == "分钟":
            total += n * 60
        else:
            total += n
    # 中文数字: "两分钟后" "三小时后"
    for m in re.finditer(r'([零一二两三四五六七八九十半])\s*(分钟|秒|小时)后', user_text):
        n = _cn_num_to_int(m.group(1))
        unit = m.group(2)
        if n == 0:
            continue
        if unit == "小时":
            total += n * 3600
        elif unit == "分钟":
            total += n * 60
        else:
            total += n
    return total


def _extract_task_name(user_text: str) -> str:
    """从用户指令中提取有意义的任务名。"""
    # 优先从 "帮我XXX" 后面提取，但去掉路径和多余前缀
    m = re.search(r'帮[我我]\s*(.+?)(?:[，。,。]|$)', user_text)
    if m:
        raw = m.group(1).strip()
        # 去掉 Windows 路径
        raw = re.sub(r'[A-Za-z]:\\[^\s，,。]*', '', raw).strip()
        # 去掉 "里的" "里面的" 等
        raw = re.sub(r'里(面)?的', '', raw).strip()
        if raw:
            return raw[:15]
    # 兜底：取"莲心"之后的内容
    cleaned = user_text.replace("莲心", "").replace("，", "").replace("。", "").strip()
    cleaned = re.sub(r'[A-Za-z]:\\[^\s，,。]*', '', cleaned).strip()
    return cleaned[:15] if cleaned else "自动化任务"


def _fallback_parse(user_text: str) -> dict:
    """LLM 失败时的规则降级：从文本中提取关键信息生成简化任务。"""
    print(f"   🔧 [AutoTaskParser] 规则降级中...")

    # 提取时间
    schedule_type = "once"
    schedule_time = "08:00"
    interval_minutes = 0

    advance_seconds = _parse_delay_seconds(user_text)

    if advance_seconds > 0:
        target = datetime.now() + timedelta(seconds=advance_seconds)
        schedule_time = target.strftime("%H:%M")
        print(f"   ⏱ [AutoTaskParser] 延迟 {advance_seconds}s → 目标时间 {schedule_time}")

    # 匹配周期
    if re.search(r'每天|每日', user_text):
        schedule_type = "daily"
    elif re.search(r'每隔\s*([\d两一二三]+)\s*分钟', user_text):
        m2 = re.search(r'每隔\s*([\d两一二三]+)\s*分钟', user_text)
        interval_minutes = _cn_num_to_int(m2.group(1)) if m2 else 0
        schedule_type = "interval"
    elif re.search(r'每周|每星期', user_text):
        schedule_type = "weekly"
    elif re.search(r'每月|每个月', user_text):
        schedule_type = "monthly"

    # 提取任务名
    name = _extract_task_name(user_text)

    # 提取动作关键词 → 生成 actions
    actions = []
    text_lower = user_text.lower()

    # 删除 — 用 run_command 执行 del 命令（Windows）
    if re.search(r'删除|删掉|移除|清理', user_text):
        # 提取路径
        path_m = re.search(r'([A-Za-z]:\\[^\s，,。]+)', user_text)
        path = path_m.group(1) if path_m else ""
        # 提取文件类型
        ext_m = re.search(r'(docx|txt|pdf|md|py|json|xlsx|pptx)文档?', user_text)
        ext = ext_m.group(1) if ext_m else ""
        if path and ext:
            cmd = f'del /f /q \"{path}\\\\*.{ext}\"'
            actions.append({
                "order": 0, "tool_name": "run_command",
                "tool_params": {"command": cmd},
                "description": f"删除 {path} 下的 .{ext} 文件"
            })
        elif path:
            cmd = f'del /f /q \"{path}\"'
            actions.append({
                "order": 0, "tool_name": "run_command",
                "tool_params": {"command": cmd},
                "description": f"删除 {path}"
            })

    # 阅读
    if re.search(r'阅读|读取|查看|读一下', user_text):
        path_m = re.search(r'([A-Za-z]:\\[^\s，,。]+)', user_text)
        path = path_m.group(1) if path_m else ""
        actions.append({
            "order": len(actions), "tool_name": "read_file",
            "tool_params": {"path": path} if path else {},
            "description": f"阅读文件" if not path else f"阅读 {path}"
        })

    # 转换/整理
    if re.search(r'整理|转换|变成|转成|生成|导出', user_text):
        ext_m = re.search(r'(docx|txt|pdf|md|json|xlsx|pptx)文档?', user_text)
        target_ext = ext_m.group(1) if ext_m else "txt"
        actions.append({
            "order": len(actions), "tool_name": "format_document",
            "tool_params": {"output_format": target_ext},
            "description": f"整理为 {target_ext} 文档"
        })

    # 通知
    if re.search(r'提醒|通知|告诉', user_text):
        actions.append({
            "order": len(actions), "tool_name": "notify",
            "tool_params": {"message": name},
            "description": f"提醒: {name}"
        })

    # 如果没有任何动作，默认加 notify
    if not actions:
        actions.append({
            "order": 0, "tool_name": "notify",
            "tool_params": {"message": user_text[:80]},
            "description": "执行用户指令"
        })

    result = {
        "name": name,
        "description": user_text,
        "schedule_type": schedule_type,
        "schedule_time": schedule_time,
        "interval_minutes": interval_minutes,
        "missed_action": "ask",
        "actions": actions,
    }
    print(f"   ✅ [AutoTaskParser] 降级结果: {json.dumps(result, ensure_ascii=False)[:200]}")
    return result


def parse_auto_task(user_text: str,
                    available_tools: list[str] = None) -> AutoTask:
    """将自然语言指令解析为 AutoTask 对象。"""
    print(f"\n🧠 [AutoTaskParser] 开始解析自然语言指令...")
    print(f"   用户输入: {user_text[:120]}")
    parsed = _parse_to_task(user_text, available_tools)

    print(f"📋 [AutoTaskParser] LLM 解析结果:")
    print(f"   任务名称: {parsed.get('name', '未命名')}")
    print(f"   调度类型: {parsed.get('schedule_type', 'once')}")
    print(f"   调度时间: {parsed.get('schedule_time', 'N/A')}")
    print(f"   间隔分钟: {parsed.get('interval_minutes', 0)}")
    print(f"   错过策略: {parsed.get('missed_action', 'ask')}")
    print(f"   工具步骤: {len(parsed.get('actions', []))} 步")

    actions = []
    for a in parsed.get("actions", []):
        actions.append(ActionStep(
            order=a.get("order", 0),
            tool_name=a.get("tool_name", ""),
            tool_params=a.get("tool_params", {}),
            description=a.get("description", ""),
        ))

    # ── 修复 LLM 返回 null 导致字段为 None 的问题 ──
    schedule_type = parsed.get("schedule_type") or "once"
    schedule_time = parsed.get("schedule_time") or ""
    interval_minutes = parsed.get("interval_minutes") or 0

    # once 类型且 LLM 没有给具体时间 → 从用户指令中提取延迟秒数
    if schedule_type == "once" and not schedule_time:
        advance_seconds = _parse_delay_seconds(user_text)
        if advance_seconds > 0:
            target = datetime.now() + timedelta(seconds=advance_seconds)
            schedule_time = target.strftime("%H:%M")
            print(f"   ⏱ [AutoTaskParser] LLM 未给时间，从文本提取: +{advance_seconds}s → {schedule_time}")
        else:
            # 默认 1 分钟后
            target = datetime.now() + timedelta(seconds=60)
            schedule_time = target.strftime("%H:%M")
            print(f"   ⏱ [AutoTaskParser] 无法确定延迟，默认 1 分钟后: {schedule_time}")

    task = AutoTask(
        name=parsed.get("name", "未命名任务"),
        description=parsed.get("description", user_text),
        source="natural",
        schedule_type=schedule_type,
        schedule_time=schedule_time,
        interval_minutes=interval_minutes,
        weekdays=parsed.get("weekdays") or [],
        day_of_month=parsed.get("day_of_month"),
        advance_minutes=parsed.get("advance_minutes") or 0,
        missed_action=parsed.get("missed_action") or "ask",
        actions=actions,
        tags=["auto"],
    )

    task.next_run = task.compute_next_run()
    print(f"✅ [AutoTaskParser] 任务对象已创建，下次执行: {task.next_run}\n")
    return task


def generate_confirm_message(task: AutoTask) -> str:
    """生成用户确认消息。"""
    type_map = {
        "once": "一次性",
        "interval": f"每隔{task.interval_minutes}分钟",
        "daily": "每天",
        "weekly": "每周",
        "monthly": "每月",
    }
    schedule_desc = type_map.get(task.schedule_type, task.schedule_type)

    if task.schedule_type in ("daily", "weekly", "monthly"):
        schedule_desc += " " + task.schedule_time

    lines = [
        f"好的，我记下了 ✨",
        f"📋 任务：{task.name}",
        f"⏰ 时间：{schedule_desc}",
    ]
    if task.advance_minutes > 0:
        lines.append(f"🔔 提前 {task.advance_minutes} 分钟提醒")
    if task.actions:
        lines.append(f"🔧 将执行 {len(task.actions)} 个步骤")
    if task.schedule_type == "once":
        lines.append(f"📅 首次执行：{task.next_run}")

    return "\n".join(lines)