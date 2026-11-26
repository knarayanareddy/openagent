"""Playbooks: shared recipes for repeatable jobs, adopted per person.

Pattern from Persistent-Agent (skills/playbooks/SKILL.md + the three built-in playbooks):

    shared file  playbooks/<name>.md   -> the recipe. Improve it once; everyone gets the change.
    personal     playbook_adoptions    -> one person's settings + the timer that runs it.

The timer message carries only `[playbook:<name>]`. The recipe text is injected when the run
starts (see install.py), so editing the file changes tomorrow's run and nobody's settings.
Only name + description sit in every prompt; the body loads on demand (progressive disclosure).
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openagent.alwayson import timers
from openagent.db import stamp
from openagent.persistent import attention

BUILTIN_DIR = Path(__file__).parent / "builtin_playbooks"
_REF = re.compile(r"\[playbook:([a-z0-9-]+)\]")


@dataclass(frozen=True)
class Playbook:
    name: str
    description: str
    schedule: str          # 5-field cron, the default for adopters
    body: str


def parse(path: Path) -> Playbook:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path.name}: playbooks start with a --- frontmatter block")
    _, front, body = raw.split("---", 2)
    meta = dict(line.split(":", 1) for line in front.strip().splitlines() if ":" in line)
    meta = {k.strip(): v.strip().strip('"') for k, v in meta.items()}
    if not meta.get("description", "").startswith("Playbook:"):
        raise ValueError(f"{path.name}: description must start with 'Playbook:'")
    return Playbook(meta["name"], meta["description"], meta.get("schedule", "0 8 * * 1-5"), body.strip())


def load(dirs: list[Path]) -> dict[str, Playbook]:
    found: dict[str, Playbook] = {}
    for directory in dirs:                         # later dirs override earlier ones
        if directory.is_dir():
            for path in sorted(directory.glob("*.md")):
                pb = parse(path)
                found[pb.name] = pb
    return found


def reference_in(text: str) -> str | None:
    m = _REF.search(text)
    return m.group(1) if m else None


def adopt(conn: sqlite3.Connection, available: dict[str, Playbook], session_id: str, reply_to: dict,
          name: str, now: datetime, *, tz: str = "UTC", settings: dict | None = None) -> int:
    """Idempotent: adopting twice updates the settings and keeps the single timer."""
    if name not in available:
        raise KeyError(f"no playbook {name!r}; have {', '.join(sorted(available)) or 'none'}")
    pb = available[name]
    row = conn.execute("SELECT timer_id FROM playbook_adoptions WHERE session_id = ? AND name = ?",
                       (session_id, name)).fetchone()
    blob = json.dumps(settings or {}, sort_keys=True)
    if row is not None:
        conn.execute("UPDATE playbook_adoptions SET settings = ? WHERE session_id = ? AND name = ?",
                     (blob, session_id, name))
        conn.commit()
        return int(row["timer_id"])
    hours = attention.working_hours(conn, session_id)
    timer_id = timers.add(conn, session_id=session_id, reply_to=reply_to, kind="cron", spec=pb.schedule,
                          message=f"[playbook:{name}] Run the {name} playbook.", now=now,
                          tz=hours.tz if hours else tz,
                          active_start=hours.start if hours else None, active_end=hours.end if hours else None)
    conn.execute("INSERT INTO playbook_adoptions (session_id, name, settings, timer_id, adopted_at) "
                 "VALUES (?, ?, ?, ?, ?)", (session_id, name, blob, timer_id, stamp(now)))
    conn.commit()
    return timer_id


def settings_for(conn: sqlite3.Connection, session_id: str, name: str) -> dict:
    row = conn.execute("SELECT settings FROM playbook_adoptions WHERE session_id = ? AND name = ?",
                       (session_id, name)).fetchone()
    return json.loads(row["settings"]) if row else {}


def catalog(available: dict[str, Playbook]) -> str:
    if not available:
        return "Playbooks: none installed."
    return "Playbooks you can run or adopt (call playbook_read for the recipe):\n" + "\n".join(
        f"- {p.name}: {p.description}" for p in available.values())
