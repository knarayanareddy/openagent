"""Dream: distil chats into durable memory, only sometimes, and leave a receipt.

The skeleton is nanobot's agent/dream.py. The guards are Waku's
waku/memory/consolidation.py. The routing into a bounded file is Hermes'.

  CURSOR  (nanobot)  Dream reads chat rows past `dream_cursor`. The cursor moves
          only when the model call succeeded, so a failed night is retried, never
          skipped.
  DUE     (Waku)     Not after every message. After N user turns, or when a timer
          fires `force=True`. Batching gives the summariser enough context.
  GUARDS  (Waku)     A proposed fact is dropped when it
            - is the assistant's own operating state (balances, 429s, tokens): stale within the hour
            - only restates memory the turn already read (every name, number and date is in `recalled`)
            - is already stored, in curated memory or as a fact
  ROUTE   (Hermes)   A durable fact tries the bounded USER.md first. If it is scanned
                     out or does not fit, it becomes a searchable fact instead.
  AUDIT   (nanobot + memU)  Facts are mirrored to wiki/facts.md and the memory
                     directory is committed, so the night's changes are one diff.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from openagent.db import kv_get, kv_set
from openagent.llm import LLM
from openagent.memory.audit import MemoryAudit, export_wiki
from openagent.memory.curated import CuratedMemory
from openagent.memory.semantic import SemanticMemory

DREAM_PROMPT = """\
You distill a personal assistant's recent conversation into long-term memory.

Extract only what the person said, never what the assistant replied. Skip chit-chat.
Never extract the assistant's own operating state: balances, credits, rate limits,
tool errors, token counts. Mark a fact "durable" when it is a stable preference or
trait of the person that belongs in their profile.

Reply with ONLY this JSON:
{{"facts": [{{"subject": "<who>", "content": "<one sentence>", "durable": false}}],
  "episode": "<one sentence>"}}

Exchanges:
{log}"""

_MONEYISH = re.compile(r"\$|\busd\b|\bcredits?\b|\bmicro\b|\baccount\b|\bwallet\b|\bapi\b", re.I)
_OPS_STATE = re.compile(
    r"\binsufficient\b|\b(?:out of|no|remaining|left in)\s+(?:\w+\s+)?credits?\b|"
    r"\d[\d,.]*\s*micro(?:-?usd)?\b|\b(?:http|status(?: code)?|error(?: code)?)\s*[45]\d\d\b|"
    r"\brate[- ]limit|\btoo many requests\b|\bquota (?:exceeded|hit|reached)\b|"
    r"\b\d[\d,.]*\s*k?\s*(?:input |output |prompt |completion )?tokens\b|"
    r"\b(?:timed out|returned an error|tool error)\b|\b(?:system prompt|context window|tool calls?)\b",
    re.I)


def is_ops_state(fact: dict) -> bool:
    """A fact about the assistant's own state, not about the person."""
    text = f"{fact.get('subject', '')} {fact.get('content', '')}"
    if re.search(r"\bbalance\b", text, re.I) and _MONEYISH.search(text):
        return True
    return _OPS_STATE.search(text) is not None


def _words(text: str) -> set[str]:
    # strip trailing sentence punctuation so "15:00." in a fact matches "15:00" in memory
    return {w.rstrip(".,:;-") for w in re.findall(r"[^\W_][\w$.:/-]*", text.lower())}


def restates(fact: dict, recalled: str) -> bool:
    """True when the fact only repeats memory the turn read: it has a number or date,
    and every capitalised or numeric word in it is already in `recalled`.

    A fact with no number is never dropped here, however familiar its names, so
    something new the user says is not lost."""
    content = str(fact.get("content", "")).replace("\u2019", "'")
    key = _words(" ".join(w for w in content.split() if any(c.isupper() or c.isdigit() for c in w)))
    has_number = any(w[0].isdigit() for w in key)
    return has_number and key <= _words(recalled)


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


@dataclass
class DreamResult:
    ran: bool = False
    kept: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    episode: str = ""
    commit: str | None = None
    error: str = ""


def chats_since_cursor(conn: sqlite3.Connection) -> tuple[list[sqlite3.Row], int]:
    cursor = int(kv_get(conn, "dream_cursor", "0"))
    rows = conn.execute("SELECT id, role, content FROM chat_log WHERE id > ? ORDER BY id",
                        (cursor,)).fetchall()
    return rows, cursor


def dream_due(conn: sqlite3.Connection, every_n: int) -> bool:
    rows, _ = chats_since_cursor(conn)
    return sum(1 for r in rows if r["role"] == "user") >= every_n


def run_dream(conn: sqlite3.Connection, llm: LLM, semantic: SemanticMemory,
              curated: CuratedMemory, audit: MemoryAudit, *, now: datetime,
              recalled: str = "", every_n: int = 4, force: bool = False,
              observer=lambda kind, ev=None: None) -> DreamResult:
    rows, _ = chats_since_cursor(conn)
    users = sum(1 for r in rows if r["role"] == "user")
    if not rows or (not force and users < every_n):
        return DreamResult()

    log = "\n".join(f"{r['role']}: {r['content']}" for r in rows)
    try:
        text = llm(DREAM_PROMPT.format(log=log), [{"role": "user", "content": "Distill."}], []).text
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except Exception as exc:                        # noqa: BLE001
        # The cursor stays where it was. The next pass reads the same rows again.
        observer("dream", {"title": "dream failed, cursor not moved", "error": str(exc)})
        return DreamResult(error=f"{type(exc).__name__}: {exc}")

    result = DreamResult(ran=True, episode=str(data.get("episode", "")))
    known = "\n".join([recalled, curated.snapshot()])
    for fact in data.get("facts", []):
        subject, content = str(fact.get("subject", "")), str(fact.get("content", ""))
        if not content:
            continue
        reason = None
        if is_ops_state(fact):
            reason = "assistant operating state"
        elif restates(fact, recalled):
            reason = "restates memory the turn already read"
        elif _norm(content) in _norm(known) or semantic.has_fact(subject, content):
            reason = "already stored"
        if reason:
            result.dropped.append({"content": content, "reason": reason})
            observer("dropped", {"title": f"dropped: {reason}", "content": content})
            continue
        where = "semantic"
        if fact.get("durable"):
            added = curated.add("user", content)
            if added.get("success"):
                where = "USER.md"
            else:
                observer("dropped", {"title": "curated refused, kept as a fact instead",
                                     "content": content, "why": added.get("error", "")})
        if where == "semantic":
            semantic.add_fact(subject, content, source="dream")
        result.kept.append({"content": content, "where": where})

    if result.episode:
        semantic.add_episode(now.date().isoformat(), result.episode)
    kv_set(conn, "dream_cursor", str(rows[-1]["id"]))        # only after success
    export_wiki(semantic, curated.root)
    result.commit = audit.commit(f"dream {now.date().isoformat()}: +{len(result.kept)} kept, "
                                 f"{len(result.dropped)} dropped")
    observer("dream", {"title": f"dream kept {len(result.kept)}, dropped {len(result.dropped)}",
                       "commit": result.commit, "cursor": rows[-1]["id"]})
    return result
