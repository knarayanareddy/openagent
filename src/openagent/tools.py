"""Tools: a registry, the built-ins, and the guard rules that govern them.

Descends from waku/tools/registry.py and the tool modules under waku/tools/.
The built-ins are deliberately few. Each one exists to show a different path
through the guard:

  remember_preference  ALLOW  writes curated memory (and can be refused by its scan)
  recall               ALLOW  reads semantic memory
  book_meeting         ALLOW  writes the calendar
  schedule_task        ALLOW  sets a timer
  send_message         HOLD   unless the address is the owner's. DENY when not an address.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openagent.alwayson import outbox, timers
from openagent.guard import ALLOW, DENY, HOLD, Decision
from openagent.memory.curated import CuratedMemory
from openagent.memory.semantic import SemanticMemory


@dataclass
class Ctx:
    """What a tool may touch. Built per run, so nothing leaks between sessions."""
    conn: sqlite3.Connection
    curated: CuratedMemory
    semantic: SemanticMemory
    session_id: str
    reply_to: dict
    now: datetime
    run_id: str
    owner_addresses: list[str] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[[dict, Ctx], str]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [{"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in self._tools.values()]

    def execute(self, name: str, args: dict, ctx: Ctx) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"error: unknown tool {name!r}"
        try:
            return tool.fn(args, ctx)
        except Exception as exc:                    # noqa: BLE001 - a tool error is data for the model
            return f"error: {type(exc).__name__}: {exc}"


# ---- the tools ---------------------------------------------------------------

def _remember_preference(args: dict, ctx: Ctx) -> str:
    action = str(args.get("action", "add")).lower()
    target = str(args.get("target", "user")).lower()
    if target not in ("user", "memory"):
        return json.dumps({"success": False, "error": "target must be 'user' or 'memory'"})
    entry = str(args.get("entry", ""))
    old_text = str(args.get("old_text", ""))
    if action in ("replace", "remove") and not old_text.strip():
        old_text = entry
    if action == "replace":
        result = ctx.curated.replace(target, old_text, entry)
    elif action == "remove":
        result = ctx.curated.remove(target, old_text)
    else:
        result = ctx.curated.add(target, entry)
    return json.dumps(result)


def _recall(args: dict, ctx: Ctx) -> str:
    return ctx.semantic.recall_text(str(args.get("query", ""))) or "nothing found"


def _book_meeting(args: dict, ctx: Ctx) -> str:
    title = f"Catch-up with {args['with']}"
    start = f"{args['day']} {args['time']}"
    ctx.conn.execute("INSERT INTO calendar_events (title, start) VALUES (?, ?)", (title, start))
    ctx.conn.commit()
    return f"booked: {title}, {start}"


def _schedule_task(args: dict, ctx: Ctx) -> str:
    kind = str(args.get("kind", "")).strip().lower()
    spec = str(args.get("spec", "")).strip()
    message = str(args.get("message", "")).strip()
    tz = str(args.get("tz", "UTC") or "UTC").strip()
    active_start = args.get("active_start")
    active_end = args.get("active_end")
    if not kind or not spec or not message:
        return "error: kind, spec, and message are required"
    try:
        timers.add(ctx.conn, session_id=ctx.session_id, reply_to=ctx.reply_to, kind=kind,
                   spec=spec, message=message, now=ctx.now,
                   tz=tz, active_start=active_start, active_end=active_end)
    except Exception as exc:  # noqa: BLE001
        return f"error: invalid timer: {exc}"
    return f"timer set: {kind} {spec}"


def _send_message(args: dict, ctx: Ctx) -> str:
    to = str(args["to"]).strip()
    address = "owner" if to.lower() in ("owner", "me") else to
    target = ctx.owner_addresses[0] if address == "owner" else address
    parsed = outbox.parse_address(target)
    if parsed is None:
        return f"error: {to!r} is not an address"
    key = hashlib.sha256(f"{ctx.run_id}|{target}|{args['body']}".encode()).hexdigest()[:24]
    outbox.insert(ctx.conn, run_id=ctx.run_id, channel=parsed[0], target=parsed[1],
                  body=str(args["body"]), idempotency_key=f"send:{key}", now=ctx.now)
    return f"queued for {target}"


def default_tools() -> ToolRegistry:
    registry = ToolRegistry()
    obj: Callable[[dict, list[str]], dict[str, Any]] = lambda props, req: {  # noqa: E731
        "type": "object", "properties": props, "required": req}
    s = {"type": "string"}
    registry.add(Tool("remember_preference",
                      "Save or manage curated memory. action: add|replace|remove (default add). target: user|memory (default user).",
                      obj({"entry": s, "action": s, "target": s, "old_text": s}, ["entry"]), _remember_preference))
    registry.add(Tool("recall", "Search long-term memory.", obj({"query": s}, ["query"]), _recall))
    registry.add(Tool("book_meeting", "Put a meeting on the calendar.",
                      obj({"with": s, "day": s, "time": s}, ["with", "day", "time"]), _book_meeting))
    registry.add(Tool("schedule_task", "Run a message at a time, on repeat if asked.",
                      obj({"kind": s, "spec": s, "message": s}, ["kind", "spec", "message"]),
                      _schedule_task))
    registry.add(Tool("send_message", "Send a message to a person at an address.",
                      obj({"to": s, "body": s}, ["to", "body"]), _send_message))
    return registry


# ---- the guard rules ---------------------------------------------------------

def _always(_args: dict, _ctx: object) -> Decision:
    return Decision(ALLOW)


def _send_rule(args: dict, ctx: object) -> Decision:
    assert isinstance(ctx, Ctx)
    to = str(args.get("to", "")).strip()
    if to.lower() in ("owner", "me") or to in ctx.owner_addresses:
        return Decision(ALLOW, "a message to the owner is a reply")
    if outbox.parse_address(to) is None:
        return Decision(DENY, f"{to!r} is not an address (telegram:<id>, slack:<channel>, github:<repo>#<n>)")
    return Decision(HOLD, "a message to anyone else is a write to a third party")


def _owner_only(_args: dict, ctx: object) -> Decision:
    assert isinstance(ctx, Ctx)
    if ctx.owner_addresses and ctx.session_id in ctx.owner_addresses:
        return Decision(ALLOW)
    return Decision(DENY, "only the owner session may modify curated memory")


def default_rules() -> dict[str, Callable[[dict, object], Decision]]:
    return {"remember_preference": _owner_only, "recall": _always, "book_meeting": _always,
            "schedule_task": _always, "send_message": _send_rule}
