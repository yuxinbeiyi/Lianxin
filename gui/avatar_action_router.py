"""Semantic avatar-action router shared by GIF, Galgame and future Live2D views."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class AvatarAction:
    name: str
    expression: str
    priority: int
    duration_ms: int = 0


ACTION_MAP = {
    "idle": AvatarAction("idle", "默认", 0),
    "thinking": AvatarAction("thinking", "疑惑", 40),
    "speaking": AvatarAction("speaking", "默认", 50),
    "listening": AvatarAction("listening", "默认", 30),
    "happy": AvatarAction("happy", "开心", 25, 2200),
    "celebrate": AvatarAction("celebrate", "开心", 35, 2800),
    "concerned": AvatarAction("concerned", "疑惑", 35, 4200),
    "affection": AvatarAction("affection", "害羞", 30, 2400),
    "wave": AvatarAction("wave", "开心", 20, 2200),
    "error": AvatarAction("error", "伤心", 60, 2600),
}


class AvatarActionRouter:
    """Maps product-level actions to whichever visual surfaces are available."""

    def __init__(self, character_widget, *, expression_callback: Callable[[str], None] | None = None,
                 schedule: Callable[[int, Callable], None] | None = None,
                 reduced_motion: bool = False):
        self.character = character_widget
        self.expression_callback = expression_callback
        self.schedule = schedule or (lambda _ms, callback: callback())
        self.reduced_motion = bool(reduced_motion)
        self.current = "idle"
        self._generation = 0
        self.history = deque(maxlen=100)

    def set_reduced_motion(self, enabled: bool) -> None:
        self.reduced_motion = bool(enabled)

    def request(self, action_name: str, *, source: str = "system", force: bool = False,
                on_finished: Callable | None = None) -> bool:
        action = ACTION_MAP.get(str(action_name), ACTION_MAP["idle"])
        current = ACTION_MAP.get(self.current, ACTION_MAP["idle"])
        if not force and action.priority < current.priority and self.current in {"thinking", "speaking", "error"}:
            return False
        self._generation += 1
        generation = self._generation
        self.current = action.name
        self.history.append({"action": action.name, "source": source, "at": time.time()})
        if self.expression_callback:
            try:
                self.expression_callback(action.expression)
            except Exception:
                pass
        self._apply_character(action, on_finished=on_finished)
        if action.duration_ms and action.name not in {"thinking", "speaking"}:
            self.schedule(action.duration_ms, lambda: self._restore_if_current(generation, on_finished))
        return True

    def _apply_character(self, action: AvatarAction, *, on_finished=None) -> None:
        try:
            if action.name == "thinking":
                self.character.start_thinking()
            elif action.name == "speaking":
                self.character.set_talking()
            elif action.name in {"concerned", "error"}:
                # These semantic reactions have their own short timeout.  Reusing
                # the legacy ten-second arms-cross animation here would create a
                # second completion callback and could restore a stale state.
                if not self.reduced_motion:
                    self.character.set_talking()
                else:
                    self.character.set_normal_status()
            elif action.name in {"happy", "celebrate", "affection", "wave"}:
                if not self.reduced_motion:
                    self.character.set_talking()
                else:
                    self.character.set_normal_status()
            elif action.name == "listening":
                self.character.set_normal_status()
            else:
                self.character.set_normal()
        except Exception:
            if on_finished:
                on_finished()

    def _restore_if_current(self, generation: int, on_finished=None) -> None:
        if generation != self._generation:
            return
        self.request("idle", source="action_timeout", force=True)
        if on_finished:
            on_finished()

    def finish_thinking(self, on_finished: Callable | None = None) -> None:
        self._generation += 1
        self.current = "idle"
        try:
            self.character.stop_thinking(on_finished=on_finished)
        except Exception:
            if on_finished:
                on_finished()

    def speaking_started(self, source: str = "speech") -> None:
        self.request("speaking", source=source, force=True)

    def speaking_finished(self) -> None:
        self.request("idle", source="speech_finished", force=True)

    def recent_actions(self) -> list[dict]:
        return list(self.history)
