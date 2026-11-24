"""Approvals: a call that needs a yes waits for it. park, answer, resume.

Descends from waku/alwayson/approvals.py, with the verdict coming from guard.py.

  park     the call is stored exactly as the model sent it, with a SHA-256 of its name
           and arguments. One outbox row asks the owner. The run ends parked and sends
           no reply of its own.
  answer   the owner's reply arrives as an ordinary event. The worker reads it BEFORE
           starting a run. `yes` replays the stored call, `no` discards it, anything
           else is an ordinary message.
  resume   the outcome becomes an event in the conversation that parked, and the next
           run there starts with it.

The model is not asked again after a yes, so it cannot change the arguments. The guard
runs once more on the replay: it turns a HOLD into ALLOW for this exact hash, and
still refuses anything that has become a DENY.

One call waits per approver, for 72 hours.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta

from openagent.alwayson import events, outbox
from openagent.db import parse_stamp, stamp
from openagent.guard import ALLOW, Grant, Guard, call_hash
from openagent.tools import Ctx, ToolRegistry
from openagent.trace import silent

TTL = timedelta(hours=72)
_YES = re.compile(r"^\s*(?:yes|y|approve|approved|ok|go ahead)\W*$", re.I)
_NO = re.compile(r"^\s*(?:no|n|deny|reject|cancel|stop)\W*$", re.I)


def park(conn: sqlite3.Connection, *, approver: str, origin_session: str, origin_address: str,
         tool: str, args: dict, now: datetime) -> str | None:
    """Store the call and return its hash, or None when this approver already has one waiting."""
    pending = conn.execute("SELECT expires_at FROM parked WHERE approver_session = ?", (approver,)).fetchone()
    if pending and parse_stamp(pending["expires_at"]) > now:
        return None
    digest = call_hash(tool, args)
    conn.execute(
        "INSERT OR REPLACE INTO parked (approver_session, origin_session, origin_address, tool, args, "
        "args_sha256, requested_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (approver, origin_session, origin_address, tool, json.dumps(args, ensure_ascii=False), digest,
         stamp(now), stamp(now + TTL)))
    conn.commit()
    return digest


def question(tool: str, args: dict) -> str:
    shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"OpenAgent wants to run {tool}({shown}). Reply yes or no. It waits 72 hours."


def answer(conn: sqlite3.Connection, *, session_id: str, text: str, now: datetime, guard: Guard,
           tools: ToolRegistry, ctx: Ctx, observer=silent) -> str | None:
    """Handle yes/no from an approver. Returns None when the text is an ordinary message."""
    row = conn.execute("SELECT * FROM parked WHERE approver_session = ?", (session_id,)).fetchone()
    if row is None or not (_YES.match(text) or _NO.match(text)):
        return None
    conn.execute("DELETE FROM parked WHERE approver_session = ?", (session_id,))
    conn.commit()
    if parse_stamp(row["expires_at"]) <= now:
        outcome = f"The approval for {row['tool']} expired after 72 hours and was not run."
    elif _NO.match(text):
        outcome = f"The owner said no. {row['tool']} was not run."
        observer("approval", {"title": f"{row['tool']} discarded (no)", "sha256": row["args_sha256"][:12]})
    else:
        args = json.loads(row["args"])
        # the stored args must hash to the stored digest, or the row was tampered with
        if call_hash(row["tool"], args) != row["args_sha256"]:
            outcome = f"{row['tool']} was not run: the stored call no longer matches its hash."
        else:
            decision = guard.decide(row["tool"], args, ctx, Grant(row["args_sha256"]))
            if decision.verdict == ALLOW:
                result = tools.execute(row["tool"], args, ctx)
                outcome = f"The owner approved {row['tool']}. Result: {result}"
                observer("approval", {"title": f"{row['tool']} approved and run exactly as stored",
                                      "sha256": row["args_sha256"][:12], "result": result})
            else:
                outcome = f"{row['tool']} was not run: {decision.reason}."
                observer("approval", {"title": f"replay refused by the guard ({decision.verdict})",
                                      "reason": decision.reason})
    events.insert(conn, source="approval", external_id=f"{row['args_sha256']}:{stamp(now)}",
                  session_id=row["origin_session"], now=now,
                  payload={"text": f"[approval] {outcome}",
                           "reply_to": outbox_target(row["origin_address"])})
    return outcome


def outbox_target(address: str) -> dict:
    parsed = outbox.parse_address(address)
    return {"via": parsed[0], **parsed[1]} if parsed else {}
