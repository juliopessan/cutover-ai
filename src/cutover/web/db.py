from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    target TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS live_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dataset_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mapping_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL,                       -- completed | failed
    model TEXT, tier TEXT, score REAL,
    input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, latency_ms INTEGER, elapsed_ms INTEGER,
    pass_rate REAL, policy_action TEXT,
    mappings_json TEXT, checks_json TEXT, error TEXT,
    decision TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
    decision_note TEXT, decided_at TEXT, decided_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_mapping_runs_dataset ON mapping_runs(dataset_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_datasets_user ON datasets(user_id, id DESC);
"""


MAPPING_RUN_EXTRA_COLUMNS = {
    "prompt": "TEXT", "price_in": "REAL", "price_out": "REAL", "input_cap": "INTEGER", "output_cap": "INTEGER",
    "estimated_cost_usd": "REAL",
}


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(mapping_runs)")}
            for column, kind in MAPPING_RUN_EXTRA_COLUMNS.items():
                if column not in existing:  # additive migration for databases created before the column existed
                    conn.execute(f"ALTER TABLE mapping_runs ADD COLUMN {column} {kind}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()
