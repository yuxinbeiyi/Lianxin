"""
TodoManager：待办清单管理模块
支持添加、完成、删除、查询待办事项，持久化存储到用户目录/.lianxin/tasks.db
提供自然语言辅助解析（时间、优先级）
"""

import uuid
import re
from datetime import datetime
from typing import List, Dict, Optional, Callable

from brain.task_store import TaskStore, get_task_store

# 优先级映射和显示
PRIORITY_VALUES = ["high", "medium", "low"]
PRIORITY_DISPLAY = {
    "high": "🔴 高",
    "medium": "🟠 中",
    "low": "⚪ 低"
}

# 优先级正则匹配规则
_PRIORITY_PATTERNS = {
    "high": r"高优先级|紧急|重要|必须",
    "low": r"低优先级|不着急|有空"
}

# 尝试导入 dateparser，如果未安装则提示用户
try:
    import dateparser
    HAS_DATEPARSER = True
except ImportError:
    HAS_DATEPARSER = False


class TodoItem:
    """待办事项数据结构"""
    def __init__(self, title: str, due_time: Optional[str] = None,
                 priority: str = "medium", description: str = "",
                 completed: bool = False, created_at: Optional[str] = None,
                 todo_id: Optional[str] = None):
        self.id = todo_id or str(uuid.uuid4())
        self.title = title
        self.description = description
        self.due_time = due_time          # ISO格式字符串，如 "2026-04-21T15:00:00"
        self.priority = priority          # "high", "medium", "low"
        self.completed = completed
        self.created_at = created_at or datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "due_time": self.due_time,
            "priority": self.priority,
            "completed": self.completed,
            "created_at": self.created_at
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TodoItem":
        return cls(
            todo_id=data.get("id"),
            title=data["title"],
            description=data.get("description", ""),
            due_time=data.get("due_time"),
            priority=data.get("priority", "medium"),
            completed=data.get("completed", False),
            created_at=data.get("created_at")
        )


