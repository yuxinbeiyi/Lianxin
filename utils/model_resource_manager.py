"""Process-local GPU model admission control without importing PyTorch."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Literal

from utils.gpu_resources import get_gpu_memory


Fallback = Literal["cpu", "edge", "defer"]


@dataclass(frozen=True)
class GpuAdmission:
    granted: bool
    fallback: Fallback
    reason: str = ""
    preempt: tuple[str, ...] = ()


class ModelResourceManager:
    """Serialize model admission and record GPU leases owned by this process.

    A lease is intentionally conservative: it remains held until the caller
    explicitly releases it, even if a model allocator temporarily reports free
    memory.  This prevents two lazy loaders from both accepting the same VRAM
    snapshot and constructing large models concurrently.
    """

    _PRIORITY = {"rag": 10, "gpt_sovits": 50, "funasr": 100}

    def __init__(self):
        self._lock = RLock()
        self._leases: dict[str, int] = {}

    def acquire(
        self,
        name: str,
        *,
        minimum_free_mb: int,
        fallback: Fallback,
    ) -> GpuAdmission:
        """Reserve GPU admission, or describe the safe fallback/preemption."""
        with self._lock:
            if name in self._leases:
                return GpuAdmission(True, fallback, "existing lease")

            priority = self._PRIORITY.get(name, 0)
            higher = tuple(
                lease for lease in self._leases
                if self._PRIORITY.get(lease, 0) >= priority
            )
            if higher:
                return GpuAdmission(
                    False, fallback,
                    f"higher-priority GPU model active: {', '.join(higher)}",
                )

            lower = tuple(
                lease for lease in self._leases
                if self._PRIORITY.get(lease, 0) < priority
            )
            if lower:
                return GpuAdmission(
                    False, fallback,
                    f"lower-priority GPU model must be released: {', '.join(lower)}",
                    preempt=lower,
                )

            memory = get_gpu_memory()
            if memory is not None and memory["free_mb"] < max(0, int(minimum_free_mb)):
                return GpuAdmission(
                    False, fallback,
                    f"only {memory['free_mb']} MiB free; need {int(minimum_free_mb)} MiB",
                )

            self._leases[name] = max(0, int(minimum_free_mb))
            return GpuAdmission(True, fallback)

    def release(self, name: str) -> None:
        with self._lock:
            self._leases.pop(name, None)

    def active_leases(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._leases)

    def has_active_gpu_lease(self) -> bool:
        with self._lock:
            return bool(self._leases)


_manager = ModelResourceManager()


def get_model_resource_manager() -> ModelResourceManager:
    return _manager
