"""The one dialect the loop speaks.

Waku's rule (waku/loop/models.py): one dialect in the loop, a ~60-line adapter per
provider. The dialect is Anthropic's content blocks:

    {"type": "text", "text": "..."}
    {"type": "tool_use", "id": "...", "name": "...", "input": {...}}

A model is any callable `(system, messages, tools, tool_choice=None) -> Response`.
Swap in the real Anthropic client by wrapping `client.messages.create` in a
function with this signature; `openagent.testing.ScriptedLLM` is the offline stand-in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Block = dict[str, Any]


@dataclass
class Response:
    content: list[Block]
    stop_reason: str = "end_turn"
    usage: dict[str, int] = field(default_factory=lambda: {"in": 0, "out": 0})

    @property
    def text(self) -> str:
        return "".join(b["text"] for b in self.content if b["type"] == "text")

    @property
    def tool_uses(self) -> list[Block]:
        return [b for b in self.content if b["type"] == "tool_use"]


LLM = Callable[..., Response]


def text_of(response: Response) -> str:
    return response.text
