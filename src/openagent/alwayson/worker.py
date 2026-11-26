"""The worker: one per home. Claims events, runs the agent, writes to the outbox.

Descends from waku/alwayson/worker.py and serve.py.

    start()   recover claimed rows from a dead run; honour the circuit breaker
    tick()    fire due timers -> claim the oldest event -> wait to batch the session
              -> an approval answer? -> a gated command? -> one run -> outbox -> dispatch

The run never talks to a person. It returns a reply and the worker puts the reply in the
outbox with an idempotency key built from the event ids, so a replayed run writes the same
key and the person gets one message.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openagent.agent import QUIET, Fusion
from openagent.alwayson import approvals, breaker, events, outbox, timers
from openagent.guard import ADMIN_COMMANDS, DENY_CMD, FILTER, gate_command


@dataclass
class TickResult:
    handled: str = "idle"          # idle | run | approval | command
    session_id: str = ""
    reply: str = ""
    parked: bool = False


class Worker:
    def __init__(self, fusion: Fusion, senders: dict[str, outbox.Sender], *, home: Path,
                 batch_wait: float = 3.0, sleep: Callable[[float], None] = time.sleep) -> None:
        self.fusion, self.senders, self.home = fusion, senders, home
        self.batch_wait, self.sleep = batch_wait, sleep
        self.conn, self.observer = fusion.conn, fusion.observer

    def start(self, now: datetime) -> int:
        attempt, delay = breaker.enforce_startup_backoff(self.home / "circuit-breaker.json", now, self.sleep)
        self.observer("breaker", {"title": f"startup attempt {attempt}, waited {delay}s",
                                  "attempt": attempt, "delay": delay})
        recovered = events.recover(self.conn)
        if recovered:
            self.observer("recover", {"title": f"{recovered} claimed event(s) returned to pending"})
        return recovered

    def stop(self) -> None:
        breaker.reset(self.home / "circuit-breaker.json")

    def is_owner(self, session_id: str) -> bool:
        return session_id == self.fusion.owner

    def tick(self, now: datetime) -> TickResult:
        timers.fire_due(self.conn, now, self.observer)
        event = events.claim_next(self.conn)
        if event is None:
            outbox.dispatch(self.conn, self.senders, now, self.observer)
            return TickResult()
        self.sleep(self.batch_wait)                       # let a burst from one chat arrive
        batch = [event, *events.claim_session(self.conn, event.session_id)]
        ids = [e.id for e in batch]
        self.observer("claim", {"title": f"claimed {len(batch)} event(s) for {event.session_id}",
                                "ids": ids, "source": event.source})
        text = "\n".join(str(e.payload.get("text", "")) for e in batch)
        reply_to = event.payload.get("reply_to") or {}
        run_id = hashlib.sha256(",".join(map(str, ids)).encode()).hexdigest()[:12]
        out = TickResult(session_id=event.session_id)
        try:
            ctx = self.fusion.ctx(event.session_id, reply_to, now, run_id)
            # an approval answer is read BEFORE a run starts
            held_digest_resume: str | None = None
            resume_system = ""
            parked_row = self.conn.execute("SELECT resume_state FROM parked WHERE approver_session = ?", (event.session_id,)).fetchone()
            if parked_row:
                try:
                    rs = json.loads(parked_row["resume_state"] or "{}")
                    if isinstance(rs, dict):
                        resume_system = str(rs.get("system") or "")
                except Exception:
                    pass
            def _resume_before_tool(name: str, args: dict) -> tuple[str, str]:
                nonlocal held_digest_resume
                decision = self.fusion.guard.decide(name, args, ctx)
                if decision.verdict == "deny":
                    return "deny", f"Refused by the guard: {decision.reason}"
                if decision.verdict == "hold":
                    target = outbox.parse_address(self.fusion.owner)
                    if target is None:
                        return "deny", f"Owner address {self.fusion.owner!r} is not a routable address; cannot request approval."
                    digest = approvals.park(self.conn, approver=self.fusion.owner, origin_session=event.session_id,
                                            origin_address=outbox.format_address(reply_to.get("via", ""), reply_to) if reply_to else "", tool=name, args=args, now=now)
                    if digest is None:
                        return "deny", "Another call is already waiting for the owner's yes. Try later."
                    held_digest_resume = digest
                    outbox.insert(self.conn, run_id=run_id, channel=target[0], target=target[1],
                                  body=approvals.question(name, args), idempotency_key=f"approval:{digest}", now=now)
                    return "hold", "This call needs the owner's approval and has been asked. Do not say it was done. It runs only after a yes."
                return "allow", ""
            def _resume_on_hold(held_call: dict, held_messages: list[dict], batch_uses: list[dict]) -> None:
                if held_digest_resume is None:
                    return
                # best-effort: reuse current snapshot/system context is not stored here; the resume_state from original park remains authoritative
                approvals.set_resume_state(self.conn, self.fusion.owner, held_digest_resume, {
                    "version": 1,
                    "session_id": event.session_id,
                    "reply_to": reply_to,
                    "system": resume_system,
                    "messages": held_messages,
                    "held_call": held_call,
                    "batch_uses": batch_uses,
                    "max_iterations": self.fusion.max_iterations,
                })
            outcome = (approvals.answer(self.conn, session_id=event.session_id, text=text, now=now,
                                        guard=self.fusion.guard, tools=self.fusion.tools, ctx=ctx,
                                        observer=self.observer, llm=self.fusion.llm, before_tool=_resume_before_tool, on_hold=_resume_on_hold)
                       if self.is_owner(event.session_id) else None)
            if outcome is not None:
                out.handled, out.reply = "approval", outcome
            else:
                verdict, command = gate_command(text, self.is_owner(event.session_id))
                if verdict in (FILTER, DENY_CMD):
                    out.handled, out.reply = "command", ("" if verdict == FILTER else "Permission denied.")
                    self.observer("command", {"title": f"{command} {verdict}"})
                elif verdict == "pass" and command in ADMIN_COMMANDS and self.is_owner(event.session_id):
                    arg = text.strip().split(None, 1)[1].strip() if len(text.strip().split(None, 1)) > 1 else ""
                    if command == "/clear":
                        self.fusion.new_session(event.session_id)
                        self.conn.execute("DELETE FROM chat_log WHERE session_id = ?", (event.session_id,))
                        self.conn.commit()
                        out.handled, out.reply = "command", "Session cleared."
                    elif command == "/dream":
                        res = self.fusion.run_dream(now, force=True, session_id=event.session_id)
                        out.handled, out.reply = "command", f"Dream ran={res.ran} kept={len(res.kept)} dropped={len(res.dropped)} commit={res.commit or 'none'}"
                    elif command == "/revert":
                        if not arg:
                            out.handled, out.reply = "command", "Usage: /revert <sha>"
                        else:
                            ok = self.fusion.audit.revert(arg, self.fusion.semantic)
                            if ok:
                                self.fusion._snapshots.clear()
                                self.fusion._recalled.clear()
                            out.handled, out.reply = "command", (f"Reverted {arg}." if ok else f"Could not revert {arg}.")
                    else:
                        out.handled, out.reply = "command", f"Unknown admin command {command}."
                    self.observer("command", {"title": f"{command} executed", "reply": out.reply})
                else:
                    turn = self.fusion.respond(event.session_id, text, reply_to, now)
                    out.handled, out.reply, out.parked = "run", turn.reply, turn.loop.parked
            if out.reply.strip() == QUIET:
                self.observer("quiet", {"title": "reply was [quiet]; nothing queued"})
                out.reply = ""
            if out.reply and reply_to:
                channel = reply_to["via"]
                target = {k: v for k, v in reply_to.items() if k != "via"}
                outbox.insert(self.conn, run_id=run_id, channel=channel, target=target, body=out.reply,
                              idempotency_key=f"reply:{','.join(map(str, ids))}", now=now)
                self.observer("outbox", {"title": f"reply queued for {outbox.format_address(channel, target)}",
                                         "body": out.reply})
            events.mark(self.conn, ids, "done")
        except Exception as exc:                          # noqa: BLE001
            events.mark(self.conn, ids, "failed")
            self.observer("claim", {"title": f"run failed: {type(exc).__name__}", "error": str(exc)})
            raise
        outbox.dispatch(self.conn, self.senders, now, self.observer)
        return out
