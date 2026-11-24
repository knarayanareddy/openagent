"""OpenAI Chat Completions adapter (stdlib, no extra dependency required).

Provenance: adapter pattern follows waku/loop/models.py (one dialect inside the loop,
thin provider adapters at the edge). Converts between OpenAI chat format and the
internal Anthropic-style content block dialect.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from openagent.llm import Response


def _tools_to_openai(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


def _messages_to_openai(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        role = m["role"]
        content = m.get("content", "")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        # content blocks
        if role == "assistant":
            text_parts = []
            tool_calls = []
            for b in content:
                if b.get("type") == "text":
                    text_parts.append(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    tool_calls.append({
                        "id": b.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": b.get("name", ""),
                            "arguments": json.dumps(b.get("input", {}), ensure_ascii=False),
                        },
                    })
            msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
        elif role == "user":
            # may contain tool_result blocks
            tool_results = [b for b in content if b.get("type") == "tool_result"]
            other = [b for b in content if b.get("type") != "tool_result"]
            for tr in tool_results:
                out.append({
                    "role": "tool",
                    "tool_call_id": tr.get("tool_use_id", ""),
                    "content": str(tr.get("content", "")),
                })
            if other:
                text = "\n".join(b.get("text", str(b)) for b in other)
                out.append({"role": "user", "content": text})
        else:
            out.append({"role": role, "content": str(content)})
    return out


def _response_from_openai(data: dict) -> Response:
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message", {})
    blocks: list[dict[str, Any]] = []
    text = msg.get("content")
    if text:
        blocks.append({"type": "text", "text": text})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"_raw": fn.get("arguments", "")}
        blocks.append({
            "type": "tool_use",
            "id": tc.get("id", f"call_{fn.get('name','tool')}"),
            "name": fn.get("name", ""),
            "input": args,
        })
    if not blocks:
        blocks = [{"type": "text", "text": ""}]
    usage = data.get("usage", {})
    return Response(
        content=blocks,
        stop_reason=choice.get("finish_reason", "stop"),
        usage={"in": usage.get("prompt_tokens", 0), "out": usage.get("completion_tokens", 0)},
    )


class OpenAIProvider:
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1/chat/completions",
        max_tokens: int = 1024,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.timeout = timeout

    def __call__(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str | None = None,
        **_: Any,
    ) -> Response:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(_messages_to_openai(messages))

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = _tools_to_openai(tools)
        if tool_choice == "none":
            payload["tool_choice"] = "none"
        elif tool_choice == "any":
            payload["tool_choice"] = "required"

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=body,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API {e.code}: {detail[:500]}") from e
        return _response_from_openai(data)
