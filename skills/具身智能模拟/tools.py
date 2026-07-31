"""莲心虚拟世界的高层具身工具。"""

from __future__ import annotations

from brain.physical.host import get_physical_runtime_host
from brain.physical.integration import get_physical_task_auditor


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "navigate_to_marker",
            "description": "让坦克前往虚拟世界地图中已放置的标记点。本地 A* 规划和运动闭环会异步执行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "marker_id": {
                        "type": "string",
                        "description": "地图标记 ID；调试界面当前活动标记默认是 marker_001。",
                    },
                },
                "required": ["marker_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_snake",
            "description": "让贪吃蛇在空闲状态下向指定方向移动一格，用于具身控制调试。",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                        "description": "移动方向。",
                    },
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_embodied_task",
            "description": "取消当前正在执行的虚拟世界具身任务。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_embodied_status",
            "description": "查询坦克的位置、朝向、活动标记和当前具身任务的真实状态。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def navigate_to_marker(marker_id: str) -> str:
    host = get_physical_runtime_host()
    with host.lock:
        if marker_id not in host.runtime.world.markers:
            return f"未找到地图标记 {marker_id}；请先在调试界面放置标记点。"
        task = host.runtime.submit_navigation(marker_id)
        get_physical_task_auditor(host.runtime).track(task, source="skill")
    return f"导航任务已提交：{task.id}，正在由本地规划器执行。"


def move_snake(direction: str) -> str:
    """在无自动导航任务时执行一格蛇移动。"""
    host = get_physical_runtime_host()
    with host.lock:
        moved = host.runtime.manual_move(direction)
    return "贪吃蛇已移动一格。" if moved else "该方向被障碍物或蛇身阻挡。"


def cancel_embodied_task() -> str:
    host = get_physical_runtime_host()
    return "当前具身任务已取消。" if host.cancel_active_task() else "当前没有可取消的具身任务。"


def get_embodied_status() -> str:
    status = get_physical_runtime_host().status()
    task = status["task"]
    snake = status["snake"]
    task_text = "当前没有活动任务" if task is None else (
        f"任务 {task['id']}（{task['kind']}）状态：{task['status']}"
        + (f"，原因：{task['error']}" if task["error"] else "")
    )
    return (
        f"蛇头位置：({snake['x']}, {snake['y']})，方向：{snake['direction']}，"
        f"步频：{snake['speed']} 格/s；活动食物：{status['active_marker_id'] or '无'}；{task_text}。"
    )


TOOL_EXECUTORS = {
    "navigate_to_marker": lambda input_data: navigate_to_marker(str(input_data["marker_id"])),
    "move_snake": lambda input_data: move_snake(str(input_data["direction"])),
    "cancel_embodied_task": lambda _input_data: cancel_embodied_task(),
    "get_embodied_status": lambda _input_data: get_embodied_status(),
}
