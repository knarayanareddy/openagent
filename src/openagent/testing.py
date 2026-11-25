"""An offline stand-in for a model, so every behaviour here is testable with no API key.

Waku's evals do the same thing (evals/conftest.py): the deterministic tier fakes the
model and asserts on the harness, because the harness is what you wrote. The judge tier
(not included here) scores real model output.

ScriptedLLM reads the last message and answers by rule. It speaks the dialect in llm.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openagent.llm import LLM, Response


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if block.get("type") == "text":
            parts.append(block["text"])
        elif block.get("type") == "tool_result":
            parts.append(str(block["content"]))
    return "\n".join(parts)


def say(text: str) -> Response:
    return Response([{"type": "text", "text": text}])


def call(name: str, **args: Any) -> Response:
    return Response([{"type": "tool_use", "id": f"toolu_{name}", "name": name, "input": args}],
                    stop_reason="tool_use")


class ScriptedLLM:
    """Rules, tried in order, against the last message in the conversation."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_next_dream = False

    def __call__(self, system: str, messages: list[dict], tools: list[dict], tool_choice: str | None = None,
                 **_: Any) -> Response:
        last = messages[-1]
        text = _text(last["content"])
        self.calls.append({"system": system, "last": text, "tool_choice": tool_choice})

        if "You are a retrieval gate" in text:                      # the gate
            message = text.split("User message:", 1)[1].strip()
            needs = bool(re.search(r"\b(alex|sam|priya|meeting|catch-up|book|remember|prefer)", message, re.I))
            query = " ".join(re.findall(r"[A-Z][a-z]+", message)) or message
            return say(json.dumps({"retrieve": needs, "query": query if needs else "",
                                   "reason": "mentions a person or plan" if needs else "self-contained"}))

        if system.startswith("You distill"):                        # the Dream pass
            if self.fail_next_dream:
                raise RuntimeError("provider returned 529 overloaded")
            return say(json.dumps({"facts": [
                {"subject": "Priya", "content": "Priya leads the Acme demo on 2026-03-14.", "durable": False},
                {"subject": "Priya", "content": "Priya wants stand-ups at 09:30 sharp.", "durable": True},
                {"subject": "assistant", "content": "The treg balance is $0.75 (750,000 micro).", "durable": False},
                {"subject": "Alex", "content": "Alex's quarterly review is on 2026-03-12 at 15:00.", "durable": False},
                {"subject": "Alex", "content": "Alex prefers morning meetings.", "durable": True}],
                "episode": "Set up Alex's catch-up and arranged a message to Sam."}))

        if last["role"] == "user" and not isinstance(last["content"], str):   # a tool result came back
            if "queued for" in text and "approved" in text.lower():
                return say("Queued. Sam will get the message.")
            if "booked:" in text:
                return say(f"Booked. {text.split('booked: ', 1)[1]}.")
            if "Refused by the guard" in text:
                return say("I could not send that. " + text.split("guard: ", 1)[-1])
            if '"refused": true' in text:
                reason = json.loads(text)["error"].split(". Memory", 1)[0].replace("Refused: ", "")
                return say(f"I did not save that. {reason}.")
            if "needs the owner's approval" in text:
                return say("(should never be sent: a parked run ends before this call)")
            if '"success": true' in text:
                return say("Noted. I will remember that.")
            return say(f"Done: {text[:100]}")

        if text.startswith("[timer]"):
            return say("Good morning. Your calendar is empty today and nothing is waiting on you.")
        if text.startswith("[approval]"):
            if "approved" in text.lower():
                return say("Queued. Sam will get the message.")
            return say("Understood. I did not send it.")
        if m := re.match(r"remember that (\w+) prefers (.+?)\.?$", text, re.I):
            return call("remember_preference", entry=f"{m[1]} prefers {m[2]}.")
        if text.lower().startswith("remember:"):
            return call("remember_preference", entry=text.split(":", 1)[1].strip())
        if m := re.match(r"book a catch-up with (\w+) on (\w+)", text, re.I):
            morning = "prefers morning" in system.lower()
            return call("book_meeting", **{"with": m[1], "day": m[2], "time": "09:00" if morning else "14:00"})
        if m := re.match(r"message (\w+) that (.+)", text, re.I):
            return call("send_message", to="telegram:2002", body=m[2])
        if text.startswith("email "):
            return call("send_message", to=text.split(" ", 1)[1].split(" ")[0], body="hello")
        if text.startswith("loop forever"):
            return call("recall", query="anything")
        return say("OK.")


class ReplayLLM:
    """Record/replay LLM responses for deterministic evals of real interactions.

    mode="record": wraps an inner LLM, writes each call+response to JSONL.
    mode="replay": reads responses from JSONL in order, no inner LLM needed.

    This makes provider behavior reproducible in tests without live API calls.
    """
    def __init__(self, path: str | Path, mode: str = "replay", inner: LLM | None = None):
        self.path = Path(path)
        self.mode = mode
        self.inner = inner
        self._replay: list[dict] | None = None
        self._index = 0
        self.calls: list[dict] = []

    def _load(self) -> list[dict]:
        if self._replay is None:
            if not self.path.exists():
                self._replay = []
            else:
                self._replay = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return self._replay

    def __call__(self, system: str, messages: list[dict], tools: list[dict], tool_choice: str | None = None, **_: Any) -> Response:
        record = {"system": system, "messages": messages, "tools": tools, "tool_choice": tool_choice}
        self.calls.append(record)
        if self.mode == "replay":
            rows = self._load()
            if self._index >= len(rows):
                raise RuntimeError(f"ReplayLLM exhausted at index {self._index} ({self.path})")
            row = rows[self._index]
            self._index += 1
            return Response(content=row["content"], stop_reason=row.get("stop_reason", "end_turn"), usage=row.get("usage", {"in": 0, "out": 0}))
        if self.inner is None:
            raise RuntimeError("ReplayLLM record mode requires inner LLM")
        resp = self.inner(system, messages, tools, tool_choice=tool_choice)
        row = {**record, "content": resp.content, "stop_reason": resp.stop_reason, "usage": resp.usage}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return resp
