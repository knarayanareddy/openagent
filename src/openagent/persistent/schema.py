"""Tables for the Persistent-Agent patterns, added to the same state.db.

Persistent-Agent keeps goals as markdown files in a managed memory store. OpenAgent's
philosophy is "one SQLite file holds everything that must survive a crash", so the same
ideas live in tables here: queryable, transactional, and covered by the same backups.

    sqlite3 ~/.openagent/state.db 'SELECT slug, status, next_check FROM goals'
"""

from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,            -- whose goal it is (personal, never shared)
    slug TEXT NOT NULL,
    outcome TEXT NOT NULL,               -- the finish line
    done_when TEXT NOT NULL DEFAULT '',  -- how completion is verified
    status TEXT NOT NULL DEFAULT 'active',   -- active | paused | completed | abandoned
    current_state TEXT NOT NULL DEFAULT '',
    next_step TEXT NOT NULL DEFAULT '',
    next_check TEXT,                     -- UTC stamp; NULL = due on the next heartbeat
    last_heartbeat TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '',   -- required to complete
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (session_id, slug)
);

CREATE TABLE IF NOT EXISTS goal_log (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,                  -- created | updated | completed | abandoned | denied
    detail TEXT NOT NULL DEFAULT ''
);

-- Unsolicited offers of help. The attention budget reads this table.
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    text TEXT NOT NULL,
    offered_at TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'pending'  -- pending | answered | declined
);

-- A person's adoption of a shared playbook: their settings plus the timer that runs it.
CREATE TABLE IF NOT EXISTS playbook_adoptions (
    session_id TEXT NOT NULL,
    name TEXT NOT NULL,
    settings TEXT NOT NULL DEFAULT '{}',
    timer_id INTEGER NOT NULL,
    adopted_at TEXT NOT NULL,
    PRIMARY KEY (session_id, name)
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
