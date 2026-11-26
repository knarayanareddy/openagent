"""Memory you can diff, and undo.

Two ideas joined:

  nanobot  agent/dream.py + utils/gitstore.py. Every Dream pass that changes
           memory ends in a git commit of the memory directory, so "what did the
           assistant decide to remember last night?" is `git log -p`, and a bad
           night is `git revert`.
  memU     memory stored as a readable wiki. SQLite is fast but not diffable, so
           the facts are mirrored into wiki/facts.md. That file is what makes a
           change in the database show up in git.

If `git` is not installed every call is a quiet no-op and the agent still works.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from openagent.memory.semantic import SemanticMemory

_GIT = ["git", "-c", "user.name=openagent", "-c", "user.email=openagent@localhost",
        "-c", "commit.gpgsign=false"]


class MemoryAudit:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.enabled = self._git("init", "-q") is not None

    def _git(self, *args: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run([*_GIT, *args], cwd=self.root, capture_output=True, text=True)
        except FileNotFoundError:
            return None

    def commit(self, message: str) -> str | None:
        """Commit whatever changed. Returns the short sha, or None when nothing did."""
        if not self.enabled or self._git("add", "-A") is None:
            return None
        staged = self._git("diff", "--cached", "--quiet")
        if staged is None or staged.returncode == 0:
            return None
        self._git("commit", "-q", "-m", message)
        head = self._git("rev-parse", "--short", "HEAD")
        return head.stdout.strip() if head and head.returncode == 0 else None

    def history(self, n: int = 10) -> list[tuple[str, str]]:
        log = self._git("log", f"-{n}", "--pretty=%h\t%s")
        if not log or log.returncode != 0:
            return []
        return [tuple(line.split("\t", 1)) for line in log.stdout.splitlines()]  # type: ignore[misc]

    def revert(self, sha: str, semantic: SemanticMemory | None = None) -> bool:
        sha = str(sha or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
            return False
        done = self._git("revert", "--no-edit", sha)
        ok = bool(done and done.returncode == 0)
        if not ok:
            # Leave repo in a clean state if revert conflicted.
            self._git("revert", "--abort")
            self._git("merge", "--abort")
            return False
        if semantic is not None:
            semantic.sync_from_wiki(self.root / "wiki" / "facts.md")
        return True


def export_wiki(semantic: SemanticMemory, root: Path) -> Path:
    """Mirror facts and episodes into markdown wiki files and JSON snapshot per run."""
    by_subject: dict[str, list[str]] = {}
    facts = semantic.all_facts()
    for fact in facts:
        by_subject.setdefault(fact["subject"], []).append(fact["content"])
    lines = ["# What I know", ""]
    for subject in sorted(by_subject, key=str.lower):
        lines += [f"## {subject}", *[f"- {c}" for c in by_subject[subject]], ""]
    wiki = root / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    path = wiki / "facts.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    episodes = semantic.all_episodes()
    ep_lines = ["# Episodes", ""]
    for ep in episodes:
        ep_lines.append(f"- ({ep['happened_at']}) {ep['summary']}")
    (wiki / "episodes.md").write_text("\n".join(ep_lines) + "\n", encoding="utf-8")
    snapshot = {"version": 1, "facts": facts, "episodes": episodes}
    (wiki / "state.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
