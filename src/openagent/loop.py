"""THE LOOP: observe, reason, act, repeat. This file is the whole trick.

Descends from waku/loop/agent.py, trimmed to its bones, with one change: the
`before_tool` seam returns a three-way verdict (see guard.py) instead of a deny
string.

    while not done:
        response = llm(messages, tools)          # reason
        if response asks for tools:
            results = run(tool_calls)            # act
            messages += results                  # observe
        else:
            done                                 # reply to the human

Exit conditions:
  1. the model stops asking for tools   -> natural end of turn
  2. max_iterations reached             -> one last call with tools off, so what the
                                           turn gathered is answered, never thrown away
  3. a call is HELD for approval        -> the run ends parked and sends no reply of its
                                           own. The approval request is the one message.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from openagent.guard import ALLOW, HOLD
from openagent.llm import LLM, Response
from openagent.tools import Ctx, ToolRegistry
from openagent.trace import silent

LIMIT_NOTE = ("You have reached the step limit for this turn and cannot call any more tools. "
              "Answer now from what you already gathered; say plainly what is missing.")
LIMIT_REPLY = "(I hit my iteration limit before finishing. Try breaking the request into smaller steps.)"

# before_tool(name, args) -> (verdict, text the model reads as the result)
BeforeTool = Callable[[str, dict], tuple[str, str]]


@dataclass
class LoopResult:
    reply: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    iterations: int = 0
    limit_reached: bool = False
    parked: bool = False


def run_loop(llm: LLM, system: str, messages: list[dict], tools: ToolRegistry, ctx: Ctx, *,
             before_tool: BeforeTool | None = None, max_iterations: int = 10,
             observer=silent) -> LoopResult:
    """Run one agent turn. `messages` is mutated in place: afterwards it holds the
    turn's whole working memory (thoughts, tool calls, tool results)."""
    result = LoopResult()
    for iteration in range(1, max_iterations + 1):
        result.iterations = iteration
        response: Response = llm(system, messages, tools.schemas())
        observer("llm", {"title": f"llm call {iteration}", "stop_reason": response.stop_reason,
                         "tools_requested": [u["name"] for u in response.tool_uses]})
        messages.append({"role": "assistant", "content": response.content})

        uses = response.tool_uses
        if not uses:                                              # exit 1
            result.reply = response.text
            return result

        tool_results = []
        for idx, call in enumerate(uses):
            started = time.perf_counter()
            verdict, text = before_tool(call["name"], call["input"]) if before_tool else (ALLOW, "")
            if verdict == ALLOW:
                output = tools.execute(call["name"], call["input"], ctx)
            else:
                output = text
            if verdict == HOLD:
                result.parked = True
            event = {"tool": call["name"], "args": call["input"], "output": output,
                     "verdict": verdict, "ms": int((time.perf_counter() - started) * 1000)}
            result.tool_calls.append(event)
            observer("tool", {"title": f"{call['name']} -> {verdict}", **event})
            tool_results.append({"type": "tool_result", "tool_use_id": call["id"], "content": output})
            if result.parked:
                # Keep tool_result sequence well-formed for providers that require one result per tool_use.
                for skipped in uses[idx + 1:]:
                    tool_results.append({"type": "tool_result", "tool_use_id": skipped["id"],
                                         "content": "Skipped: a prior tool call in this turn requires approval."})
                break
        messages.append({"role": "user", "content": tool_results})

        if result.parked:                                         # exit 3
            return result

    result.limit_reached = True                                   # exit 2
    observer("limit", {"title": "iteration limit reached, answering with tools off"})
    try:
        final = llm(f"{system}\n\n{LIMIT_NOTE}", messages, tools.schemas(), tool_choice="none")
        result.reply = final.text or LIMIT_REPLY
    except Exception:                                             # noqa: BLE001
        result.reply = LIMIT_REPLY
    return result
