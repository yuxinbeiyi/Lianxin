"""人格档案的原子持久化与故障回退。"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from brain.persona.defaults import build_default_persona
from brain.persona.models import (
    DEFAULT_PERSONA_ID,
    PERSONA_SCHEMA_VERSION,
    PersonaProfile,
    PersonaValidationError,
)
from utils.paths import get_user_data_dir


class PersonaStoreError(RuntimeError):
    """人格存储读写失败。"""


class PersonaNotFoundError(PersonaStoreError):
    pass


class PersonaStore:
    STATE_FILE = "active.json"

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else get_user_data_dir() / "personas"
        self._io_lock = threading.RLock()

    def ensure_initialized(self) -> None:
        with self._io_lock:
            self.root.mkdir(parents=True, exist_ok=True)
            default_path = self.profile_path(DEFAULT_PERSONA_ID)
            if not default_path.exists():
                self._write_profile(build_default_persona(), backup=False)
            if not self.state_path.exists():
                self.write_state({
                    "schema_version": PERSONA_SCHEMA_VERSION,
                    "enabled": False,
                    "active_id": DEFAULT_PERSONA_ID,
                })

    @property
    def state_path(self) -> Path:
        return self.root / self.STATE_FILE

    def profile_path(self, profile_id: str) -> Path:
        # 借用模型校验，避免路径穿越；这里只需两个必填占位字段。
        PersonaProfile(
            id=profile_id,
            profile_name="validate",
            assistant_name="validate",
        ).validate()
        return self.root / f"{profile_id}.json"

    def list_profiles(self) -> list[PersonaProfile]:
        self.ensure_initialized()
        profiles: list[PersonaProfile] = []
        for path in self.root.glob("*.json"):
            if path.name == self.STATE_FILE:
                continue
            try:
                profiles.append(self._read_profile_path(path))
            except (PersonaStoreError, PersonaValidationError):
                # 单个人格损坏不应让整个管理界面无法打开。
                continue
        return sorted(
            profiles,
            key=lambda item: (item.id != DEFAULT_PERSONA_ID, item.profile_name.casefold()),
        )

    def load_profile(self, profile_id: str) -> PersonaProfile:
        self.ensure_initialized()
        path = self.profile_path(profile_id)
        if not path.exists():
            raise PersonaNotFoundError(f"人格不存在：{profile_id}")
        return self._read_profile_path(path)

    def save_profile(self, profile: PersonaProfile) -> None:
        profile.validate()
        self.ensure_initialized()
        with self._io_lock:
            self._write_profile(profile, backup=True)

    def delete_profile(self, profile_id: str) -> None:
        if profile_id == DEFAULT_PERSONA_ID:
            raise PersonaStoreError("默认莲心人格不能删除")
        with self._io_lock:
            path = self.profile_path(profile_id)
            if not path.exists():
                raise PersonaNotFoundError(f"人格不存在：{profile_id}")
            path.unlink()
            backup = path.with_suffix(path.suffix + ".bak")
            backup.unlink(missing_ok=True)

    def restore_default(self) -> PersonaProfile:
        profile = build_default_persona()
        with self._io_lock:
            self.root.mkdir(parents=True, exist_ok=True)
            self._write_profile(profile, backup=True)
        return profile

    def read_state(self) -> dict[str, Any]:
        self.ensure_initialized()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("状态文件不是对象")
            return {
                "schema_version": PERSONA_SCHEMA_VERSION,
                "enabled": bool(data.get("enabled", False)),
                "active_id": str(data.get("active_id", DEFAULT_PERSONA_ID)),
            }
        except Exception:
            fallback = {
                "schema_version": PERSONA_SCHEMA_VERSION,
                "enabled": False,
                "active_id": DEFAULT_PERSONA_ID,
            }
            self.write_state(fallback)
            return fallback

    def write_state(self, state: dict[str, Any]) -> None:
        payload = {
            "schema_version": PERSONA_SCHEMA_VERSION,
            "enabled": bool(state.get("enabled", False)),
            "active_id": str(state.get("active_id", DEFAULT_PERSONA_ID)),
        }
        self.profile_path(payload["active_id"])
        with self._io_lock:
            self.root.mkdir(parents=True, exist_ok=True)
            self._atomic_write_json(self.state_path, payload, backup=True)

    def _read_profile_path(self, path: Path) -> PersonaProfile:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return PersonaProfile.from_dict(data)
        except PersonaValidationError:
            raise
        except Exception as exc:
            raise PersonaStoreError(f"读取人格失败：{path.name}: {exc}") from exc

    def _write_profile(self, profile: PersonaProfile, *, backup: bool) -> None:
        self._atomic_write_json(
            self.profile_path(profile.id), profile.to_dict(), backup=backup
        )

    @staticmethod
    def _atomic_write_json(path: Path, data: dict[str, Any], *, backup: bool) -> None:
        tmp = Path(f"{path}.tmp.{os.getpid()}.{threading.get_ident()}")
        try:
            if backup and path.exists():
                shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
            with open(tmp, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(tmp), str(path))
        except Exception as exc:
            raise PersonaStoreError(f"保存人格配置失败：{path.name}: {exc}") from exc
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
