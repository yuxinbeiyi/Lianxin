"""Cross-platform capability detection and single-instance protection."""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class PlatformCapabilities:
    system: str
    release: str
    python: str
    is_windows: bool
    is_macos: bool
    is_linux: bool
    native_global_hotkey: bool
    native_taskbar_flash: bool
    registry_autostart: bool
    unix_file_lock: bool
    qt_tray_candidate: bool

    def to_dict(self) -> dict:
        return asdict(self)


def get_platform_capabilities() -> PlatformCapabilities:
    system = platform.system() or sys.platform
    lower = system.lower()
    is_windows = lower == "windows" or sys.platform.startswith("win")
    is_macos = lower == "darwin" or sys.platform == "darwin"
    is_linux = lower == "linux" or sys.platform.startswith("linux")
    return PlatformCapabilities(
        system=system,
        release=platform.release(),
        python=platform.python_version(),
        is_windows=is_windows,
        is_macos=is_macos,
        is_linux=is_linux,
        native_global_hotkey=is_windows,
        native_taskbar_flash=is_windows,
        registry_autostart=is_windows,
        unix_file_lock=not is_windows,
        qt_tray_candidate=True,
    )


class SingleInstanceGuard:
    """Windows mutex with a non-Windows advisory-file-lock fallback."""

    def __init__(self, name: str = "LianxinAI_SingleInstance_v2", lock_path: Path | None = None):
        self.name = name
        self.lock_path = Path(lock_path or (Path.home() / ".lianxin" / "lianxin.lock"))
        self._handle = None
        self._file = None

    def acquire(self) -> bool:
        caps = get_platform_capabilities()
        if caps.is_windows:
            try:
                import ctypes
                self._handle = ctypes.windll.kernel32.CreateMutexW(None, False, self.name)
                already_exists = ctypes.windll.kernel32.GetLastError() == 183
                if already_exists:
                    ctypes.windll.kernel32.CloseHandle(self._handle)
                    self._handle = None
                    return False
                return bool(self._handle)
            except Exception:
                # If native mutex access is unavailable, continue with a lock file.
                pass
        return self._acquire_file_lock()

    def _acquire_file_lock(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.lock_path.open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt
                self._file.seek(0)
                if self.lock_path.stat().st_size == 0:
                    self._file.write("0")
                    self._file.flush()
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._file.seek(0)
            self._file.truncate()
            self._file.write(str(os.getpid()))
            self._file.flush()
            return True
        except (OSError, IOError):
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
            return False

    def release(self) -> None:
        if self._handle is not None:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
        if self._file is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None

    def __del__(self):
        self.release()
