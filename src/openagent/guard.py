"""The guard: one function decides what a tool call may do.

Descends from NanoClaw's src/guard/ (TypeScript: guard.ts, guard-actions.ts,
types.ts, delivery-guard.ts) and src/command-gate.ts, ported to Python. It
replaces Waku's per-tool `allow`/`ask` string with a three-way verdict, and keeps
Waku's SHA-256 hash of the parked call.

  ALLOW   run it
  DENY    never run it, and tell the model why
  HOLD    park it: store the call, ask the owner, end the run

The rule that matters, taken from NanoClaw's runGuarded:

    An approved replay satisfies a HOLD but never a DENY.

On "yes" the rules run again, live. A call that was merely held becomes allowed;
a call that has since become structurally forbidden (the address was revoked, the
tool was disabled) stays denied. Approve-then-revoke does not execute.

Unknown tools are DENIED. A guard that fails open on a typo is not a guard.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

ALLOW, DENY, HOLD = "allow", "deny", "hold"


@dataclass(frozen=True)
class Decision:
    verdict: str
    reason: str = ""


@dataclass(frozen=True)
class Grant:
    """What an approved replay carries: the hash of the call the owner saw."""
    args_sha256: str


Rule = Callable[[dict, "object"], Decision]


def call_hash(tool: str, args: dict) -> str:
    """SHA-256 of the call exactly as parked. The model is never asked again after a
    yes, so it cannot change the arguments between the question and the answer."""
    blob = json.dumps([tool, args], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Guard:
    def __init__(self, rules: dict[str, Rule]) -> None:
        self.rules = rules

    def decide(self, tool: str, args: dict, ctx: object, grant: Grant | None = None) -> Decision:
        rule = self.rules.get(tool)
        if rule is None:
            return Decision(DENY, f"no guard rule for '{tool}'")
        decision = rule(args, ctx)                   # structural checks always run live
        if decision.verdict == HOLD and grant is not None:
            if grant.args_sha256 == call_hash(tool, args):
                return Decision(ALLOW, "approved by the owner")
            return Decision(DENY, "the call changed after it was approved")
        return decision                              # a grant never upgrades a DENY


# ---- the command gate (NanoClaw: src/command-gate.ts) -------------------------

PASS, FILTER, DENY_CMD = "pass", "filter", "deny"
FILTERED_COMMANDS = {"/compact", "/context"}         # dropped silently, never reach the model
ADMIN_COMMANDS = {"/clear", "/dream", "/revert"}


def gate_command(text: str, sender_is_admin: bool) -> tuple[str, str]:
    """Classify a slash command before it can reach the agent."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return PASS, ""
    command = stripped.split()[0].lower()
    if command in FILTERED_COMMANDS:
        return FILTER, command
    if command in ADMIN_COMMANDS:
        return (PASS, command) if sender_is_admin else (DENY_CMD, command)
    return PASS, command                             # unknown slash commands pass through
