"""Timers: when the agent wakes up on its own.

Three sources joined:

  Waku      waku/alwayson/timers.py. A due timer becomes a row in `events`, so a timer
            run is crash-safe like any message. The external id is `<timer>:<slot>`, so
            a restart that fires the same slot twice is a no-op.
  nanobot   cron/types.py. Three schedule kinds: `at` (once), `every` (an interval),
            and a calendar rule. `daily` supports an optional weekdays-only flag, and `cron`
            accepts a standard 5-field cron expression (min hour dom month dow).
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
    parts = str(value).strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid HH:MM clock value: {value!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 24 and 0 <= m <= 59 and not (h == 24 and m > 0)):
        raise ValueError(f"clock value out of range: {value!r}")
    return h * 60 + m


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




# ---- cron (5-field: min hour dom month dow) --------------------------------------
def _cron_field(field: str, lo: int, hi: int) -> set[int]:
    """Parse one cron field into allowed integer values."""
    values: set[int] = set()
    hi_bound = 7 if (lo == 0 and hi == 6) else hi  # allow DOW 7 as Sunday
    for part in field.split(','):
        part = part.strip()
        step = 1
        if '/' in part:
            part, step_s = part.split('/', 1)
            step = int(step_s)
            if step <= 0:
                raise ValueError(f"invalid cron step: {field!r}")
        if part == '*':
            start, end = lo, hi
        elif '-' in part:
            a, b = part.split('-', 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start < lo or end > hi_bound or start > end:
            raise ValueError(f"cron value out of range: {field!r}")
        for v in range(start, end + 1, step):
            values.add(0 if (lo == 0 and hi == 6 and v == 7) else v)
    return values


def _parse_cron(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int], bool, bool]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron expression must have 5 fields (min hour dom month dow), got {expr!r}")
    mins = _cron_field(parts[0], 0, 59)
    hours = _cron_field(parts[1], 0, 23)
    dom = _cron_field(parts[2], 1, 31)
    month = _cron_field(parts[3], 1, 12)
    dow = _cron_field(parts[4], 0, 6)
    dom_star = parts[2].strip() in ('*', '*/1') or dom == set(range(1, 32))
    dow_star = parts[4].strip() in ('*', '*/1') or dow == set(range(0, 7))
    # Reject impossible day/month combinations (e.g. Feb 31, Apr 31)
    max_days = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
    if not dom_star and not any(any(d <= max_days[m] for d in dom) for m in month):
        raise ValueError(f"impossible calendar date in cron expression: {expr!r}")
    return mins, hours, dom, month, dow, dom_star, dow_star


def cron_matches(dt: datetime, expr: str) -> bool:
    """True when local datetime matches a 5-field cron expression."""
    mins, hours, dom, month, dow, dom_star, dow_star = _parse_cron(expr)
    if dt.minute not in mins or dt.hour not in hours or dt.month not in month:
        return False
    dom_ok = dt.day in dom
    cron_dow_py = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}  # cron 0=Sun -> python weekday
    dow_ok = dt.weekday() in {cron_dow_py[d] for d in dow}
    if dom_star and dow_star:
        return True
    if dom_star:
        return dow_ok
    if dow_star:
        return dom_ok
    return dom_ok or dow_ok  # Vixie cron: either matches when both restricted


def next_cron(expr: str, tz: str, after: datetime) -> datetime:
    """Next UTC datetime strictly after `after` that matches the cron expression."""
    zone = ZoneInfo(tz)
    mins, hours, dom, month, dow, dom_star, dow_star = _parse_cron(expr)
    cron_dow_py = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}
    # Step in UTC to avoid DST fall-back fold resets / skipped repeated-hour bugs.
    cur_utc = after.astimezone(ZoneInfo("UTC")).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(8 * 366 * 24 * 60):  # 8 years covers leap-day schedules
        local = cur_utc.astimezone(zone)
        if local.minute in mins and local.hour in hours and local.month in month:
            dom_ok = local.day in dom
            dow_ok = local.weekday() in {cron_dow_py[d] for d in dow}
            if dom_star and dow_star:
                day_ok = True
            elif dom_star:
                day_ok = dow_ok
            elif dow_star:
                day_ok = dom_ok
            else:
                day_ok = dom_ok or dow_ok
            if day_ok:
                return cur_utc
        cur_utc += timedelta(minutes=1)
    raise ValueError(f"cron expression {expr!r} did not match within search window")
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
        secs = int(spec)
        if secs <= 0:
            raise ValueError(f"every timer spec must be > 0 seconds, got {spec!r}")
        return now + timedelta(seconds=secs)
    if kind == "daily":
        return _next_daily(spec, tz, now)
    if kind == "cron":
        return next_cron(spec, tz, now)
    raise ValueError(f"unknown timer kind {kind!r}: at | every | daily | cron")


def add(conn: sqlite3.Connection, *, session_id: str, reply_to: dict, kind: str, spec: str,
        message: str, now: datetime, tz: str = "UTC", active_start: str | None = None,
        active_end: str | None = None) -> int:
    if active_start is not None:
        active_start = str(active_start).strip()
        _minutes(active_start)  # validate
    if active_end is not None:
        active_end = str(active_end).strip()
        _minutes(active_end)  # validate
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
    if row["kind"] == "cron":
        return next_cron(row["spec"], row["tz"], now)
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
