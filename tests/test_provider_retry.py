from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from openagent.providers.anthropic import AnthropicProvider
from openagent.providers.openai import OpenAIProvider


class _Resp:
    def __init__(self, payload: dict):
        self._b = json.dumps(payload).encode()
    def read(self):
        return self._b
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


def test_anthropic_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}
    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {}, io.BytesIO(b"slow down"))
        return _Resp({"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "usage": {}})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("openagent.providers.anthropic.time.sleep", lambda *_: None)
    p = AnthropicProvider(api_key="x")
    r = p(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])
    assert r.content[0]["text"] == "ok"
    assert calls["n"] == 2


def test_anthropic_raises_on_url_error_after_retries(monkeypatch):
    calls = {"n": 0}
    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        raise urllib.error.URLError("down")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("openagent.providers.anthropic.time.sleep", lambda *_: None)
    p = AnthropicProvider(api_key="x")
    with pytest.raises(RuntimeError, match="request failed"):
        p(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])
    assert calls["n"] == 3


def test_openai_retries_on_503_then_succeeds(monkeypatch):
    calls = {"n": 0}
    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 503, "unavailable", {}, io.BytesIO(b"no"))
        return _Resp({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("openagent.providers.openai.time.sleep", lambda *_: None)
    p = OpenAIProvider(api_key="x")
    r = p(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])
    assert r.content[0]["text"] == "ok"
    assert calls["n"] == 3


def test_openai_honors_retry_after_header(monkeypatch):
    from email.message import Message
    calls = {"n": 0, "sleep": []}
    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            h = Message(); h["retry-after"] = "2"
            raise urllib.error.HTTPError(req.full_url, 429, "rate", h, io.BytesIO(b"slow"))
        return _Resp({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("openagent.providers.openai.time.sleep", lambda s: calls["sleep"].append(s))
    p = OpenAIProvider(api_key="x")
    r = p(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])
    assert r.content[0]["text"] == "ok"
    assert calls["sleep"] and calls["sleep"][0] == 2.0


def test_openai_honors_retry_after_http_date(monkeypatch):
    from email.message import Message
    from email.utils import formatdate
    calls = {"n": 0, "sleep": []}
    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            h = Message(); h["retry-after"] = formatdate(timeval=__import__("time").time() + 1, usegmt=True)
            raise urllib.error.HTTPError(req.full_url, 503, "unavailable", h, io.BytesIO(b"no"))
        return _Resp({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("openagent.providers.openai.time.sleep", lambda s: calls["sleep"].append(s))
    p = OpenAIProvider(api_key="x")
    r = p(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])
    assert r.content[0]["text"] == "ok"
    assert calls["sleep"] and 0 <= calls["sleep"][0] <= 5
