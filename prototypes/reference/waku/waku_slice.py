"""waku-agent, distilled to one file you can read in ten minutes.

Upstream: github.com/ShenSeanChen/waku-agent (MIT)
  loop        waku/loop/agent.py               ~95 lines, two ways to stop
  gate        waku/memory/retrieval_gate.py    decide WHETHER to remember
  memory      waku/memory/semantic/store.py    SQLite FTS5, BM25, one file
  inbox       waku/alwayson/events.py          UNIQUE(source, external_id) makes redelivery a no-op
  outbox      waku/alwayson/outbox.py          idempotency_key UNIQUE, so a replayed run sends once
  approvals   waku/alwayson/approvals.py       a call that needs a yes is parked with a SHA-256

Run:  python waku_slice.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field

# ---- memory: facts in SQLite FTS5 --------------------------------------------------------

db = sqlite3.connect(":memory:")
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE facts (id INTEGER PRIMARY KEY, subject TEXT, content TEXT);
CREATE VIRTUAL TABLE facts_fts USING fts5(subject, content, content=facts, content_rowid=id);
CREATE TRIGGER facts_ai AFTER INSERT ON facts BEGIN
  INSERT INTO facts_fts(rowid, subject, content) VALUES (new.id, new.subject, new.content);
END;
CREATE TABLE events (id INTEGER PRIMARY KEY, source TEXT, external_id TEXT, text TEXT,
                     status TEXT DEFAULT 'pending', UNIQUE (source, external_id));
CREATE TABLE outbox (id INTEGER PRIMARY KEY, body TEXT, idempotency_key TEXT UNIQUE,
                     status TEXT DEFAULT 'pending');
CREATE TABLE parked (id INTEGER PRIMARY KEY, tool TEXT, args TEXT, sha256 TEXT);
""")


def remember(subject: str, content: str) -> None:
    db.execute("INSERT INTO facts (subject, content) VALUES (?, ?)", (subject, content))


def search(query: str, k: int = 3) -> list[str]:
    # [^\W_] is the set FTS5's unicode61 tokenizer keeps. Splitting on spaces instead hands FTS5 a
    # word like "catch-up", which it parses as a column filter and raises "no such column: up".
    words = list(dict.fromkeys(re.findall(r"[^\W_]{2,}", query.lower())))
    if not words:
        return []                                  # an empty query must return nothing
    rows = db.execute(
        "SELECT f.content FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid "
        "WHERE facts_fts MATCH ? ORDER BY bm25(facts_fts) LIMIT ?", (" OR ".join(words), k))
    return [r["content"] for r in rows]


# ---- the gate: does THIS message need memory? --------------------------------------------

def gate(message: str) -> tuple[bool, str]:
    """Waku asks a small model for {"retrieve": bool, "query": str}. A rule stands in here.
    Whatever answers, the contract is the same, and on any error it must fail OPEN."""
    needs = any(w in message.lower() for w in ("alex", "meeting", "remember", "book"))
    return needs, message


# ---- the loop: this is the whole trick ---------------------------------------------------

@dataclass
class Reply:
    text: str = ""
    calls: list[tuple[str, dict]] = field(default_factory=list)
    limit_reached: bool = False


def model(messages: list[dict], tools_allowed: bool = True) -> dict:
    """A scripted model. Real Waku speaks Anthropic's content blocks to any provider."""
    last = messages[-1]["content"]
    if isinstance(last, list):                                    # a tool result came back
        return {"text": f"Done. {last[0]['content']}"}
    if "book" in last.lower() and tools_allowed:
        morning = "morning" in messages[0]["content"].lower()
        return {"tool": ("create_event", {"title": "Catch-up with Alex",
                                          "time": "09:00" if morning else "14:00"})}
    if "message sam" in last.lower() and tools_allowed:
        return {"tool": ("send_message", {"to": "sam", "body": "running late"})}
    return {"text": "OK."}


TOOLS = {"create_event": lambda a: f"booked {a['title']} at {a['time']}",
         "send_message": lambda a: f"sent to {a['to']}"}
NEEDS_YES = {"send_message"}                                      # Waku's `ask` mode


def run_loop(system: str, user: str, max_iterations: int = 5) -> Reply:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    out = Reply()
    for _ in range(max_iterations):
        response = model(messages)                                 # reason
        if "tool" not in response:                                 # exit 1: no tool call
            out.text = response["text"]
            return out
        name, args = response["tool"]
        if name in NEEDS_YES:                                      # park, do not run
            digest = hashlib.sha256(json.dumps([name, args], sort_keys=True).encode()).hexdigest()
            db.execute("INSERT INTO parked (tool, args, sha256) VALUES (?, ?, ?)",
                       (name, json.dumps(args), digest))
            out.calls.append((name, args))
            out.text = f"Waiting for your yes to run {name}. ({digest[:10]})"
            return out
        result = TOOLS[name](args)                                 # act
        out.calls.append((name, args))
        messages.append({"role": "user", "content": [{"type": "tool_result", "content": result}]})
    out.limit_reached = True                                       # exit 2: one last call, tools off
    out.text = model(messages, tools_allowed=False)["text"]
    return out


# ---- always-on: inbox -> run -> outbox -----------------------------------------------------

def receive(source: str, external_id: str, text: str) -> bool:
    cur = db.execute("INSERT OR IGNORE INTO events (source, external_id, text) VALUES (?, ?, ?)",
                     (source, external_id, text))
    return cur.rowcount == 1                                       # False = a redelivery


def work() -> None:
    for event in db.execute("SELECT * FROM events WHERE status = 'pending' ORDER BY id").fetchall():
        retrieve, query = gate(event["text"])
        recalled = search(query) if retrieve else []
        system = "You are Waku." + (f" Memory: {' '.join(recalled)}" if recalled else "")
        reply = run_loop(system, event["text"])
        # the key is derived from the event, so a replayed run writes the same key and is dropped
        db.execute("INSERT OR IGNORE INTO outbox (body, idempotency_key) VALUES (?, ?)",
                   (reply.text, f"reply:{event['id']}"))
        db.execute("UPDATE events SET status = 'done' WHERE id = ?", (event["id"],))
        print(f"  gate={'retrieve' if retrieve else 'skip':8} recalled={recalled!s:48} -> {reply.text}")


if __name__ == "__main__":
    remember("Alex", "Alex prefers morning meetings.")
    print("1. a message and its redelivery")
    print("  stored:", receive("telegram", "u1", "Book a catch-up with Alex on Friday"),
          "| redelivered:", receive("telegram", "u1", "Book a catch-up with Alex on Friday"))
    work()
    print("2. a call that needs a yes")
    receive("telegram", "u2", "message Sam I am late")
    work()
    print("3. general knowledge skips memory")
    receive("telegram", "u3", "what is 2+2")
    work()
    print("parked:", [dict(r) for r in db.execute("SELECT tool, sha256 FROM parked")])
    print("outbox rows:", db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])