class TodoManager:
    def __init__(self, store: TaskStore | None = None, *, workflow_audit: bool = True):
        self._store = store or get_task_store()
        self._workflow_audit = bool(workflow_audit)
        self._todos: List[TodoItem] = []
        self._observers: List[Callable] = []  # 观察者回调列表
        self._load()

    # ── 持久化 ─────────────────────────────────────────────

    def _load(self):
        """从统一任务数据库加载待办事项。"""
        try:
            self._todos = [TodoItem.from_dict(item) for item in self._store.list_todos()]
            print(f"[待办] SQLite 加载成功，共 {len(self._todos)} 条待办")
        except Exception as e:
            print(f"[待办] SQLite 加载失败: {e}")
            self._todos = []

    def _save(self):
        """原子保存待办事项到统一任务数据库。"""
        try:
            self._store.replace_todos(t.to_dict() for t in self._todos)
            print(f"[待办] SQLite 保存成功，共 {len(self._todos)} 条待办")
            # 保存成功后通知所有观察者
            self._notify_observers()
        except Exception as e:
            print(f"[待办] SQLite 保存失败: {e}")

    def get_workflow_runs(self, todo_id: str) -> List[dict]:
        """返回与某条待办正式关联的 Workflow 运行。"""
        return self._store.list_workflows("todo", todo_id)

    def link_auto_task(self, todo_id: str, task_id: str, relation: str = "automates") -> None:
        """建立待办与自动化任务的可追溯关系。"""
        self._store.link_tasks("todo", todo_id, "auto_task", task_id, relation)

    def _notify_observers(self):
        """通知所有注册的观察者数据已变化"""
        for cb in self._observers:
            try:
                cb()
            except Exception as e:
                print(f"[待办] 通知观察者失败: {e}")

    def _record_workflow(self, todo: TodoItem, action: str) -> None:
        if not self._workflow_audit:
            return
        try:
            from brain.workflow import get_workflow_store
            workflow_store = get_workflow_store()
            run = workflow_store.begin_run(
                kind="todo", title=f"待办{action}：{todo.title}", channel="task_center",
                metadata={"todo_id": todo.id, "action": action,
                          "title": todo.title, "due_time": todo.due_time},
            )
            run_id = int(run["id"])
            workflow_store.finish_run(run_id, status="success", result_summary=f"待办已{action}")
            self._store.bind_workflow("todo", todo.id, run_id, action)
        except Exception:
            # Workflow 审计不可阻断待办的核心 CRUD。
            pass

    # ── 观察者管理 ─────────────────────────────────────────

    def register_observer(self, callback: Callable):
        """注册观察者，数据变化时调用 callback()"""
        if callback not in self._observers:
            self._observers.append(callback)

    def unregister_observer(self, callback: Callable):
        """注销观察者"""
        if callback in self._observers:
            self._observers.remove(callback)

    # ── 增删改查 ─────────────────────────────────────────

    def add_todo(self, title: str, due_time: Optional[str] = None,
                 priority: str = "medium", description: str = "") -> TodoItem:
        """添加待办事项，返回创建的 TodoItem"""
        if priority not in PRIORITY_VALUES:
            priority = "medium"
        todo = TodoItem(
            title=title,
            due_time=due_time,
            priority=priority,
            description=description
        )
        self._todos.append(todo)
        self._save()
        self._record_workflow(todo, "创建")
        return todo

    def get_todos(self, completed: bool = False) -> List[TodoItem]:
        """
        获取待办列表
        :param completed: True 获取所有（包括已完成），False 只获取未完成
        """
        if completed:
            return self._todos.copy()
        else:
            return [t for t in self._todos if not t.completed]

    def get_todo_by_id(self, todo_id: str) -> Optional[TodoItem]:
        for t in self._todos:
            if t.id == todo_id:
                return t
        return None

    def complete_todo(self, todo_id: str) -> bool:
        """标记待办为完成，返回是否成功"""
        todo = self.get_todo_by_id(todo_id)
        if todo and not todo.completed:
            todo.completed = True
            self._save()
            self._record_workflow(todo, "完成")
            return True
        return False

    def toggle_complete(self, todo_id: str) -> bool:
        """切换待办的完成状态（已完成→未完成，未完成→已完成），返回是否成功"""
        todo = self.get_todo_by_id(todo_id)
        if todo:
            todo.completed = not todo.completed
            self._save()
            self._record_workflow(todo, "完成" if todo.completed else "恢复")
            return True
        return False

    def delete_todo(self, todo_id: str) -> bool:
        """删除待办，返回是否成功"""
        for i, t in enumerate(self._todos):
            if t.id == todo_id:
                del self._todos[i]
                self._save()
                self._record_workflow(t, "删除")
                return True
        return False

    def update_todo(self, todo_id: str, **kwargs) -> bool:
        """更新待办字段，支持 title, due_time, priority, description"""
        todo = self.get_todo_by_id(todo_id)
        if not todo:
            return False
        for key, value in kwargs.items():
            if key in ["title", "due_time", "priority", "description"]:
                setattr(todo, key, value)
        if "priority" in kwargs and kwargs["priority"] not in PRIORITY_VALUES:
            todo.priority = "medium"
        self._save()
        self._record_workflow(todo, "更新")
        return True

    def get_overdue_todos(self) -> List[TodoItem]:
        """返回所有未完成且截止时间已过的待办"""
        now = datetime.now()
        overdue = []
        for t in self._todos:
            if not t.completed and t.due_time:
                try:
                    due_dt = datetime.fromisoformat(t.due_time)
                    if due_dt < now:
                        overdue.append(t)
                except ValueError:
                    continue
        return overdue

    # ── 自然语言辅助解析（提供给外部使用）─────────────────

    @staticmethod
    def parse_time_from_text(text: str) -> Optional[str]:
        """
        从文本中解析出未来时间，返回 ISO 格式字符串，若解析失败返回 None
        """
        if not HAS_DATEPARSER:
            print("[待办] dateparser 未安装，无法解析自然语言时间。请运行 pip install dateparser")
            return None
        # 设置解析偏好为未来时间
        dt = dateparser.parse(text, settings={'PREFER_DATES_FROM': 'future'})
        if dt:
            return dt.isoformat()
        return None

    @staticmethod
    def parse_priority_from_text(text: str) -> str:
        """从文本中解析优先级，返回 'high', 'medium', 'low'"""
        text_lower = text.lower()
        for priority, pattern in _PRIORITY_PATTERNS.items():
            if re.search(pattern, text_lower):
                return priority
        return "medium"

    @staticmethod
    def extract_title_from_text(text: str, due_time_iso: Optional[str] = None) -> str:
        """
        从原始文本中提取待办标题（去掉时间和优先级关键词）
        简单实现：如果解析出了时间，则尝试移除时间部分；否则返回原文本截取前50字
        """
        if len(text) > 50:
            return text[:50] + "..."
        return text
