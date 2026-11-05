import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models import Character, Fact

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    character TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    player_text TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repo:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def create_session(
        self, session_id: str, scenario_id: str, scene_id: str, character: Character
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, scenario_id, scene_id, character, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, scenario_id, scene_id, character.model_dump_json(), _now()),
            )

    def update_session_scene(self, session_id: str, scene_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET scene_id = ? WHERE id = ?", (scene_id, session_id)
            )

    def update_session_character(self, session_id: str, character: Character) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET character = ? WHERE id = ?",
                (character.model_dump_json(), session_id),
            )

    def get_session(self, session_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "scenario_id": row["scenario_id"],
            "scene_id": row["scene_id"],
            "character": Character.model_validate(json.loads(row["character"])),
            "created_at": row["created_at"],
        }

    def save_turn(
        self, session_id: str, seq: int, player_text: str, result_json: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO turns (session_id, seq, player_text, result, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, seq, player_text, result_json, _now()),
            )

    def list_turns(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, player_text, result, created_at FROM turns"
                " WHERE session_id = ? ORDER BY seq",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_fact(self, session_id: str, fact: Fact) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO facts (session_id, fact_id, text, source, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, fact.id, fact.text, fact.source, _now()),
            )

    def list_facts(self, session_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT text FROM facts WHERE session_id = ? ORDER BY id", (session_id,)
            ).fetchall()
        return [row["text"] for row in rows]
