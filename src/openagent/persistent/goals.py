"""Goals: an outcome with a finish line, advanced by the heartbeat.

Pattern from langchain-samples/Persistent-Agent (skills/goals/SKILL.md). Two upgrades that
OpenAgent's harness makes possible:

  * Completion is enforced by code, not by a sentence in a prompt. `status=completed`
    without `evidence` is refused, and so is any change to a finished goal.
  * "Is anything due?" is a SQL query, so the harness can skip the model entirely on a
    heartbeat when nothing is due (see heartbeat.py).
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from openagent.db import parse_stamp, stamp

ACTIVE, PAUSED, COMPLETED, ABANDONED = "active", "paused", "completed", "abandoned"
STATUSES = (ACTIVE, PAUSED, COMPLETED, ABANDONED)
TERMINAL = (COMPLETED, ABANDONED)


class GoalError(ValueError):
    pass


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "goal"


def _parse_when(value: str | None) -> str | None:
    """next_check must carry an explicit UTC offset (Persistent-Agent's rule)."""
    if value in (None, ""):
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise GoalError(f"next_check is not ISO 8601: {value!r}") from exc
    if moment.tzinfo is None:
        raise GoalError("next_check needs an explicit UTC offset, e.g. 2026-03-03T09:00:00+00:00")
    return stamp(moment)


def _log(conn: sqlite3.Connection, goal_id: int, now: datetime, kind: str, detail: str = "") -> None:
    conn.execute("INSERT INTO goal_log (goal_id, at, kind, detail) VALUES (?, ?, ?, ?)",
                 (goal_id, stamp(now), kind, detail))


def create(conn: sqlite3.Connection, session_id: str, outcome: str, now: datetime, *,
           done_when: str = "", next_step: str = "", next_check: str | None = None) -> sqlite3.Row:
    outcome = outcome.strip()
    if not outcome:
        raise GoalError("a goal needs an outcome")
    slug = slugify(outcome)
    existing = conn.execute("SELECT * FROM goals WHERE session_id = ? AND slug = ?",
                            (session_id, slug)).fetchone()
    if existing is not None:                       # rephrasing must not create a second goal
        return existing
    cur = conn.execute(
        "INSERT INTO goals (session_id, slug, outcome, done_when, next_step, next_check, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, slug, outcome, done_when, next_step, _parse_when(next_check),
         stamp(now), stamp(now)))
    _log(conn, int(cur.lastrowid or 0), now, "created", outcome)
    conn.commit()
    return get(conn, session_id, int(cur.lastrowid or 0))


def get(conn: sqlite3.Connection, session_id: str, goal_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM goals WHERE id = ? AND session_id = ?",
                       (goal_id, session_id)).fetchone()
    if row is None:
        raise GoalError(f"no goal {goal_id} for this person")
    return row


def validate_update(row: sqlite3.Row, args: dict) -> None:
    """Raises GoalError if the update is not allowed. Used by the guard rule AND `update`."""
    status = args.get("status")
    if row["status"] in TERMINAL:
        raise GoalError(f"goal {row['id']} is {row['status']}; finished goals are not edited")
    if status is not None and status not in STATUSES:
        raise GoalError(f"status must be one of {', '.join(STATUSES)}")
    if status == COMPLETED and not str(args.get("evidence", "")).strip():
        raise GoalError("completing a goal needs evidence: what was checked, and where")
    if status == ABANDONED and not str(args.get("current_state", "")).strip():
        raise GoalError("abandoning a goal needs the reason in current_state")


def update(conn: sqlite3.Connection, session_id: str, goal_id: int, now: datetime, **fields: str | None) -> sqlite3.Row:
    row = get(conn, session_id, goal_id)
    validate_update(row, fields)
    sets: dict[str, str | None] = {}
    for key in ("current_state", "next_step", "evidence", "status"):
        if fields.get(key) is not None:
            sets[key] = str(fields[key])
    if "next_check" in fields:
        sets["next_check"] = _parse_when(fields["next_check"])
    sets["last_heartbeat"] = stamp(now)
    sets["updated_at"] = stamp(now)
    cols = ", ".join(f"{k} = ?" for k in sets)
    conn.execute(f"UPDATE goals SET {cols} WHERE id = ?", (*sets.values(), goal_id))
    kind = sets.get("status") if sets.get("status") in TERMINAL else "updated"
    _log(conn, goal_id, now, str(kind), str(fields.get("current_state") or fields.get("evidence") or ""))
    conn.commit()
    return get(conn, session_id, goal_id)


def list_goals(conn: sqlite3.Connection, session_id: str, *, status: str | None = None) -> list[sqlite3.Row]:
    if status:
        return conn.execute("SELECT * FROM goals WHERE session_id = ? AND status = ? ORDER BY id",
                            (session_id, status)).fetchall()
    return conn.execute("SELECT * FROM goals WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()


def is_due(row: sqlite3.Row, now: datetime) -> bool:
    if row["status"] != ACTIVE:
        return False
    return row["next_check"] is None or parse_stamp(row["next_check"]) <= now


def due_goals(conn: sqlite3.Connection, session_id: str, now: datetime) -> list[sqlite3.Row]:
    return [g for g in list_goals(conn, session_id, status=ACTIVE) if is_due(g, now)]


def digest(conn: sqlite3.Connection, session_id: str, now: datetime) -> str:
    """The goals block that goes into the system prompt. Finished goals stay out of it."""
    rows = [g for g in list_goals(conn, session_id) if g["status"] in (ACTIVE, PAUSED)]
    if not rows:
        return "Goals: none."
    lines = ["Goals (personal to this person):"]
    for g in rows:
        due = " | DUE NOW" if is_due(g, now) else ""
        lines.append(f"- id={g['id']} [{g['status']}] {g['outcome']} | state: {g['current_state'] or 'not checked yet'}"
                     f" | next: {g['next_step'] or 'unset'} | next_check: {g['next_check'] or 'next heartbeat'}{due}")
    return "\n".join(lines)
