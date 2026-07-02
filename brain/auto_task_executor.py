# -*- coding: utf-8 -*-
"""
auto_task_executor.py — 自动化任务执行器
负责按序执行工具链、记录日志、处理首次执行时的 LLM 动态工具链生成。
"""

import json
import logging
import threading
import time
from datetime import datetime
from typing import Optional, Callable

import litellm

from config import get_api_config
from brain.auto_task_manager import get_auto_task_manager, AutoTaskManager
from brain.tools import TOOL_DEFINITIONS, execute_tool
from utils.auto_task_data import AutoTask, ActionStep

logger = logging.getLogger("AutoTaskExecutor")

# 防止同一任务并发执行
_running_tasks: set[str] = set()
_lock = threading.Lock()

# 执行超时（秒）
EXECUTION_TIMEOUT = 300
# 最大重试次数
MAX_RETRIES = 3
# 重试间隔（秒）
RETRY_DELAYS = [60, 180, 300]


def execute_auto_task(task: AutoTask,
                      on_step: Callable[[int, str, bool], None] = None,
                      on_complete: Callable[[str, bool, str], None] = None):
    """在后台线程中执行自动化任务。"""
    thread = threading.Thread(
        target=_execute_sync,
        args=(task, on_step, on_complete),
        daemon=True,
    )
    thread.start()


def _execute_sync(task: AutoTask,
                  on_step: Optional[Callable[[int, str, bool], None]],
                  on_complete: Optional[Callable[[str, bool, str], None]]):
    """同步执行任务的所有步骤。"""
    task_id = task.task_id

    # 并发保护
    with _lock:
        if task_id in _running_tasks:
            logger.warning(f"任务 {task.name} 正在执行中，跳过")
            print(f"⏭ [AutoTaskExecutor] 任务「{task.name}」正在执行中，跳过重复触发")
            return
        _running_tasks.add(task_id)

    manager = get_auto_task_manager()
    start_time = time.time()
    all_success = True
    final_message = ""

    print(f"\n{'='*60}")
    print(f"🚀 [AutoTaskExecutor] 开始执行任务「{task.name}」(ID:{task_id})")
    print(f"   调度类型: {task.schedule_type} | 时间: {task.schedule_time}")
    print(f"{'='*60}")

    try:
        steps = task.actions if task.actions else []

        # 如果没有工具链，用 LLM 动态生成
        if not steps:
            logger.info(f"任务 {task.name} 无工具链，尝试 LLM 动态生成...")
            print(f"🧠 [AutoTaskExecutor] 无预设工具链，正在调用 LLM 动态生成...")
            steps = _generate_actions_from_llm(task)
            if steps:
                task.actions = steps
                manager.set_actions(task_id, steps)
                logger.info(f"任务 {task.name} 工具链已生成并保存: {len(steps)} 步")
                print(f"✅ [AutoTaskExecutor] LLM 已生成 {len(steps)} 个步骤:")
                for s in steps:
                    print(f"   步骤{s.order}: {s.tool_name}({s.tool_params}) — {s.description}")
            else:
                final_message = "无法生成工具链，任务未执行"
                all_success = False
                manager.add_log(task_id, -1, False, final_message)
                print(f"❌ [AutoTaskExecutor] LLM 无法生成工具链")
                if on_complete:
                    on_complete(task_id, False, final_message)
                return

        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
                logger.info(f"任务 {task.name} 第 {attempt} 次重试，等待 {delay}s...")
                print(f"🔄 [AutoTaskExecutor] 第 {attempt} 次重试，等待 {delay}s...")
                time.sleep(delay)

            all_success = True
            final_message = ""
            total_steps = len(steps)

            for step in steps:
                if time.time() - start_time > EXECUTION_TIMEOUT:
                    final_message = "执行超时"
                    all_success = False
                    print(f"⏰ [AutoTaskExecutor] 执行超时 ({EXECUTION_TIMEOUT}s)")
                    break

                step_start = time.time()
                print(f"  ▶ 步骤{step.order}/{total_steps-1}: {step.description}")
                print(f"    调用工具: {step.tool_name}({step.tool_params})")
                try:
                    result = execute_tool(step.tool_name, step.tool_params)
                    duration_ms = int((time.time() - step_start) * 1000)
                    success = not result.startswith("[拒绝]") and "失败" not in result[:20]

                    manager.add_log(task_id, step.order, success,
                                    f"{step.description}: {result[:200]}", duration_ms)

                    if success:
                        print(f"  ✅ 步骤{step.order} 完成 ({duration_ms}ms) → {result[:120]}")
                    else:
                        print(f"  ❌ 步骤{step.order} 失败 ({duration_ms}ms) → {result[:120]}")

                    if on_step:
                        on_step(step.order, f"{step.description}: {result[:100]}", success)

                    if not success:
                        all_success = False
                        final_message = result
                        break

                except Exception as e:
                    duration_ms = int((time.time() - step_start) * 1000)
                    manager.add_log(task_id, step.order, False, str(e), duration_ms)
                    all_success = False
                    final_message = str(e)
                    print(f"  💥 步骤{step.order} 异常 ({duration_ms}ms) → {e}")
                    if on_step:
                        on_step(step.order, str(e), False)
                    break

            if all_success:
                break

        manager.mark_executed(task_id, all_success, final_message)

    except Exception as e:
        all_success = False
        final_message = str(e)
        manager.add_log(task_id, -1, False, f"执行异常: {e}")
        manager.mark_executed(task_id, False, final_message)
        print(f"💥 [AutoTaskExecutor] 执行异常: {e}")

    finally:
        elapsed = time.time() - start_time
        status = "✅ 成功" if all_success else "❌ 失败"
        print(f"{'='*60}")
        print(f"🏁 [AutoTaskExecutor] 任务「{task.name}」执行完毕: {status} (耗时 {elapsed:.1f}s)")
        print(f"{'='*60}\n")
        with _lock:
            _running_tasks.discard(task_id)
        if on_complete:
            on_complete(task_id, all_success, final_message)


