"""One SQLite file holds everything that must survive a crash.

Descends from waku/db.py. The additions are `parked` (approvals), `timers`
with an active-hours window, `kv` (the Dream cursor) and `calendar_events`.

Read any table yourself:  sqlite3 ~/.openagent/state.db 'SELECT * FROM events'
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
-- Semantic memory: durable facts, keyword-searched with FTS5 (BM25).
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    subject TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    subject, content, content=facts, content_rowid=id
);
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, subject, content) VALUES (new.id, new.subject, new.content);
END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, subject, content)
    VALUES ('delete', old.id, old.subject, old.content);
END;
CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, subject, content)
    VALUES ('delete', old.id, old.subject, old.content);
    INSERT INTO facts_fts(rowid, subject, content) VALUES (new.id, new.subject, new.content);
END;

-- Episodic memory: dated things that happened.
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    happened_at TEXT NOT NULL,
    summary TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    summary, content=episodes, content_rowid=id
);
CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, summary) VALUES (new.id, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary)
    VALUES ('delete', old.id, old.summary);
END;
CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary)
    VALUES ('delete', old.id, old.summary);
    INSERT INTO episodes_fts(rowid, summary) VALUES (new.id, new.summary);
END;

-- Raw chat log. The Dream pass reads rows past its cursor.
CREATE TABLE IF NOT EXISTS chat_log (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Always-on: the inbox. A row is on disk before any model is called.
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL,
    source TEXT NOT NULL,            -- telegram | slack | github | timer | approval
    external_id TEXT NOT NULL,       -- the sender's own id for the message
    session_id TEXT NOT NULL,
    payload TEXT NOT NULL,           -- JSON
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | claimed | done | failed
    UNIQUE (source, external_id)     -- a redelivery is a no-op
);

-- Always-on: the outbox. A run never calls a messaging API itself.
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    target TEXT NOT NULL,            -- JSON address
    body TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | sent | dead | cancelled
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT ''
);

-- Timers: nanobot's schedule kinds + OpenClaw's active-hours window.
CREATE TABLE IF NOT EXISTS timers (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    reply_to TEXT NOT NULL,          -- JSON address
    kind TEXT NOT NULL,              -- at | every | daily
    spec TEXT NOT NULL,
    message TEXT NOT NULL,
    next_fire_at TEXT NOT NULL,
    tz TEXT NOT NULL DEFAULT 'UTC',
    active_start TEXT,               -- HH:MM, NULL = always
    active_end TEXT,
    enabled INTEGER NOT NULL DEFAULT 1
);

-- One call waits per approver. It waits 72 hours.
CREATE TABLE IF NOT EXISTS parked (
    approver_session TEXT PRIMARY KEY,
    origin_session TEXT NOT NULL,
    origin_address TEXT NOT NULL,
    tool TEXT NOT NULL,
    args TEXT NOT NULL,              -- JSON, stored exactly as the model sent it
    args_sha256 TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    start TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def utc_now() -> datetime:
    return datetime.now(UTC)


def stamp(moment: datetime) -> str:
    """One fixed UTC form, so comparing two stamps as text compares the times."""
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def parse_stamp(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def connect(home: Path) -> sqlite3.Connection:
    home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(home / "state.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    # lightweight migrations for parked turn resume state
    _ensure_column(conn, "parked", "resume_state", "TEXT NOT NULL DEFAULT ''")
    conn.commit()
    return conn


def kv_get(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO kv (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()
