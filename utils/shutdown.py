"""有总预算的 Qt 后台线程停机协调。"""

from __future__ import annotations

import time
from typing import Iterable


# 应用退出时仍在网络/模型调用中的 QThread 必须保留 Python 引用，否则 Qt 会
# 报“QThread: Destroyed while thread is still running”。线程结束后自动释放。
_LINGERING_THREADS: list[object] = []


def _release(worker) -> None:
    try:
        _LINGERING_THREADS.remove(worker)
    except ValueError:
        pass


def stop_qthreads(workers: Iterable[object], total_timeout_ms: int = 250) -> list[object]:
    """先同时发停止请求，再在一个共享预算内等待，绝不逐线程累计超时。"""
    unique = []
    seen: set[int] = set()
    for worker in workers or ():
        if worker is None or id(worker) in seen:
            continue
        seen.add(id(worker))
        try:
            running = bool(worker.isRunning())
        except Exception:
            running = False
        if running:
            unique.append(worker)

    for worker in unique:
        try:
            worker.requestInterruption()
        except Exception:
            pass
        try:
            worker.quit()
        except Exception:
            pass

    deadline = time.monotonic() + max(0, int(total_timeout_ms)) / 1000.0
    for worker in unique:
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        if remaining_ms <= 0:
            break
        try:
            worker.wait(min(remaining_ms, 50))
        except Exception:
            pass

    survivors = []
    for worker in unique:
        try:
            running = bool(worker.isRunning())
        except Exception:
            running = False
        if not running:
            continue
        survivors.append(worker)
        if worker not in _LINGERING_THREADS:
            _LINGERING_THREADS.append(worker)
            try:
                worker.finished.connect(lambda w=worker: _release(w))
            except Exception:
                pass
    return survivors