def _generate_actions_from_llm(task: AutoTask) -> list[ActionStep]:
    """用 LLM 根据任务描述动态生成工具链。"""
    api_cfg = get_api_config()
    model = api_cfg.get("model", "deepseek-v4-flash")
    if "/" not in model:
        model = f"deepseek/{model}"

    tools_desc = json.dumps(TOOL_DEFINITIONS[:30], ensure_ascii=False, indent=2)

    system_prompt = f"""你是莲心AI的工具链生成器。根据任务描述，生成需要调用的工具步骤序列。

## 可用工具
{tools_desc}

## 输出格式（严格 JSON 数组）
[
  {{
    "order": 0,
    "tool_name": "工具名称",
    "tool_params": {{"参数": "值"}},
    "description": "这一步做什么"
  }}
]

## 规则
- 只输出 JSON 数组，不要额外文字
- 工具名称必须从可用工具列表中选择
- 参数必须符合工具定义的要求
- 步骤数不超过 5 步"""

    user_prompt = f"请为以下任务生成工具链：\n\n任务名称：{task.name}\n任务描述：{task.description}"

    try:
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            api_key=api_cfg["api_key"],
            api_base=api_cfg["base_url"],
            temperature=0.1,
            max_tokens=1000,
            timeout=30,
        )
        raw = response.choices[0].message.content or ""
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        steps_data = json.loads(raw)
        return [
            ActionStep(
                order=s.get("order", i),
                tool_name=s.get("tool_name", ""),
                tool_params=s.get("tool_params", {}),
                description=s.get("description", ""),
            )
            for i, s in enumerate(steps_data)
        ]
    except Exception as e:
        logger.warning(f"LLM 工具链生成失败: {e}")
        return []