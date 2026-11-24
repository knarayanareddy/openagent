"""A trace is the observer pattern from waku/loop/agent.py, kept in one list.

Anything in the system calls `observer(kind, event)`. The Trace turns each call
into a row with a lane, so the same data feeds a terminal printout, a JSONL
file, or the preview app's timeline. No module imports a logger it must carry.
"""

from __future__ import annotations

from typing import Any

LANES = {
    "alwayson": {"inbox", "dedupe", "claim", "recover", "timer", "defer", "outbox", "sent",
                 "retry", "dead", "approval", "breaker", "command"},
    "loop": {"llm", "tool", "limit", "reply"},
    "guard": {"guard"},
    "memory": {"gate", "recall", "snapshot", "curated", "dream", "dropped", "audit"},
}
_LANE_OF = {kind: lane for lane, kinds in LANES.items() for kind in kinds}


class Trace:
    def __init__(self) -> None:
        self.scenes: list[dict[str, Any]] = []

    def scene(self, scene_id: str, title: str, blurb: str) -> None:
        self.scenes.append({"id": scene_id, "title": title, "blurb": blurb, "events": [],
                            "state": None})

    def __call__(self, kind: str, event: dict[str, Any] | None = None) -> None:
        if not self.scenes:
            self.scene("start", "start", "")
        event = dict(event or {})
        title = str(event.pop("title", kind))
        self.scenes[-1]["events"].append(
            {"kind": kind, "lane": _LANE_OF.get(kind, "loop"), "title": title, "detail": event})

    def attach_state(self, state: dict[str, Any]) -> None:
        self.scenes[-1]["state"] = state


def silent(kind: str, event: dict[str, Any] | None = None) -> None:
    """The observer when nobody is watching."""
