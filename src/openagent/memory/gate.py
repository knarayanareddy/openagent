"""The gate that decides WHETHER to read memory at all.

Descends from waku/memory/retrieval_gate.py.

Reading memory on every turn is slow, and worse, irrelevant memories bias the
answer. So a cheap model answers one narrow question first: does THIS message
need the user's memory? "what's 2+2" no. "when am I meeting Alex?" yes, and
here are the search words.

It fails open. If the gate errors or returns no JSON we retrieve, because a stale
memory beats a lost one.
"""

from __future__ import annotations

import json

from openagent.llm import LLM

GATE_PROMPT = """\
You are a retrieval gate for a personal assistant's long-term memory.
Given the user's message, decide if answering well requires the user's stored
memories (facts about people, projects, preferences, or past events).

Reply with ONLY this JSON, nothing else:
{{"retrieve": true/false, "query": "<search keywords if true, else empty>", "reason": "<5 words>"}}

General knowledge, math, small talk, or self-contained requests -> false.
Anything referencing the user's life, people, plans, or history -> true.

User message: {message}"""


def should_retrieve(llm: LLM, message: str) -> tuple[bool, str, str]:
    """Returns (retrieve?, search_query, reason)."""
    try:
        response = llm("", [{"role": "user", "content": GATE_PROMPT.format(message=message)}], [])
        text = response.text
        if "{" not in text:
            return True, message, "gate returned no JSON, failing open"
        decision = json.loads(text[text.index("{"): text.rindex("}") + 1])
        return (bool(decision.get("retrieve")), decision.get("query") or message,
                decision.get("reason", ""))
    except Exception as exc:                       # noqa: BLE001 - fail open on anything
        return True, message, f"gate failed open ({type(exc).__name__})"
