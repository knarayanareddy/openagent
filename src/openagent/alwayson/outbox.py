"""The outbox: one row per outgoing message, sent exactly once.

Descends from waku/alwayson/outbox.py, dispatcher.py and the address forms in
waku/alwayson/senders/. A run never calls Telegram, Slack or GitHub. It calls
`insert`, and `dispatch` sends the row.

  idempotency_key is UNIQUE, so a run replayed after a crash writes the same key
  again and the second row is dropped. The person gets one reply.

  pending    waiting for its next attempt
  sent       delivered
  dead       failed 5 times; stop trying
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta

from openagent.db import parse_stamp, stamp
from openagent.trace import silent

BACKOFF_SECONDS = (10, 60, 600, 3600)      # the wait after the 1st, 2nd, 3rd and 4th failure
MAX_ATTEMPTS = 5

_TELEGRAM = re.compile(r"^telegram:(-?\d+)$")
_SLACK = re.compile(r"^slack:([A-Z0-9]+)(?::(\d+\.\d+))?$")
_GITHUB = re.compile(r"^github:([^#\s]+)#([1-9]\d*)$")
_GENERIC = re.compile(r"^(local|cli|stdout|webhook):(.+)$")


def parse_address(text: str) -> tuple[str, dict] | None:
    """telegram:<chat id> | slack:<channel>[:<thread>] | github:<owner>/<repo>#<number> | local/cli/stdout/webhook:<id>"""
    text = (text or "").strip()
    if m := _TELEGRAM.match(text):
        return "telegram", {"chat_id": int(m[1])}
    if m := _SLACK.match(text):
        return "slack", {"channel": m[1], **({"thread_ts": m[2]} if m[2] else {})}
    if m := _GITHUB.match(text):
        return "github", {"repo": m[1], "number": int(m[2])}
    if m := _GENERIC.match(text):
        return m[1], {"chat_id": m[2]}
    return None


def format_address(channel: str, target: dict) -> str:
    if channel == "telegram":
        return f"telegram:{target.get('chat_id', '')}"
    if channel == "slack":
        return f"slack:{target.get('channel', '')}" + (f":{target['thread_ts']}" if target.get("thread_ts") else "")
    if channel == "github":
        return f"github:{target.get('repo', '')}#{target.get('number', '')}"
    # generic fallback for cli/local/custom channels
    ident = target.get("chat_id") or target.get("channel") or target.get("id") or "default"
    return f"{channel}:{ident}"


def insert(conn: sqlite3.Connection, *, run_id: str, channel: str, target: dict, body: str,
           idempotency_key: str, now: datetime) -> int | None:
    cur = conn.execute(
        "INSERT OR IGNORE INTO outbox (run_id, channel, target, body, idempotency_key, next_attempt_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, channel, json.dumps(target), body, idempotency_key, stamp(now)))
    conn.commit()
    return cur.lastrowid if cur.rowcount else None


def due(conn: sqlite3.Connection, now: datetime, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM outbox WHERE status = 'pending' AND next_attempt_at <= ? ORDER BY id LIMIT ?",
        (stamp(now), limit)).fetchall()


def _fail(conn: sqlite3.Connection, row: sqlite3.Row, error: str, now: datetime) -> str:
    attempts = row["attempts"] + 1
    if attempts >= MAX_ATTEMPTS:
        status, retry = "dead", row["next_attempt_at"]
    else:
        status, retry = "pending", stamp(now + timedelta(seconds=BACKOFF_SECONDS[attempts - 1]))
    conn.execute("UPDATE outbox SET status = ?, attempts = ?, next_attempt_at = ?, last_error = ? "
                 "WHERE id = ?", (status, attempts, retry, error[:300], row["id"]))
    conn.commit()
    return status


Sender = Callable[[dict, str], None]


def dispatch(conn: sqlite3.Connection, senders: dict[str, Sender], now: datetime,
             observer=silent) -> dict[str, int]:
    """Send every due row. A sender that raises schedules a retry with backoff."""
    counts = {"sent": 0, "retry": 0, "dead": 0}
    for row in due(conn, now):
        target = json.loads(row["target"])
        addr = format_address(row["channel"], target)
        try:
            senders[row["channel"]](target, row["body"])
        except Exception as exc:                        # noqa: BLE001
            status = _fail(conn, row, f"{type(exc).__name__}: {exc}", now)
            kind = "dead" if status == "dead" else "retry"
            counts[kind] += 1
            wait = None if status == "dead" else BACKOFF_SECONDS[row["attempts"]]
            observer(kind, {"title": f"{addr}: attempt {row['attempts'] + 1} failed, "
                                     + ("giving up" if wait is None else f"retry in {wait}s"),
                            "error": str(exc)})
            continue
        conn.execute("UPDATE outbox SET status = 'sent', attempts = attempts + 1 WHERE id = ?", (row["id"],))
        conn.commit()
        counts["sent"] += 1
        observer("sent", {"title": f"sent to {addr}", "body": row["body"]})
    return counts


def next_attempt(conn: sqlite3.Connection, outbox_id: int) -> datetime:
    row = conn.execute("SELECT next_attempt_at FROM outbox WHERE id = ?", (outbox_id,)).fetchone()
    return parse_stamp(row["next_attempt_at"])
