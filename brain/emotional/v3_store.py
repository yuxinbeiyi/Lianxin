"""SQLite persistence and v2 migration for Ripple v3."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .v3_models import (
    DEFAULT_PERSONA_ID,
    DEFAULT_SUBJECT_ID,
    AffectDelta,
    EmotionalStateV3,
    clamp,
)


DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "memory" / "conversations.db"


class EmotionStore:
    """Small transactional repository sharing the application's SQLite database."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        self._lock = threading.RLock()
        self._local = threading.local()
        self._memory_conn: sqlite3.Connection | None = None
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
                self._memory_conn.execute("PRAGMA foreign_keys=ON")
            return self._memory_conn
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=3000")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        with self._lock:
            if self._memory_conn is not None:
                self._memory_conn.close()
                self._memory_conn = None
            conn = getattr(self._local, "conn", None)
            if conn is not None:
                conn.close()
                self._local.conn = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS emotion_v3_states (
                    persona_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (persona_id, subject_id)
                );
                CREATE TABLE IF NOT EXISTS emotion_v3_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    persona_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    source_channel TEXT DEFAULT '',
                    source_session_id INTEGER,
                    source_message_id INTEGER,
                    event_type TEXT NOT NULL,
                    delta_json TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    significance REAL NOT NULL DEFAULT 0,
                    summary TEXT DEFAULT '',
                    resulting_state_json TEXT DEFAULT '',
                    idempotency_key TEXT DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_emotion_v3_event_key
                    ON emotion_v3_events(idempotency_key)
                    WHERE idempotency_key <> '';
                CREATE INDEX IF NOT EXISTS idx_emotion_v3_event_scope
                    ON emotion_v3_events(persona_id, subject_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS emotion_v3_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(emotion_v3_events)").fetchall()}
            if "resulting_state_json" not in columns:
                conn.execute("ALTER TABLE emotion_v3_events ADD COLUMN resulting_state_json TEXT DEFAULT ''")
            conn.commit()

    def load_state(self, persona_id: str, subject_id: str) -> EmotionalStateV3:
        persona_id = str(persona_id or DEFAULT_PERSONA_ID)
        subject_id = str(subject_id or DEFAULT_SUBJECT_ID)
        with self._lock:
            row = self._connect().execute(
                "SELECT state_json FROM emotion_v3_states WHERE persona_id=? AND subject_id=?",
                (persona_id, subject_id),
            ).fetchone()
        if not row:
            return EmotionalStateV3(persona_id=persona_id, subject_id=subject_id)
        try:
            payload = json.loads(row["state_json"])
            payload["persona_id"] = persona_id
            payload["subject_id"] = subject_id
            return EmotionalStateV3.from_mapping(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return EmotionalStateV3(persona_id=persona_id, subject_id=subject_id)

    def has_state(self, persona_id: str, subject_id: str) -> bool:
        with self._lock:
            row = self._connect().execute(
                "SELECT 1 FROM emotion_v3_states WHERE persona_id=? AND subject_id=?",
                (str(persona_id), str(subject_id)),
            ).fetchone()
        return row is not None

    def save_state(self, state: EmotionalStateV3) -> None:
        payload = json.dumps(state.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            conn = self._connect()
            conn.execute(
                """INSERT INTO emotion_v3_states
                   (persona_id,subject_id,schema_version,state_json,updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(persona_id,subject_id) DO UPDATE SET
                     schema_version=excluded.schema_version,
                     state_json=excluded.state_json,
                     updated_at=excluded.updated_at""",
                (state.persona_id, state.subject_id, state.schema_version, payload, time.time()),
            )
            conn.commit()

    def list_states(self) -> list[EmotionalStateV3]:
        with self._lock:
            rows = self._connect().execute(
                "SELECT persona_id,subject_id,state_json FROM emotion_v3_states"
            ).fetchall()
        result = []
        for row in rows:
            try:
                payload = json.loads(row["state_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            payload.update(persona_id=row["persona_id"], subject_id=row["subject_id"])
            result.append(EmotionalStateV3.from_mapping(payload))
        return result

    def append_event(
        self,
        state: EmotionalStateV3,
        delta: AffectDelta,
        *,
        source_channel: str = "",
        source_session_id: int | None = None,
        source_message_id: int | None = None,
        idempotency_key: str = "",
    ) -> int | None:
        delta = delta.bounded()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """INSERT INTO emotion_v3_events
                       (persona_id,subject_id,source_channel,source_session_id,
                        source_message_id,event_type,delta_json,confidence,
                        significance,summary,resulting_state_json,idempotency_key,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        state.persona_id, state.subject_id, str(source_channel or ""),
                        source_session_id, source_message_id, delta.event_type,
                        json.dumps(delta.to_dict(), ensure_ascii=False, separators=(",", ":")),
                        delta.confidence, delta.significance, delta.summary, "",
                        str(idempotency_key or ""), time.time(),
                    ),
                )
                conn.commit()
                return int(cur.lastrowid)
            except sqlite3.IntegrityError:
                conn.rollback()
                return None

    def save_state_with_event(
        self,
        state: EmotionalStateV3,
        delta: AffectDelta,
        *,
        source_channel: str = "",
        source_session_id: int | None = None,
        source_message_id: int | None = None,
        idempotency_key: str = "",
    ) -> bool:
        """Atomically append the appraisal event and replace its resulting state."""
        delta = delta.bounded()
        state_payload = json.dumps(
            state.to_dict(), ensure_ascii=False, separators=(",", ":")
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """INSERT INTO emotion_v3_events
                       (persona_id,subject_id,source_channel,source_session_id,
                        source_message_id,event_type,delta_json,confidence,
                        significance,summary,resulting_state_json,idempotency_key,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        state.persona_id, state.subject_id, str(source_channel or ""),
                        source_session_id, source_message_id, delta.event_type,
                        json.dumps(delta.to_dict(), ensure_ascii=False, separators=(",", ":")),
                        delta.confidence, delta.significance, delta.summary,
                        state_payload,
                        str(idempotency_key or ""), time.time(),
                    ),
                )
                conn.execute(
                    """INSERT INTO emotion_v3_states
                       (persona_id,subject_id,schema_version,state_json,updated_at)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(persona_id,subject_id) DO UPDATE SET
                         schema_version=excluded.schema_version,
                         state_json=excluded.state_json,
                         updated_at=excluded.updated_at""",
                    (
                        state.persona_id, state.subject_id, state.schema_version,
                        state_payload, time.time(),
                    ),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                conn.rollback()
                return False
            except Exception:
                conn.rollback()
                raise

    def recent_events(
        self, persona_id: str, subject_id: str, *, limit: int = 30
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connect().execute(
                """SELECT * FROM emotion_v3_events
                   WHERE persona_id=? AND subject_id=?
                   ORDER BY created_at DESC,id DESC LIMIT ?""",
                (str(persona_id), str(subject_id), max(1, min(int(limit), 200))),
            ).fetchall()
        return [dict(row) for row in rows]

    def event_stats(self, persona_id: str, subject_id: str, *, significant: float = 0.82) -> dict:
        with self._lock:
            row = self._connect().execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN significance>=? THEN 1 ELSE 0 END) AS significant
                   FROM emotion_v3_events WHERE persona_id=? AND subject_id=?""",
                (float(significant), str(persona_id), str(subject_id)),
            ).fetchone()
        return {
            "total": int(row["total"] or 0) if row else 0,
            "significant": int(row["significant"] or 0) if row else 0,
        }

    def delete_scope(self, persona_id: str, subject_id: str) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                "DELETE FROM emotion_v3_events WHERE persona_id=? AND subject_id=?",
                (persona_id, subject_id),
            )
            conn.execute(
                "DELETE FROM emotion_v3_states WHERE persona_id=? AND subject_id=?",
                (persona_id, subject_id),
            )
            conn.commit()

    def clear_events(self, persona_id: str, subject_id: str) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                "DELETE FROM emotion_v3_events WHERE persona_id=? AND subject_id=?",
                (persona_id, subject_id),
            )
            conn.commit()

    def clear_simulation_events(self, persona_id: str, subject_id: str) -> int:
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "DELETE FROM emotion_v3_events WHERE persona_id=? AND subject_id=? AND source_channel='ui_simulation'",
                (persona_id, subject_id),
            )
            conn.commit()
            return int(cur.rowcount or 0)

    def migrate_v2_json(
        self,
        source: Path,
        *,
        persona_id: str = DEFAULT_PERSONA_ID,
        subject_id: str = DEFAULT_SUBJECT_ID,
    ) -> bool:
        """Import one legacy JSON snapshot once without replaying old events."""
        key = f"v2_migrated:{persona_id}:{subject_id}"
        with self._lock:
            conn = self._connect()
            if conn.execute("SELECT 1 FROM emotion_v3_meta WHERE key=?", (key,)).fetchone():
                return False
            existing = conn.execute(
                "SELECT 1 FROM emotion_v3_states WHERE persona_id=? AND subject_id=?",
                (persona_id, subject_id),
            ).fetchone()
        if existing or not source.exists():
            self._mark_meta(key, "skipped")
            return False
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False

        needs = data.get("needs", {}) if isinstance(data.get("needs"), dict) else {}
        emotions = data.get("emotions", {}) if isinstance(data.get("emotions"), dict) else {}
        excitement = clamp(emotions.get("excitement", 0), 0, 100) / 100.0
        anger = clamp(emotions.get("anger", 0), 0, 100) / 100.0
        hurt = clamp(emotions.get("hurt", 0), 0, 100) / 100.0
        frustration = clamp(emotions.get("frustration", 0), 0, 100) / 100.0
        loneliness = clamp(emotions.get("loneliness", 0), 0, 100) / 100.0
        deep = clamp(data.get("deep_layer", 62), 0, 100) / 100.0
        needed = clamp(needs.get("needed", 65), 0, 100) / 100.0
        security = clamp(needs.get("security", 68), 0, 100) / 100.0
        autonomy = clamp(needs.get("autonomy", 60), 0, 100) / 100.0
        now = time.time()
        state = EmotionalStateV3(
            persona_id=persona_id,
            subject_id=subject_id,
            valence=clamp(excitement * 0.55 - anger * 0.55 - hurt * 0.45, -1, 1),
            arousal=clamp(excitement * 0.45 + anger * 0.65 + frustration * 0.45 - hurt * 0.15, -1, 1),
            pride=clamp(anger * 0.35 + loneliness * 0.12 - excitement * 0.18, -1, 1),
            guardedness=clamp((1.0 - autonomy) * 0.25 + anger * 0.30, -1, 1),
            connection=clamp(0.08 + loneliness * 0.62 + (1.0 - needed) * 0.18, 0, 1),
            trust=deep,
            intimacy=clamp((needed + security + deep) / 3.0, 0, 1),
            rupture=clamp(max(anger, hurt) * 0.55, 0, 1),
            last_update=float(data.get("last_update", now) or now),
            last_interaction=float(data.get("last_interaction", now) or now),
            enabled=bool(data.get("enabled", True)),
        ).normalize()
        self.save_state(state)
        self._mark_meta(key, "imported")
        return True

    def _mark_meta(self, key: str, value: str) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                """INSERT INTO emotion_v3_meta(key,value,updated_at) VALUES (?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                (key, value, time.time()),
            )
            conn.commit()
