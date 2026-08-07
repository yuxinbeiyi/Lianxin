"""
观察探索引擎：LLM 驱动的自主环境扫描与记录。
在后台线程中运行，让莲心通过肩载摄像头主动探索周围环境。
"""

import json
import uuid
from datetime import datetime
from openai import OpenAI

from config import get_api_config, get_explorer_prompt
from brain.tools import execute_tool, shoulder_photo, shoulder_pan, shoulder_tilt
from brain.observation_store import add as _store_add

# ── 探索器专用工具定义 ──────────────────────────────────────────

_EXPLORER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "shoulder_photo",
            "description": "用肩载摄像头拍一张照片，返回保存路径。每次探索必须先拍照才能分析。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_image",
            "description": "分析照片内容，返回详细的画面描述。必须在 shoulder_photo 之后调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "shoulder_photo 返回的图片路径",
                    },
                },
                "required": ["image_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shoulder_pan",
            "description": "水平转动舵机。0°=最左, 90°=正前方, 180°=最右。每次调整建议 15~30°。",
            "parameters": {
                "type": "object",
                "properties": {
                    "angle": {"type": "integer", "description": "目标角度 0~180"},
                },
                "required": ["angle"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shoulder_tilt",
            "description": "垂直转动舵机。0°=最上, 90°=水平, 180°=最下。每次调整建议 10~20°。",
            "parameters": {
                "type": "object",
                "properties": {
                    "angle": {"type": "integer", "description": "目标角度 0~180"},
                },
                "required": ["angle"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_observation",
            "description": "记录一次值得关注的发现。当你看到有趣的、不寻常的或值得记住的事物时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "详细描述你看到了什么",
                    },
                    "attention": {
                        "type": "string",
                        "description": "什么特别引起了你的注意（可选）",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关键词标签列表，如 ['水杯', '红色', '桌面']",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_exploration",
            "description": "结束本轮探索。当你觉得已经看够了或没什么值得关注的时候调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "一句话总结本轮探索看到了什么",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]


# ── 探索器执行函数映射 ──────────────────────────────────────────

def _explorer_execute(name: str, args: dict, current_pan: int, current_tilt: int,
                      last_image_path: str, chain_id: str) -> tuple[str, int, int, str]:
    """执行探索器工具调用。返回 (结果文本, 新pan, 新tilt, 新image_path)。"""
    if name == "shoulder_photo":
        result = shoulder_photo()
        if "拍照成功" in result:
            # 提取路径
            path = result.replace("拍照成功，已保存到 ", "").strip()
            return result, current_pan, current_tilt, path
        return result, current_pan, current_tilt, last_image_path

    elif name == "describe_image":
        from brain.tools import describe_image
        result = describe_image(args.get("image_path", last_image_path))
        return result, current_pan, current_tilt, last_image_path

    elif name == "shoulder_pan":
        angle = int(args.get("angle", 90))
        angle = max(0, min(180, angle))
        result = shoulder_pan(angle)
        return result, angle, current_tilt, last_image_path

    elif name == "shoulder_tilt":
        angle = int(args.get("angle", 90))
        angle = max(0, min(180, angle))
        result = shoulder_tilt(angle)
        return result, current_pan, angle, last_image_path

    elif name == "save_observation":
        record = _store_add(
            description=args.get("description", ""),
            attention=args.get("attention", ""),
            tags=args.get("tags", []),
            image_path=last_image_path,
            pan=current_pan,
            tilt=current_tilt,
            chain_id=chain_id,
        )
        return f"已记录观察: {record['id']}", current_pan, current_tilt, last_image_path

    elif name == "finish_exploration":
        return f"[EXPLORATION_DONE] {args.get('summary', '探索完成')}", current_pan, current_tilt, last_image_path

    else:
        return f"未知工具: {name}", current_pan, current_tilt, last_image_path


# ── 探索引擎 ────────────────────────────────────────────────────

class ObservationEngine:
    """在单个线程中执行一次自主观察探索。"""

    def __init__(self):
        cfg = get_api_config()
        self._use_local = cfg.get("use_local", False)
        if self._use_local:
            from config import normalize_local_base_url, normalize_local_model_name
            self._model = normalize_local_model_name(
                cfg.get("local_model_name", "qwen2.5:3b-instruct")
            )
            self._max_tokens = min(cfg["max_tokens"], 2048)
            self._client = OpenAI(
                api_key="ollama",
                base_url=normalize_local_base_url(
                    cfg.get("local_base_url", "http://localhost:11434/v1")
                ),
            )
        else:
            self._model = cfg["model"]
            self._max_tokens = cfg["max_tokens"]
            self._client = OpenAI(
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
            )
        self._system_prompt = get_explorer_prompt()

    def run_explore(self) -> dict:
        """
        执行一次探索循环。返回:
        {
            "chain_id": str,
            "summary": str,
            "observations": list[dict],  # ObservationStore records
            "total_tool_calls": int,
        }
        """
        chain_id = f"explore_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        messages = [{"role": "system", "content": self._system_prompt}]
        messages.append({
            "role": "user",
            "content": (
                f"开始一轮环境探索（chain_id={chain_id}）。"
                "从正前方开始，拍一张照片看看周围有什么。"
                "如果看到有趣的、不寻常的或值得注意的东西，转动舵机仔细看看再记录。"
                "没什么特别的话就记录当前画面然后结束。"
            ),
        })

        current_pan = 90
        current_tilt = 90
        last_image_path = ""
        max_iterations = 6
        pan_adjustments = 0
        summary = ""

        for iteration in range(max_iterations):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=min(self._max_tokens, 1024),
                    tools=_EXPLORER_TOOLS,
                    tool_choice="auto",
                    messages=messages,
                    timeout=30,
                )
            except Exception as e:
                error_msg = str(e).lower()
                is_retryable = any(kw in error_msg for kw in [
                    "timeout", "connection", "getaddrinfo", "name or service not known",
                    "rate limit", "server error", "500", "502", "503", "504",
                ])
                if is_retryable and iteration < 2:
                    import time as _time
                    _time.sleep(2.0)
                    try:
                        response = self._client.chat.completions.create(
                            model=self._model,
                            max_tokens=min(self._max_tokens, 1024),
                            tools=_EXPLORER_TOOLS,
                            tool_choice="auto",
                            messages=messages,
                            timeout=30,
                        )
                    except Exception as e2:
                        return {
                            "chain_id": chain_id,
                            "summary": f"探索失败: {e2}",
                            "observations": [],
                            "total_tool_calls": iteration,
                        }
                else:
                    return {
                        "chain_id": chain_id,
                        "summary": f"探索失败: {e}",
                        "observations": [],
                        "total_tool_calls": iteration,
                    }

            choice = response.choices[0]

            if choice.finish_reason == "stop":
                summary = choice.message.content or "探索结束"
                break

            elif choice.finish_reason == "tool_calls":
                messages.append(choice.message)
                for tool_call in choice.message.tool_calls:
                    name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    if name in ("shoulder_pan", "shoulder_tilt"):
                        pan_adjustments += 1
                        if pan_adjustments > 3:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": "已达到舵机调整次数上限，请调用 finish_exploration 结束探索。",
                            })
                            continue

                    result, current_pan, current_tilt, last_image_path = _explorer_execute(
                        name, args, current_pan, current_tilt,
                        last_image_path, chain_id
                    )

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })

                    if result.startswith("[EXPLORATION_DONE]"):
                        summary = result.replace("[EXPLORATION_DONE] ", "")
                        break

                # 检查是否已结束
                if any(
                    isinstance(r, dict) and r.get("role") == "tool"
                    and str(r.get("content", "")).startswith("[EXPLORATION_DONE]")
                    for r in messages[-3:]
                ):
                    break
            else:
                break

        # 收集本轮产生的观察记录
        from brain.observation_store import get_chain
        observations = get_chain(chain_id)

        return {
            "chain_id": chain_id,
            "summary": summary or "完成环境扫描",
            "observations": observations,
            "total_tool_calls": iteration + 1,
        }
