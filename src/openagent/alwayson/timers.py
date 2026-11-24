"""Timers: when the agent wakes up on its own.

Three sources joined:

  Waku      waku/alwayson/timers.py. A due timer becomes a row in `events`, so a timer
            run is crash-safe like any message. The external id is `<timer>:<slot>`, so
            a restart that fires the same slot twice is a no-op.
  nanobot   cron/types.py. Three schedule kinds: `at` (once), `every` (an interval),
            and a calendar rule. Here the calendar rule is `daily` with an optional
            weekdays-only flag. For full cron expressions, swap `_next_daily` for croniter.
  OpenClaw  src/cron/active-hours.ts, ported to Python below. A timer may carry a
            wall-clock window. Outside it the timer is DEFERRED, not dropped: it stays
            due and fires on the first poll inside the window.

Missed slots are coalesced into one firing. A laptop closed over a weekend wakes to one
"good morning", not nine.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from openagent.alwayson import events
from openagent.db import parse_stamp, stamp
from openagent.trace import silent

# ---- active hours (port of OpenClaw's isCronWithinActiveHours) --------------------


@dataclass(frozen=True)
class ActiveHours:
    start: str                    # "HH:MM"
    end: str                      # "HH:MM"; "24:00" is allowed as an end
    tz: str = "UTC"


def _minutes(value: str) -> int:
    return int(value[:2]) * 60 + int(value[3:5])


def within_active_hours(active: ActiveHours | None, now: datetime) -> bool:
    """Wall-clock comparison. Overnight windows work (22:00 to 06:00).
    start == end is an empty window, exactly as in the TypeScript."""
    if active is None:
        return True
    local = now.astimezone(ZoneInfo(active.tz))
    minute = local.hour * 60 + local.minute
    start, end = _minutes(active.start), _minutes(active.end)
    if start == end:
        return False
    return start <= minute < end if end > start else (minute >= start or minute < end)


# ---- schedules (nanobot's kinds) --------------------------------------------------

def _next_daily(spec: str, tz: str, after: datetime) -> datetime:
    """spec: "09:00" or "09:00 weekdays"."""
    clock, _, flag = spec.partition(" ")
    hour, minute = (int(p) for p in clock.split(":"))
    zone = ZoneInfo(tz)
    local = after.astimezone(zone)
    candidate = datetime.combine(local.date(), time(hour, minute), tzinfo=zone)
    if candidate <= after:
        candidate += timedelta(days=1)
    while flag == "weekdays" and candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.astimezone(ZoneInfo("UTC"))


def first_fire(kind: str, spec: str, tz: str, now: datetime) -> datetime:
    if kind == "at":
        return parse_stamp(spec)
    if kind == "every":
        return now + timedelta(seconds=int(spec))
    if kind == "daily":
        return _next_daily(spec, tz, now)
    raise ValueError(f"unknown timer kind {kind!r}: at | every | daily")


def add(conn: sqlite3.Connection, *, session_id: str, reply_to: dict, kind: str, spec: str,
        message: str, now: datetime, tz: str = "UTC", active_start: str | None = None,
        active_end: str | None = None) -> int:
    fire = first_fire(kind, spec, tz, now)
    cur = conn.execute(
        "INSERT INTO timers (session_id, reply_to, kind, spec, message, next_fire_at, tz, "
        "active_start, active_end) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, json.dumps(reply_to), kind, spec, message, stamp(fire), tz,
         active_start, active_end))
    conn.commit()
    return int(cur.lastrowid or 0)


def _advance(row: sqlite3.Row, now: datetime) -> datetime | None:
    if row["kind"] == "at":
        return None
    if row["kind"] == "every":
        step = timedelta(seconds=int(row["spec"]))
        nxt = parse_stamp(row["next_fire_at"])
        while nxt <= now:                      # coalesce every missed slot
            nxt += step
        return nxt
    return _next_daily(row["spec"], row["tz"], now)


def fire_due(conn: sqlite3.Connection, now: datetime, observer=silent) -> list[int]:
    """Turn each due timer into an event. Returns the new event ids."""
    fired: list[int] = []
    for row in conn.execute("SELECT * FROM timers WHERE enabled = 1 AND next_fire_at <= ? ORDER BY id",
                            (stamp(now),)).fetchall():
        active = (ActiveHours(row["active_start"], row["active_end"], row["tz"])
                  if row["active_start"] and row["active_end"] else None)
        if not within_active_hours(active, now):
            observer("defer", {"title": f"timer {row['id']} deferred, outside "
                                        f"{active.start}-{active.end} {active.tz}",  # type: ignore[union-attr]
                               "message": row["message"]})
            continue                            # stays due; fires on the first in-window poll
        event_id = events.insert(
            conn, source="timer", external_id=f"{row['id']}:{row['next_fire_at']}",
            session_id=row["session_id"], now=now,
            payload={"text": f"[timer] {row['message']}", "reply_to": json.loads(row["reply_to"])})
        nxt = _advance(row, now)
        if nxt is None:
            conn.execute("UPDATE timers SET enabled = 0 WHERE id = ?", (row["id"],))
        else:
            conn.execute("UPDATE timers SET next_fire_at = ? WHERE id = ?", (stamp(nxt), row["id"]))
        conn.commit()
        if event_id:
            fired.append(event_id)
            observer("timer", {"title": f"timer {row['id']} fired -> event {event_id}",
                               "message": row["message"]})
    return fired
