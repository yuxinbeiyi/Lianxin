# -*- coding: utf-8 -*-
"""
AutoTaskScheduler — 自动化任务调度线程
以 QThread 方式运行，每 30 秒检查一次到期任务，通过信号通知主线程。
"""

import logging
from PyQt5.QtCore import QThread, pyqtSignal

from brain.auto_task_manager import get_auto_task_manager
from utils.auto_task_data import AutoTask

logger = logging.getLogger("AutoTaskScheduler")


class AutoTaskScheduler(QThread):
    """后台调度线程，定期检查到期任务并发射信号。"""

    task_due = pyqtSignal(object)          # 单个任务到期 → AutoTask
    task_missed = pyqtSignal(object)       # 错过任务需要询问 → AutoTask
    status_changed = pyqtSignal()          # 任务列表有变化

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = get_auto_task_manager()
        self._running = False
        self._check_interval_ms = 30_000   # 30 秒
        self._missed_check_count = 0

    def run(self):
        self._running = True
        logger.info("[AutoTaskScheduler] 调度线程已启动，检查间隔: 30s")
        print("⏰ [AutoTaskScheduler] 调度线程已启动，检查间隔: 30s")

        while self._running:
            try:
                self._check_due_tasks()
                self._check_missed_tasks()
            except Exception as e:
                logger.error(f"[AutoTaskScheduler] 检查异常: {e}")
                print(f"❌ [AutoTaskScheduler] 检查异常: {e}")

            self.msleep(self._check_interval_ms)

    def stop(self):
        self._running = False
        logger.info("[AutoTaskScheduler] 调度线程已停止")
        print("⏹ [AutoTaskScheduler] 调度线程已停止")

    def _check_due_tasks(self):
        due = self._manager.get_due_tasks()
        if due:
            print(f"📋 [AutoTaskScheduler] 本轮检查发现 {len(due)} 个到期任务")
        for task in due:
            logger.info(f"[AutoTaskScheduler] 任务到期: {task.name} (ID: {task.task_id})")
            print(f"🔔 [AutoTaskScheduler] 任务到期 → {task.name} (ID:{task.task_id})")
            self.task_due.emit(task)

    def _check_missed_tasks(self):
        self._missed_check_count += 1
        # 每 2 分钟（4 个 30s 周期）检查一次错过任务
        if self._missed_check_count % 4 != 0:
            return
        missed = self._manager.get_missed_tasks()
        if missed:
            print(f"⚠️ [AutoTaskScheduler] 发现 {len(missed)} 个错过任务")
        for task in missed:
            self._manager.mark_asked(task.task_id)
            logger.info(f"[AutoTaskScheduler] 错过任务: {task.name} (ID: {task.task_id})")
            print(f"⏳ [AutoTaskScheduler] 错过任务 → {task.name} (ID:{task.task_id})，将询问用户")
            self.task_missed.emit(task)