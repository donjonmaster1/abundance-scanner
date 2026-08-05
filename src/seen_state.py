"""Tracks already-processed document IDs across weekly runs (state/seen.sqlite)
so the same bill/rule/matter isn't re-pulled through the LLM stages twice.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "state" / "seen.sqlite"


class SeenStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                id TEXT PRIMARY KEY,
                first_seen_utc TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def filter_unseen(self, ids: list[str]) -> list[str]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self.conn.execute(f"SELECT id FROM seen WHERE id IN ({placeholders})", ids).fetchall()
        already_seen = {r[0] for r in rows}
        return [i for i in ids if i not in already_seen]

    def mark_seen(self, ids: list[str]) -> None:
        if not ids:
            return
        now = datetime.now(timezone.utc).isoformat()
        self.conn.executemany(
            "INSERT OR IGNORE INTO seen (id, first_seen_utc) VALUES (?, ?)",
            [(i, now) for i in ids],
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "SeenStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
