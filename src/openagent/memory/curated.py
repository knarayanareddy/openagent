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

Entries are separated by "\\n§\\n". The threat list below is an expanded, original
set informed by common prompt-injection and exfil patterns; upstream provenance includes
Hermes' `tools/threat_patterns.py` (studied for categories, not copied).
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
    # Instruction override / role reassignment
    (re.compile(r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier)\s+(?:instructions|rules|messages|prompts?)", re.I),
     "it tries to override earlier instructions"),
    (re.compile(r"\b(?:disregard|forget)\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+(?:instructions|rules|context)\b", re.I),
     "it tries to override earlier instructions"),
    (re.compile(r"\b(?:you are now|act as if you (?:have no|are)|pretend to be|from now on you are)\b", re.I),
     "it tries to reassign the assistant's role"),
    (re.compile(r"\b(?:developer mode|jailbreak|DAN mode|do anything now)\b", re.I),
     "it contains a jailbreak-style role override"),
    (re.compile(r"\b(?:system prompt|hidden prompt|initial instructions?)\b.{0,40}\b(?:reveal|show|print|dump|repeat)\b", re.I),
     "it tries to exfiltrate system instructions"),
    (re.compile(r"\b(?:reveal|show|print|dump|repeat)\b.{0,40}\b(?:system prompt|hidden prompt|initial instructions?)\b", re.I),
     "it tries to exfiltrate system instructions"),

    # Credential / secret / sensitive paths
    (re.compile(r"(?:\.ssh/|id_rsa|id_ed25519|\.gnupg/|/etc/passwd|/etc/shadow|\.env\b|credentials\.json|\.aws/credentials|\.netrc\b)", re.I),
     "it names a credential or sensitive system file"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "it contains what looks like an AWS access key"),
    (re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghu|ghs|ghr|xox[baprs]-|AIza)[-_A-Za-z0-9]{16,}\b"),
     "it contains what looks like an API key or token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
     "it contains what looks like a private key"),

    # Command execution / exfiltration
    (re.compile(r"curl[^\n|]*\|\s*(?:ba)?sh", re.I), "it pipes a download into a shell"),
    (re.compile(r"\b(?:wget|curl)\b[^\n]{0,120}\b(?:\||;|&&)\b[^\n]{0,60}\b(?:sh|bash|zsh|python|perl|node)\b", re.I),
     "it chains a download to command execution"),
    (re.compile(r"\b(?:rm\s+-rf\s+/|mkfs\.|dd\s+if=|:\(\)\s*\{\s*:\|:\s*&\s*\};:)", re.I),
     "it contains a destructive shell command"),
    (re.compile(r"\b(?:powershell|cmd\.exe)\b[^\n]{0,80}\b(?:-enc|-encodedcommand|iex|invoke-expression)\b", re.I),
     "it contains an encoded or obfuscated shell command"),

    # Exfil / suspicious URLs and markup
    (re.compile(r"\b(?:send|post|upload|exfiltrate|leak)\b.{0,60}\b(?:https?://|ftp://)\S+", re.I),
     "it instructs data exfiltration to a URL"),
    (re.compile(r"https?://\S*(?:webhook\.site|requestbin|ngrok(?:-free)?\.app|pipedream\.net|interact\.sh)\S*", re.I),
     "it contains a known exfiltration/webhook endpoint"),
    (re.compile(r"<\s*script\b", re.I), "it contains script markup"),
    (re.compile(r"\b(?:javascript:|data:text/html)", re.I), "it contains an active URI payload"),

    # Obfuscation / hidden characters
    (re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]"), "it hides invisible characters"),
    (re.compile(r"(?:&#x?[0-9a-f]+;){8,}", re.I), "it contains suspicious HTML entity obfuscation"),
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
