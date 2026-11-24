"""The event inbox: one row in `events` per incoming message.

Descends from waku/alwayson/events.py. A handler calls `insert` and returns.
The worker calls `claim_next`, then `claim_session`, then `mark`. Each function is
one short transaction, so a row is pending, claimed, done or failed on disk at every
moment and a process that dies loses nothing.

  UNIQUE(source, external_id)   a redelivery is a no-op. Telegram's update_id, Slack's
                                event_id and GitHub's X-GitHub-Delivery are the ids.
  recover()                     at startup, every `claimed` row goes back to `pending`:
                                a claimed row then belongs to a run that died.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from openagent.db import stamp

STATUSES = ("pending", "claimed", "done", "failed")


@dataclass(frozen=True)
class Event:
    id: int
    received_at: str
    source: str
    external_id: str
    session_id: str
    payload: dict
    status: str


def _event(row: sqlite3.Row) -> Event:
    return Event(row["id"], row["received_at"], row["source"], row["external_id"],
                 row["session_id"], json.loads(row["payload"]), row["status"])


def insert(conn: sqlite3.Connection, *, source: str, external_id: str, session_id: str,
           payload: dict, now: datetime) -> int | None:
    """One pending row. None when this source already delivered this external_id."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO events (received_at, source, external_id, session_id, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        (stamp(now), source, str(external_id), session_id, json.dumps(payload)))
    conn.commit()
    return cur.lastrowid if cur.rowcount else None


def claim_next(conn: sqlite3.Connection) -> Event | None:
    row = conn.execute(
        "UPDATE events SET status = 'claimed' WHERE id = "
        "(SELECT id FROM events WHERE status = 'pending' ORDER BY id LIMIT 1) RETURNING *").fetchone()
    conn.commit()
    return _event(row) if row else None


def claim_session(conn: sqlite3.Connection, session_id: str) -> list[Event]:
    """Every other pending row of one conversation, oldest first."""
    rows = conn.execute(
        "UPDATE events SET status = 'claimed' WHERE status = 'pending' AND session_id = ? RETURNING *",
        (session_id,)).fetchall()
    conn.commit()
    return sorted((_event(r) for r in rows), key=lambda e: e.id)


def mark(conn: sqlite3.Connection, ids: list[int], status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"{status!r} is not an event status: {', '.join(STATUSES)}")
    conn.executemany("UPDATE events SET status = ? WHERE id = ?", [(status, i) for i in ids])
    conn.commit()


def recover(conn: sqlite3.Connection) -> int:
    cur = conn.execute("UPDATE events SET status = 'pending' WHERE status = 'claimed'")
    conn.commit()
    return cur.rowcount
