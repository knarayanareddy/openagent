"""Attention budget: being always-on must not mean always messaging.

Persistent-Agent states its rules in prose (skills/goals/SKILL.md, "protect attention"):
at most one unsolicited offer per 24 h, seven days of silence after an unanswered offer,
declined topics stay closed, offers only in working hours. A model can forget a sentence.
Here the same rules are a guard check over the `offers` table, so they hold even when
the model does not remember them.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from openagent.alwayson.timers import ActiveHours, within_active_hours
from openagent.db import kv_get, kv_set, parse_stamp, stamp

QUIET = "[quiet]"
MAX_OFFERS_PER_DAY = 1
UNANSWERED_BACKOFF = timedelta(days=7)


def set_working_hours(conn: sqlite3.Connection, session_id: str, start: str, end: str, tz: str) -> None:
    kv_set(conn, f"working_hours:{session_id}", json.dumps({"start": start, "end": end, "tz": tz}))


def working_hours(conn: sqlite3.Connection, session_id: str) -> ActiveHours | None:
    raw = kv_get(conn, f"working_hours:{session_id}")
    if not raw:
        return None
    data = json.loads(raw)
    return ActiveHours(data["start"], data["end"], data["tz"])


def check_offer(conn: sqlite3.Connection, session_id: str, topic: str, now: datetime) -> tuple[bool, str]:
    """May the agent make an unsolicited offer on `topic` right now?"""
    hours = working_hours(conn, session_id)
    if hours is None:
        return False, "working hours are unknown; wait for a normal conversation"
    if not within_active_hours(hours, now):
        return False, f"outside working hours {hours.start}-{hours.end} {hours.tz}"
    rows = conn.execute("SELECT * FROM offers WHERE session_id = ? ORDER BY id DESC", (session_id,)).fetchall()
    recent = [r for r in rows if now - parse_stamp(r["offered_at"]) < timedelta(days=1)]
    if len(recent) >= MAX_OFFERS_PER_DAY:
        return False, "one unsolicited offer per 24 hours is the ceiling"
    for r in rows:
        if r["outcome"] == "pending" and now - parse_stamp(r["offered_at"]) < UNANSWERED_BACKOFF:
            return False, "the last offer is unanswered; wait seven days, do not nudge"
    for r in rows:
        if r["topic"].lower() == topic.lower() and r["outcome"] in ("declined", "pending"):
            return False, f"topic {topic!r} was already offered and not taken up"
    return True, "ok"


def record_offer(conn: sqlite3.Connection, session_id: str, topic: str, text: str, now: datetime) -> int:
    cur = conn.execute("INSERT INTO offers (session_id, topic, text, offered_at) VALUES (?, ?, ?, ?)",
                       (session_id, topic, text, stamp(now)))
    conn.commit()
    return int(cur.lastrowid or 0)


def resolve_offer(conn: sqlite3.Connection, session_id: str, topic: str, outcome: str) -> int:
    if outcome not in ("answered", "declined"):
        raise ValueError("outcome must be answered or declined")
    cur = conn.execute("UPDATE offers SET outcome = ? WHERE session_id = ? AND lower(topic) = lower(?) "
                       "AND outcome = 'pending'", (outcome, session_id, topic))
    conn.commit()
    return cur.rowcount


def touch_activity(conn: sqlite3.Connection, session_id: str, now: datetime) -> None:
    """Remember when the person last spoke, using the harness clock (testable, replayable)."""
    kv_set(conn, f"last_user_msg:{session_id}", stamp(now))


def recent_activity(conn: sqlite3.Connection, session_id: str, now: datetime, hours: int = 24) -> bool:
    """Has the person said anything lately? (A heartbeat with no context has no reason to offer.)"""
    raw = kv_get(conn, f"last_user_msg:{session_id}")
    return bool(raw) and now - parse_stamp(raw) < timedelta(hours=hours)
