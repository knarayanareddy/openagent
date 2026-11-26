"""PersistentScriptedLLM: the offline model for the goal / heartbeat / playbook scenarios.

Same philosophy as openagent.testing.ScriptedLLM: fake the model, assert on the harness.
It reads the system prompt the harness built (goals digest, current time, playbook body)
and the tool results the harness returned, and answers by rule. If the harness did not
inject the right context, this model has nothing to act on, which is exactly the point.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from openagent.llm import Response
from openagent.testing import ScriptedLLM, _text, call, say

QUIET = "[quiet]"


def _now(system: str) -> datetime:
    m = re.search(r"Current time \(UTC\): (\S+)", system)
    return datetime.fromisoformat(m[1]) if m else datetime(2026, 3, 2, 9, 0).astimezone()


def _run(messages: list[dict]) -> tuple[list[str], list[str]]:
    """Tool names called and results returned since the last plain-text user message."""
    start = max((i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str)),
                default=0)
    names, results = [], []
    for m in messages[start + 1:]:
        if m["role"] == "assistant":
            names += [b["name"] for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"]
        elif m["role"] == "user":
            results.append(_text(m["content"]))
    return names, results


class PersistentScriptedLLM(ScriptedLLM):
    def __call__(self, system: str, messages: list[dict], tools: list[dict], tool_choice: str | None = None,
                 **kw: Any) -> Response:
        last = messages[-1]
        text = _text(last["content"])
        if "You are a retrieval gate" in text or system.startswith("You distill"):
            return super().__call__(system, messages, tools, tool_choice, **kw)
        initial = next((m["content"] for m in reversed(messages)
                        if m["role"] == "user" and isinstance(m["content"], str)), "")
        names, results = _run(messages)
        self.calls.append({"system": system, "last": text, "tool_choice": tool_choice})
        now = _now(system)

        # 1. the owner states an outcome that needs follow-through
        if m := re.match(r"get a catch-up with (\w+) .*?(?:free slot|scheduled)", initial, re.I):
            if not names:
                return call("goal_create", outcome=f"Get a catch-up with {m[1]} scheduled",
                            done_when="a calendar event with them exists",
                            next_step="check their availability with the calendar tool",
                            next_check=(now + timedelta(hours=4)).isoformat())
            return say("On it. I'm tracking this as a goal and will only message you when there is news.")

        # 2. the hourly heartbeat, reached only when the harness decided a goal is due
        if initial.strip().startswith("[timer] [heartbeat]"):
            due = re.search(r"id=(\d+) \[active\] Get a catch-up with (\w+) scheduled.*DUE NOW", system)
            if not due:
                return say(QUIET)
            goal_id, who = int(due[1]), due[2]
            if not names:
                return call("mcp_search", query="calendar availability free")
            if names == ["mcp_search"]:
                tool = results[-1].split(" ", 1)[0]
                return call("mcp_call", tool=tool, arguments={"who": who})
            if names == ["mcp_search", "mcp_call"]:
                free = re.search(r"free: ([^\n]+)", results[-1])
                if not free:
                    return call("goal_update", goal_id=goal_id, current_state=f"{who} has no free slot yet",
                                next_step="check again tomorrow morning",
                                next_check=(now + timedelta(hours=18)).isoformat())
                return call("goal_update", goal_id=goal_id,
                            current_state=f"{who} is free {free[1].split(',')[0].strip()}; waiting for the owner's yes",
                            next_step="book it after the owner says yes",
                            next_check=(now + timedelta(hours=24)).isoformat())
            return say(QUIET if "no free slots" in results[-2] else
                       "Alex is free Thursday 14:00. Want me to book the catch-up? Reply yes.")

        # 3. the owner's yes to a proposal the heartbeat made
        waiting = re.search(r"id=(\d+) \[active\] Get a catch-up with (\w+) scheduled.*is free (\w+) (\d\d:\d\d); "
                            r"waiting for the owner's yes", system)
        if waiting and re.match(r"(yes|yep|go ahead)\b", initial, re.I):
            goal_id, who, day, hhmm = int(waiting[1]), waiting[2], waiting[3], waiting[4]
            if not names:
                return call("book_meeting", **{"with": who, "day": day, "time": hhmm})
            if names == ["book_meeting"]:
                return call("goal_update", goal_id=goal_id, status="completed",
                            evidence=f"calendar tool answered: {results[-1]}")
            return say(f"Booked: catch-up with {who}, {day} {hhmm}. Goal complete.")

        # 4. a playbook run
        if pb := re.search(r"\[playbook:([a-z-]+)\]", initial):
            if f"Playbook in progress: {pb[1]}" not in system:
                return say("(playbook body was not injected)")
            active = re.findall(r"- id=\d+ \[active\] (.*?) \|", system)
            return say("Morning brief: " + (f"{len(active)} goal(s) in flight: " + "; ".join(active) if active
                                             else "nothing needs you.")) if active else say(QUIET)

        # 5. someone asks about the owner in a shared channel
        if "not a private chat" in system and re.search(r"what does the owner|owner prefer", initial, re.I):
            return say("I can't share personal details here.")
        return super().__call__(system, messages, tools, tool_choice, **kw)
