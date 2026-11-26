"""The heartbeat: one hourly wake-up per person, which costs nothing when nothing is due.

Persistent-Agent (middleware/per_user_schedules.py + heartbeat.py) creates one hourly
schedule per person and runs a full model turn on every tick; the turn then replies
`[quiet]` most of the time. That is 24 model calls per person per day to say nothing.

OpenAgent can do better because its goals are rows:

  * the heartbeat is a normal cron timer, with an active-hours window (deferred, not dropped)
  * `pre_run` answers `[quiet]` WITHOUT calling the model when no goal is due and no
    offer is allowed. The model only wakes for real work.
  * `ensure_heartbeat` is idempotent and removes duplicates from concurrent first messages
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta

from openagent.alwayson import timers
from openagent.db import kv_get, kv_set, parse_stamp, stamp
from openagent.persistent import attention, goals

HEARTBEAT_SPEC = "0 * * * *"
OFFER_CONSIDER_EVERY = timedelta(hours=8)     # at most 3 model wake-ups a day just to think about offers
HEARTBEAT_PROMPT = (
    "[heartbeat] Hourly check-in. Follow the goals block: advance goals that are DUE NOW within "
    "what the person already approved, verify outcomes before completing them (evidence is "
    "required), and set next_check. Ask before booking, sending or deleting anything. "
    "Message the person only for real progress, a blocker, or a finished goal. "
    "Otherwise reply exactly [quiet]. This is an automated run: do not onboard or chat."
)
_TAG = re.compile(r"^\[timer\]\s*\[heartbeat\]")


def is_heartbeat(text: str) -> bool:
    """True only when EVERY line is a heartbeat tick.

    The worker batches events from one session into one text. If a person's message was
    batched with a tick, this is False, so the quiet short-circuit can never swallow it."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return bool(lines) and all(_TAG.match(ln) or ln.startswith("[heartbeat]") for ln in lines)


def ensure_heartbeat(conn: sqlite3.Connection, session_id: str, reply_to: dict, now: datetime, *,
                     window: tuple[str, str, str] = ("08:00", "20:00", "UTC")) -> int:
    rows = conn.execute("SELECT id FROM timers WHERE session_id = ? AND message LIKE '[heartbeat]%' "
                        "ORDER BY id", (session_id,)).fetchall()
    if rows:
        for extra in rows[1:]:                       # duplicates from concurrent first DMs
            conn.execute("DELETE FROM timers WHERE id = ?", (extra["id"],))
        conn.commit()
        return int(rows[0]["id"])
    hours = attention.working_hours(conn, session_id)
    start, end, tz = (hours.start, hours.end, hours.tz) if hours else window
    return timers.add(conn, session_id=session_id, reply_to=reply_to, kind="cron", spec=HEARTBEAT_SPEC,
                      message=HEARTBEAT_PROMPT, now=now, tz=tz, active_start=start, active_end=end)


def heartbeat_needs_model(conn: sqlite3.Connection, session_id: str, now: datetime) -> tuple[bool, str]:
    """Decide, with SQL and no model, whether this tick deserves a model turn."""
    due = goals.due_goals(conn, session_id, now)
    if due:
        return True, f"{len(due)} goal(s) due"
    ok, why = attention.check_offer(conn, session_id, "__probe__", now)
    if not ok or not attention.recent_activity(conn, session_id, now):
        return False, f"nothing due; offers: {why if not ok else 'no recent context'}"
    last = kv_get(conn, f"offer_consider:{session_id}")
    if last and now - parse_stamp(last) < OFFER_CONSIDER_EVERY:
        return False, "nothing due; offers were considered recently"
    kv_set(conn, f"offer_consider:{session_id}", stamp(now))
    return True, "an offer is allowed and there is recent context (considered at most every 8h)"
