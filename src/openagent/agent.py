"""Fusion.respond(): one turn, with every pillar in its place.

Descends from waku/app.py (`Waku.respond`) and waku/runtime/session.py.

  1. SNAPSHOT  curated memory is read once per session and frozen (Hermes)
  2. GATE      a small model decides whether this message needs memory (Waku)
  3. RECALL    only then, FTS5 search of facts and episodes (Waku)
  4. LOOP      reason/act/repeat, every tool call through the guard (Waku + NanoClaw)
  5. SAVE      the exchange goes to chat_log, which the Dream pass reads (nanobot)
  6. DREAM     if enough new chats have piled up, distil them (nanobot + Waku)
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openagent.alwayson import approvals, outbox
from openagent.db import connect
from openagent.guard import ALLOW, DENY, HOLD, Guard
from openagent.llm import LLM
from openagent.loop import LoopResult, run_loop
from openagent.memory import dream
from openagent.memory.audit import MemoryAudit
from openagent.memory.curated import CuratedMemory
from openagent.memory.gate import should_retrieve
from openagent.memory.semantic import SemanticMemory
from openagent.tools import Ctx, ToolRegistry, default_rules, default_tools
from openagent.trace import silent

SOUL = ("You are OpenAgent, a personal assistant that lives on the owner's machine. "
        "Be brief. Use memory only when it helps. Never claim an action happened unless a tool said so.")


@dataclass
class Turn:
    reply: str
    loop: LoopResult
    recalled: str = ""
    dream: dream.DreamResult | None = None
    history: list[dict] = field(default_factory=list)


class Fusion:
    def __init__(self, home: Path, llm: LLM, small_llm: LLM | None = None, *, owner: str = "telegram:1001",
                 every_n: int = 4, observer=silent, tools: ToolRegistry | None = None,
                 guard: Guard | None = None, max_iterations: int = 10) -> None:
        self.home = home
        self.conn = connect(home)
        self.llm, self.small_llm = llm, small_llm or llm
        self.owner, self.every_n, self.observer = owner, every_n, observer
        self.max_iterations = max_iterations
        self.curated = CuratedMemory(home / "memories")
        self.semantic = SemanticMemory(self.conn)
        self.audit = MemoryAudit(home / "memories")
        self.tools = tools or default_tools()
        self.guard = guard or Guard(default_rules())
        self._snapshots: dict[str, str] = {}
        self._recalled: list[str] = []

    # ------------------------------------------------------------------------
    def ctx(self, session_id: str, reply_to: dict, now: datetime, run_id: str) -> Ctx:
        return Ctx(self.conn, self.curated, self.semantic, session_id, reply_to, now, run_id,
                   owner_addresses=[self.owner])

    def new_session(self, session_id: str) -> None:
        """Forget the frozen snapshot, as a restart would."""
        self._snapshots.pop(session_id, None)

    def respond(self, session_id: str, text: str, reply_to: dict, now: datetime) -> Turn:
        run_id = uuid.uuid4().hex[:12]
        # 1. SNAPSHOT: frozen for the session, so the prompt prefix stays cacheable
        if session_id not in self._snapshots:
            self._snapshots[session_id] = self.curated.snapshot()
            self.observer("snapshot", {"title": "curated memory frozen for this session",
                                       "memory": self._snapshots[session_id] or "(empty)"})
        # 2-3. GATE then RECALL
        recalled = ""
        retrieve, query, reason = should_retrieve(self.small_llm, text)
        self.observer("gate", {"title": f"gate: {'retrieve' if retrieve else 'skip memory'}",
                               "reason": reason, "query": query if retrieve else ""})
        if retrieve:
            recalled = self.semantic.recall_text(query)
            self.observer("recall", {"title": f"recalled {len(recalled.splitlines())} item(s)",
                                     "text": recalled or "(nothing found)"})
            if recalled:
                self._recalled.append(recalled)

        system = SOUL + (f"\n\n{self._snapshots[session_id]}" if self._snapshots[session_id] else "")
        if recalled:
            system += f"\n\nRelevant memory:\n{recalled}"

        # 4. LOOP, with every tool call through the guard
        ctx = self.ctx(session_id, reply_to, now, run_id)
        origin_address = outbox.format_address(reply_to["via"], reply_to) if reply_to else ""

        def before_tool(name: str, args: dict) -> tuple[str, str]:
            decision = self.guard.decide(name, args, ctx)
            self.observer("guard", {"title": f"guard: {name} -> {decision.verdict}",
                                    "reason": decision.reason, "args": args})
            if decision.verdict == DENY:
                return DENY, f"Refused by the guard: {decision.reason}"
            if decision.verdict == HOLD:
                digest = approvals.park(self.conn, approver=self.owner, origin_session=session_id,
                                        origin_address=origin_address, tool=name, args=args, now=now)
                if digest is None:
                    return DENY, "Another call is already waiting for the owner's yes. Try later."
                target = outbox.parse_address(self.owner)
                assert target is not None
                outbox.insert(self.conn, run_id=run_id, channel=target[0], target=target[1],
                              body=approvals.question(name, args), idempotency_key=f"approval:{digest}",
                              now=now)
                self.observer("approval", {"title": f"{name} parked, owner asked", "sha256": digest[:12]})
                return HOLD, ("This call needs the owner's approval and has been asked. "
                              "Do not say it was done. It runs only after a yes.")
            return ALLOW, ""

        history = [{"role": r["role"], "content": r["content"]} for r in self.conn.execute(
            "SELECT role, content FROM chat_log WHERE session_id = ? ORDER BY id DESC LIMIT 8",
            (session_id,)).fetchall()][::-1]
        messages = [*history, {"role": "user", "content": text}]
        loop = run_loop(self.llm, system, messages, self.tools, ctx, before_tool=before_tool,
                        max_iterations=self.max_iterations, observer=self.observer)

        # 5. SAVE (a parked run says nothing, so only the user's side is logged)
        self.conn.execute("INSERT INTO chat_log (session_id, role, content) VALUES (?, 'user', ?)",
                          (session_id, text))
        if loop.reply:
            self.conn.execute("INSERT INTO chat_log (session_id, role, content) VALUES (?, 'assistant', ?)",
                              (session_id, loop.reply))
        self.conn.commit()
        self.observer("reply", {"title": "parked, no reply" if loop.parked else "reply ready",
                                "reply": loop.reply})

        # 6. DREAM, only when enough new chats have piled up
        result = None
        if dream.dream_due(self.conn, self.every_n):
            result = self.run_dream(now)
        return Turn(loop.reply, loop, recalled, result, messages)

    def run_dream(self, now: datetime, force: bool = False) -> dream.DreamResult:
        result = dream.run_dream(self.conn, self.small_llm, self.semantic, self.curated, self.audit,
                                 now=now, recalled="\n".join(self._recalled), every_n=self.every_n,
                                 force=force, observer=self.observer)
        if result.ran:
            self._recalled.clear()
        return result


def pretty(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
