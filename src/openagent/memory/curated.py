"""Curated memory: two small, bounded markdown files the agent edits itself.

Descends from Hermes' tools/memory_tool.py and tools/memory_tool_store.py.

  MEMORY.md  the agent's own notes about your environment and conventions
  USER.md    who you are

Three ideas, all from Hermes:

  1. BOUNDED. A character budget per file (2,200 and 1,375 there, the same
     defaults here). A full file refuses the write and says what to do, so the
     agent must merge or drop an entry. Small memory forces prioritisation.
  2. SCANNED. Memory is injected into the system prompt, so a poisoned entry
     would persist across sessions. Every write is scanned first.
  3. FROZEN. The prompt gets a snapshot taken at session start. Writes mid-session
     reach disk but never change the prompt, so the provider's prefix cache holds.

Entries are separated by "\\n§\\n". The threat list below is a starter set; the
upstream list lives in Hermes' tools/threat_patterns.py.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

ENTRY_DELIMITER = "\n§\n"
DEFAULT_LIMITS = {"memory": 2200, "user": 1375}
FILES = {"memory": "MEMORY.md", "user": "USER.md"}
HEADERS = {"memory": "MEMORY (your personal notes)", "user": "USER PROFILE (who the user is)"}

_THREATS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+(?:instructions|rules)", re.I),
     "it tries to override earlier instructions"),
    (re.compile(r"\b(?:you are now|act as if you have no)\b", re.I), "it tries to reassign the assistant's role"),
    (re.compile(r"(?:\.ssh/|id_rsa|/etc/passwd|\.env\b|credentials\.json)", re.I),
     "it names a credential file"),
    (re.compile(r"curl[^\n|]*\|\s*(?:ba)?sh", re.I), "it pipes a download into a shell"),
    (re.compile(r"\b(?:sk|pk|ghp|xox[bp])[-_][A-Za-z0-9_-]{16,}"), "it contains what looks like an API key"),
    (re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]"), "it hides invisible characters"),
]


def scan(content: str) -> str | None:
    """Why this text may not enter memory, or None when it is clean."""
    for pattern, reason in _THREATS:
        if pattern.search(content):
            return reason
    return None


class CuratedMemory:
    def __init__(self, root: Path, limits: dict[str, int] | None = None) -> None:
        self.root = root
        self.limits = {**DEFAULT_LIMITS, **(limits or {})}
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- reading -----------------------------------------------------------
    def _path(self, target: str) -> Path:
        if target not in FILES:
            raise ValueError(f"target must be 'memory' or 'user', not {target!r}")
        return self.root / FILES[target]

    def entries(self, target: str) -> list[str]:
        path = self._path(target)
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8").strip()
        return [e.strip() for e in raw.split(ENTRY_DELIMITER) if e.strip()]

    def usage(self, target: str) -> str:
        used = len(ENTRY_DELIMITER.join(self.entries(target)))
        return f"{used:,}/{self.limits[target]:,}"

    def snapshot(self) -> str:
        """The block that goes into the system prompt. Take it once per session."""
        blocks = []
        for target in ("memory", "user"):
            entries = self.entries(target)
            if entries:
                body = "\n".join(f"- {e}" for e in entries)
                blocks.append(f"{HEADERS[target]} [{self.usage(target)}]\n{body}")
        return "\n\n".join(blocks)

    # ---- writing -----------------------------------------------------------
    def _write(self, target: str, entries: list[str]) -> None:
        path = self._path(target)
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(ENTRY_DELIMITER.join(entries) + "\n")
        os.replace(tmp, path)          # atomic: a crash leaves the old file or the new one

    def _fits(self, target: str, entries: list[str]) -> bool:
        return len(ENTRY_DELIMITER.join(entries)) <= self.limits[target]

    def add(self, target: str, content: str) -> dict:
        content = " ".join(content.split())
        if not content:
            return {"success": False, "error": "nothing to remember"}
        if (reason := scan(content)) is not None:
            return {"success": False, "refused": True,
                    "error": f"Refused: {reason}. Memory is read into every future prompt."}
        entries = self.entries(target)
        if content in entries:
            return {"success": True, "note": "already stored", "usage": self.usage(target)}
        if not self._fits(target, [*entries, content]):
            return {"success": False, "full": True,
                    "error": (f"{target} memory is full ({self.usage(target)}). Replace or remove "
                              "an entry first, or merge two into one."),
                    "entries": entries}
        self._write(target, [*entries, content])
        return {"success": True, "usage": self.usage(target)}

    def replace(self, target: str, old_text: str, content: str) -> dict:
        content = " ".join(content.split())
        if (reason := scan(content)) is not None:
            return {"success": False, "refused": True, "error": f"Refused: {reason}."}
        entries = self.entries(target)
        hits = [i for i, e in enumerate(entries) if old_text in e]
        if len(hits) != 1:
            return {"success": False, "error": f"{old_text!r} matched {len(hits)} entries; need exactly 1"}
        updated = [*entries[:hits[0]], content, *entries[hits[0] + 1:]]
        if not self._fits(target, updated):
            return {"success": False, "full": True, "error": "the replacement does not fit"}
        self._write(target, updated)
        return {"success": True, "usage": self.usage(target)}

    def remove(self, target: str, old_text: str) -> dict:
        entries = self.entries(target)
        kept = [e for e in entries if old_text not in e]
        if len(kept) == len(entries):
            return {"success": False, "error": f"no entry contains {old_text!r}"}
        self._write(target, kept)
        return {"success": True, "usage": self.usage(target)}
