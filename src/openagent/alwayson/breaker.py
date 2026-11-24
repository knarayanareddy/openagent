"""Startup circuit breaker: a crash-looping agent slows itself down.

Port of NanoClaw's src/circuit-breaker.ts. If the process starts again soon after
a start that never shut down cleanly, it waits before doing anything, and waits
longer each time. A clean shutdown, or an hour of quiet, resets it.

  crashes:  1   2   3   4    5    6+
  delay s:  0   0  10  30  120  300 -> 900 (capped)

This matters most for always-on agents: a bad message that kills the worker would
otherwise be reclaimed by `events.recover()` and kill it again, as fast as the OS
can restart it, hammering the model provider each time.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from openagent.db import parse_stamp, stamp

RESET_WINDOW_S = 60 * 60
BACKOFF_SCHEDULE_S = (0, 0, 10, 30, 120, 300, 900)


def delay_for(attempt: int) -> int:
    return BACKOFF_SCHEDULE_S[min(attempt - 1, len(BACKOFF_SCHEDULE_S) - 1)]


def enforce_startup_backoff(path: Path, now: datetime,
                            sleep: Callable[[float], None] = time.sleep) -> tuple[int, int]:
    """Call once at startup. Returns (attempt, seconds waited)."""
    previous = None
    try:
        previous = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        pass
    if previous and (now - parse_stamp(previous["timestamp"])).total_seconds() < RESET_WINDOW_S:
        attempt = int(previous["attempt"]) + 1
    else:
        attempt = 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"attempt": attempt, "timestamp": stamp(now)}))
    delay = delay_for(attempt)
    if delay > 0:
        sleep(delay)
    return attempt, delay


def reset(path: Path) -> None:
    """Call on a clean shutdown."""
    path.unlink(missing_ok=True)
