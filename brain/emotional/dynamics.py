"""Deterministic continuous dynamics for Ripple v3."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .v3_models import EmotionalStateV3, ProactiveMotive, clamp


@dataclass(frozen=True)
class DynamicsConfig:
    integration_step_minutes: float = 5.0
    max_offline_minutes: float = 7 * 24 * 60.0
    connection_rate: float = 0.00042
    connection_accel_delay: float = 90.0
    connection_accel: float = 0.85
    immersion_dampen: float = 0.75
    valence_setpoint: float = 0.05
    valence_regress: float = 0.0022
    arousal_setpoint: float = -0.08
    arousal_regress: float = 0.0028
    guardedness_setpoint: float = 0.12
    guardedness_regress: float = 0.0016
    guardedness_defend_threshold: float = 0.58
    guardedness_defend_target: float = 0.42
    guardedness_defend_rate: float = 0.0010
    immersion_decay: float = 0.006
    rupture_decay: float = 0.000035
    repair_decay: float = 0.00008
    observation_threshold: float = 0.35
    contact_threshold: float = 0.58
    urgent_threshold: float = 0.80
    guardedness_block: float = 0.55
    low_valence_regulation: float = -0.48
    high_arousal_regulation: float = 0.58

    @classmethod
    def from_mapping(cls, values: dict | None) -> "DynamicsConfig":
        values = values if isinstance(values, dict) else {}
        allowed = cls.__dataclass_fields__
        clean = {}
        for key, value in values.items():
            if key not in allowed:
                continue
            try:
                clean[key] = float(value)
            except (TypeError, ValueError):
                continue
        return cls(**clean)


class EmotionalDynamics:
    def __init__(self, config: DynamicsConfig | None = None):
        self.config = config or DynamicsConfig()

    @staticmethod
    def _approach(value: float, target: float, rate: float, minutes: float) -> float:
        if rate <= 0 or minutes <= 0:
            return value
        factor = 1.0 - math.exp(-rate * minutes)
        return value + (target - value) * factor

    @staticmethod
    def _connection_context_factor(message: str) -> float:
        text = (message or "").lower()
        if any(token in text for token in ("晚安", "睡了", "去睡", "休息了")):
            return 0.38
        if any(token in text for token in ("开会", "上班", "出门", "忙一会")):
            return 0.68
        return 1.0

    def advance(
        self,
        state: EmotionalStateV3,
        *,
        now: float | None = None,
        bias: dict | None = None,
    ) -> EmotionalStateV3:
        state.normalize()
        if not state.enabled:
            return state
        now = time.time() if now is None else float(now)
        elapsed = clamp((now - state.last_update) / 60.0, 0.0, self.config.max_offline_minutes)
        if elapsed <= 0:
            return state

        remaining = elapsed
        step_size = clamp(self.config.integration_step_minutes, 0.25, 30.0)
        while remaining > 1e-9:
            minutes = min(step_size, remaining)
            self._step(state, minutes, now - remaining * 60.0, bias or {})
            remaining -= minutes
        state.last_update = now
        return state.normalize()

    def _step(self, state: EmotionalStateV3, minutes: float, at_time: float, bias: dict) -> None:
        cfg = self.config
        connection_bias = max(-0.35, min(0.35, float(bias.get("connection", 0) or 0)))
        valence_bias = max(-0.20, min(0.20, float(bias.get("valence", 0) or 0)))
        arousal_bias = max(-0.20, min(0.20, float(bias.get("arousal", 0) or 0)))
        guardedness_bias = max(-0.20, min(0.20, float(bias.get("guardedness", 0) or 0)))
        idle_minutes = max(0.0, (at_time - state.last_interaction) / 60.0)
        context_factor = self._connection_context_factor(state.last_user_message)
        accel = 1.0
        if idle_minutes > cfg.connection_accel_delay:
            progress = min(1.0, (idle_minutes - cfg.connection_accel_delay) / 360.0)
            accel += cfg.connection_accel * progress * (0.5 + state.connection)

        if state.valence < -0.58:
            valence_factor = 0.55
        elif state.valence < -0.20:
            valence_factor = 1.18
        else:
            valence_factor = 1.0
        immersion_factor = max(0.15, 1.0 - state.immersion * cfg.immersion_dampen)
        state.connection += (
            cfg.connection_rate * (1.0 + connection_bias) * context_factor * accel * valence_factor
            * immersion_factor * minutes
        )

        guarded_target = cfg.guardedness_setpoint + guardedness_bias
        guarded_rate = cfg.guardedness_regress
        if state.connection >= cfg.guardedness_defend_threshold and state.rupture > 0.15:
            guarded_target = cfg.guardedness_defend_target + min(0.20, state.rupture * 0.25)
            guarded_rate = cfg.guardedness_defend_rate
        state.guardedness = self._approach(
            state.guardedness, guarded_target, guarded_rate, minutes
        )

        valence_target = cfg.valence_setpoint + valence_bias - state.rupture * 0.16 + state.repair * 0.05
        valence_rate = cfg.valence_regress * (0.55 if state.connection > 0.72 and state.valence < 0 else 1.0)
        state.valence = self._approach(state.valence, valence_target, valence_rate, minutes)

        arousal_target = cfg.arousal_setpoint + arousal_bias
        if state.connection > 0.62:
            arousal_target += (state.connection - 0.62) * 0.60
        if state.guardedness > 0.5 and state.connection > 0.58:
            arousal_target += 0.10
        state.arousal = self._approach(
            state.arousal, arousal_target, cfg.arousal_regress, minutes
        )

        state.immersion = max(0.0, state.immersion - cfg.immersion_decay * minutes)
        if state.immersion <= 0.01:
            state.immersion = 0.0
            if state.last_activity_at and at_time - state.last_activity_at > 3600:
                state.last_activity_type = ""
                state.last_activity_label = ""
        state.rupture = max(0.0, state.rupture - cfg.rupture_decay * minutes)
        state.repair = max(0.0, state.repair - cfg.repair_decay * minutes)
        state.normalize()

    def motive(self, state: EmotionalStateV3) -> ProactiveMotive:
        cfg = self.config
        connection = state.connection
        regulate = (
            state.valence <= cfg.low_valence_regulation
            or state.arousal >= cfg.high_arousal_regulation
        )
        if connection >= cfg.urgent_threshold:
            return ProactiveMotive(
                "urgent", clamp(connection, 0.0, 1.0), True, regulate,
                "连接需求已经持续较高",
            )
        if connection >= cfg.contact_threshold:
            blocked = state.guardedness >= cfg.guardedness_block and state.rupture > 0.12
            return ProactiveMotive(
                "contact", clamp(connection, 0.0, 1.0), not blocked, regulate,
                "想联系对方" if not blocked else "想联系，但仍处在防御状态",
            )
        if connection >= cfg.observation_threshold:
            return ProactiveMotive(
                "aware", clamp(connection, 0.0, 1.0), False, regulate,
                "开始留意对方的沉默",
            )
        return ProactiveMotive("calm", connection, False, regulate, "当前连接需求平稳")
