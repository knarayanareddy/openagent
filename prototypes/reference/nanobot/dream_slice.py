"""nanobot's memory loop, distilled: a journal, a cursor, a Dream pass, and git as the audit trail.

Upstream: github.com/HKUDS/nanobot (MIT)
  nanobot/agent/memory.py        MemoryStore: history journal, cursors, dream_lock
  nanobot/agent/dream.py         run_dream(): read past the cursor, run an agent, commit the diff
  nanobot/utils/gitstore.py      GitStore.auto_commit
  nanobot/agent/autocompact.py   idle sessions are compacted after a TTL
  nanobot/cron/types.py          CronSchedule.kind = "at" | "every" | "cron"

What is worth copying:
  * The cursor only advances when the Dream pass COMPLETED. A failed night is retried, never skipped.
  * Memory lives in files under git, so "what did it learn last night" is a diff and a bad night is a revert.
  * One asyncio.Lock serialises writers, so a manual /dream and a scheduled one cannot interleave.

Run:  python dream_slice.py
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


# ---- schedules (nanobot/cron/types.py) ------------------------------------------------------

@dataclass
class CronSchedule:
    kind: str                     # "at" | "every" | "cron"
    at: datetime | None = None
    every: timedelta | None = None
    expr: str | None = None       # "M H * * *" only; use croniter for the full grammar

    def next_after(self, now: datetime) -> datetime | None:
        if self.kind == "at":
            return self.at if self.at and self.at > now else None
        if self.kind == "every" and self.every:
            return now + self.every
        if self.kind == "cron" and self.expr:
            minute, hour = (int(p) for p in self.expr.split()[:2])
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return candidate if candidate > now else candidate + timedelta(days=1)
        return None


# ---- the memory store (nanobot/agent/memory.py) ----------------------------------------------

class MemoryStore:
    def __init__(self, workspace: Path) -> None:
        self.dir = workspace / "memory"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.journal = self.dir / "history.jsonl"
        self.cursor_file = self.dir / ".dream_cursor"
        self.memory_md = self.dir / "MEMORY.md"
        self.dream_lock = asyncio.Lock()
        self._git("init", "-q")
        # Audit the memory CONTENT, not the bookkeeping. A failed night then changes nothing and commits nothing.
        (self.dir / ".gitignore").write_text("history.jsonl\n.dream_cursor\n")
        self.auto_commit("init")

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-c", "user.name=nanobot", "-c", "user.email=n@localhost",
                               "-c", "commit.gpgsign=false", *args], cwd=self.dir, capture_output=True, text=True)

    def append_history(self, text: str) -> int:
        cursor = self.latest_cursor() + 1
        with self.journal.open("a") as f:
            f.write(json.dumps({"cursor": cursor, "content": text}) + "\n")
        return cursor

    def entries(self) -> list[dict]:
        return [json.loads(l) for l in self.journal.read_text().splitlines()] if self.journal.exists() else []

    def latest_cursor(self) -> int:
        e = self.entries()
        return e[-1]["cursor"] if e else 0

    def dream_cursor(self) -> int:
        return int(self.cursor_file.read_text()) if self.cursor_file.exists() else 0

    def set_dream_cursor(self, value: int) -> None:
        self.cursor_file.write_text(str(value))

    def unprocessed(self) -> list[dict]:
        return [e for e in self.entries() if e["cursor"] > self.dream_cursor()]

    def auto_commit(self, message: str) -> str | None:
        self._git("add", "-A")
        if self._git("diff", "--cached", "--quiet").returncode == 0:
            return None
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "--short", "HEAD").stdout.strip()


# ---- dream (nanobot/agent/dream.py) ----------------------------------------------------------

@dataclass
class DreamResult:
    had_input: bool = False
    changed: bool = False
    error: str | None = None
    commit_sha: str | None = None


async def fake_agent(prompt: str, fail: bool) -> str:
    """Stands in for loop.process_direct(prompt, tools=store.build_dream_tools())."""
    if fail:
        raise RuntimeError("provider overloaded")
    return "\n".join(f"- {l.removeprefix('user: ')}" for l in prompt.splitlines() if l.startswith("user: "))


async def run_dream(store: MemoryStore, *, fail: bool = False) -> DreamResult:
    result = DreamResult()
    async with store.dream_lock:                                   # writers are serialised
        pending = store.unprocessed()
        if not pending:
            return result
        result.had_input = True
        try:
            notes = await fake_agent("\n".join(e["content"] for e in pending), fail)
            existing = store.memory_md.read_text() if store.memory_md.exists() else ""
            store.memory_md.write_text(existing + notes + "\n")
            store.set_dream_cursor(pending[-1]["cursor"])           # ONLY after the pass completed
        except Exception as exc:                                    # noqa: BLE001
            result.error = str(exc)                                 # cursor untouched: retried next time
        sha = store.auto_commit(f"dream: {len(pending)} journal entries")
        result.changed, result.commit_sha = sha is not None, sha
    return result


async def main() -> None:
    store = MemoryStore(Path(tempfile.mkdtemp()))
    now = datetime(2026, 3, 2, 22, 0)
    print("schedules:", {s.kind: str(s.next_after(now)) for s in (
        CronSchedule("at", at=now + timedelta(hours=1)), CronSchedule("every", every=timedelta(minutes=30)),
        CronSchedule("cron", expr="0 3 * * *"))})
    for line in ("user: I moved to Lisbon", "user: my sister is called Ana"):
        store.append_history(line)
    print("night 1 (provider down):", await run_dream(store, fail=True),
          "| cursor:", store.dream_cursor(), "| unprocessed:", len(store.unprocessed()))
    print("night 2 (retried)      :", await run_dream(store),
          "| cursor:", store.dream_cursor(), "| unprocessed:", len(store.unprocessed()))
    print("night 3 (nothing new)  :", await run_dream(store))
    print("git log:", store._git("log", "--oneline").stdout.strip())
    print("MEMORY.md:", store.memory_md.read_text().strip().replace("\n", " | "))


if __name__ == "__main__":
    asyncio.run(main())
