"""Anthropic Messages API adapter (stdlib, no extra dependency required).

Provenance: adapter pattern follows waku/loop/models.py (one dialect inside the loop,
thin provider adapters at the edge).
"""
from __future__ import annotations

import json
import os
import urllib.error
import time
from email.utils import parsedate_to_datetime
import urllib.request
from typing import Any

from openagent.llm import Response


class AnthropicProvider:
    def __init__(
        self,
        model: str = "claude-sonnet-4-5",
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com/v1/messages",
        max_tokens: int = 1024,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
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
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = tools
            if tool_choice == "none":
                payload["tool_choice"] = {"type": "none"}
            elif tool_choice == "any":
                payload["tool_choice"] = {"type": "any"}

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=body,
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")
                last_err = RuntimeError(f"Anthropic API {e.code}: {detail[:500]}")
                if e.code in {429, 500, 502, 503, 504, 529} and attempt < 2:
                    retry_after = e.headers.get("retry-after") if e.headers else None
                    delay = (0.25 * (2 ** attempt)) + (0.05 * (attempt + 1))
                    if retry_after is not None:
                        try:
                            delay = float(retry_after)
                        except Exception:
                            try:
                                dt = parsedate_to_datetime(str(retry_after))
                                delay = dt.timestamp() - time.time()
                            except Exception:
                                pass
                    time.sleep(min(max(delay, 0.0), 8.0))
                    continue
                raise last_err from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = RuntimeError(f"Anthropic request failed: {e}")
                if attempt < 2:
                    time.sleep(0.05 * (2 ** attempt))
                    continue
                raise last_err from e
        else:
            raise last_err or RuntimeError("Anthropic request failed")

        content = data.get("content", [])
        # normalize to our internal block format
        blocks = []
        for b in content:
            if b.get("type") in ("text", "tool_use"):
                blocks.append(b)
        usage = data.get("usage", {})
        return Response(
            content=blocks or [{"type": "text", "text": ""}],
            stop_reason=data.get("stop_reason", "end_turn"),
            usage={"in": usage.get("input_tokens", 0), "out": usage.get("output_tokens", 0)},
        )
