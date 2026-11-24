"""Semantic and episodic memory on SQLite FTS5.

Descends from waku/memory/semantic/store.py and episodic/store.py.

Hermes' insight, kept by Waku: for one person's facts, ranked keyword search
(BM25) is fast, fully local, and you can read the whole index with sqlite3.
Want vectors? Swap this class for a pgvector store with the same three methods.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from openagent.memory.curated import scan as scan_threat


def fts_query(text: str) -> str:
    """Turn free text into `word OR word`. Two lessons from Waku's version:

    * `[^\\W_]` is the set FTS5's unicode61 tokenizer keeps, so non-ASCII names
      such as Müller or Сергей still match. An ASCII-only class truncates them.
    * Everything is lowercased because FTS5 reads AND/OR/NOT only in UPPERCASE,
      so a user's "Alex and Bob" never parses as a boolean expression.
    """
    words = re.findall(r"[^\W_]{2,}", text.lower())
    return " OR ".join(dict.fromkeys(words))


class SemanticMemory:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add_fact(self, subject: str, content: str, source: str = "user") -> int:
        if scan_threat(f"{subject} {content}") is not None:
            return -1
        cur = self.conn.execute("INSERT INTO facts (subject, content, source) VALUES (?, ?, ?)",
                                (subject, content, source))
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def has_fact(self, subject: str, content: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM facts WHERE lower(subject) = lower(?) AND lower(content) = lower(?)",
            (subject, content)).fetchone()
        return row is not None

    def search(self, query: str, k: int = 5) -> list[dict]:
        match = fts_query(query)
        if not match:
            # An empty query must return nothing. Reading it as "give me the
            # recent ones" hands the model someone else's memory as if relevant.
            return []
        rows = self.conn.execute(
            "SELECT f.subject, f.content FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid "
            "WHERE facts_fts MATCH ? ORDER BY bm25(facts_fts) LIMIT ?", (match, k)).fetchall()
        return [dict(r) for r in rows]

    def all_facts(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT subject, content, source FROM facts ORDER BY id")]

    def add_episode(self, happened_at: str, summary: str) -> None:
        self.conn.execute("INSERT INTO episodes (happened_at, summary) VALUES (?, ?)",
                          (happened_at, summary))
        self.conn.commit()

    def search_episodes(self, query: str, k: int = 3) -> list[dict]:
        match = fts_query(query)
        if not match:
            return []
        rows = self.conn.execute(
            "SELECT e.happened_at, e.summary FROM episodes_fts JOIN episodes e "
            "ON e.id = episodes_fts.rowid WHERE episodes_fts MATCH ? "
            "ORDER BY bm25(episodes_fts) LIMIT ?", (match, k)).fetchall()
        return [dict(r) for r in rows]

    def recall_text(self, query: str) -> str:
        facts = self.search(query)
        episodes = self.search_episodes(query)
        lines = [f"- {f['content']}" for f in facts]
        lines += [f"- ({e['happened_at']}) {e['summary']}" for e in episodes]
        return "\n".join(lines)


    def replace_all_facts(self, facts: list[dict]) -> None:
        """Replace all facts (used by audit revert sync)."""
        self.conn.execute("DELETE FROM facts")
        for f in facts:
            subject = str(f.get("subject", "")).strip()
            content = str(f.get("content", "")).strip()
            source = str(f.get("source", "wiki"))
            if subject and content:
                self.conn.execute("INSERT INTO facts (subject, content, source) VALUES (?, ?, ?)",
                                  (subject, content, source))
        self.conn.commit()

    def sync_from_wiki(self, wiki_path: str | Path) -> int:
        """Rebuild facts table from a wiki/facts.md export. Returns number of facts loaded."""
        path = Path(wiki_path)
        if not path.exists():
            self.replace_all_facts([])
            return 0
        subject = ""
        facts: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                subject = line[3:].strip()
            elif line.startswith("- ") and subject:
                facts.append({"subject": subject, "content": line[2:].strip(), "source": "wiki"})
        self.replace_all_facts(facts)
        return len(facts)
