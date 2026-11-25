"""Regression tests for first fix batch (F-01,F-03/F-05,F-08,F-09,F-11,F-12)."""
from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from conftest import ME, NOW, OWNER
from openagent.agent import Fusion
from openagent.alwayson import events, outbox
from openagent.alwayson.worker import Worker
from openagent.llm import Response
from openagent.providers.anthropic import AnthropicProvider
from openagent.providers.openai import OpenAIProvider
from openagent.testing import ScriptedLLM
from openagent.tools import default_tools


def test_f01_local_owner_hold_does_not_crash(tmp_path):
    # Default owner in real deployments can be local:owner; HOLD must not crash.
    fusion = Fusion(tmp_path / "home", ScriptedLLM(), owner="local:owner")
    turn = fusion.respond("cli", "Message Sam that the demo moved to 3pm",
                          {"via": "cli", "chat_id": "local:owner"}, NOW)
    assert turn.loop.parked is True
    parked = fusion.conn.execute("SELECT COUNT(*) FROM parked").fetchone()[0]
    outbox_rows = fusion.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    assert parked == 1
    assert outbox_rows == 1  # approval prompt queued


def test_f01_parse_address_accepts_local_cli_stdout_webhook():
    assert outbox.parse_address("local:owner") == ("local", {"chat_id": "owner"})
    assert outbox.parse_address("cli:user") == ("cli", {"chat_id": "user"})
    assert outbox.parse_address("stdout:x") == ("stdout", {"chat_id": "x"})
    assert outbox.parse_address("webhook:hook1") == ("webhook", {"chat_id": "hook1"})


def test_f08_multi_tool_hold_breaks_and_skips_remaining(fusion):
    calls = []

    def multi_llm(system, messages, tools, tool_choice=None, **_):
        if tool_choice == "none":
            return Response([{"type": "text", "text": "done"}])
        return Response([
            {"type": "tool_use", "id": "1", "name": "send_message",
             "input": {"to": "telegram:2002", "body": "hi"}},
            {"type": "tool_use", "id": "2", "name": "book_meeting",
             "input": {"with": "Alex", "day": "Fri", "time": "09:00"}},
        ], stop_reason="tool_use")

    fusion.llm = multi_llm
    turn = fusion.respond("s", "message Sam and book Alex", ME, NOW)
    assert turn.loop.parked is True
    # second tool must not execute
    assert fusion.conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0] == 0
    # skipped result should be present for well-formed tool_result sequence
    tool_results = [m for m in turn.history if m["role"] == "user" and isinstance(m["content"], list)]
    assert tool_results
    contents = [b["content"] for b in tool_results[-1]["content"] if b.get("type") == "tool_result"]
    assert any("Skipped" in c for c in contents)


def test_f08_admin_commands_execute_in_worker(fusion):
    worker = Worker(fusion, {"telegram": lambda t, b: None}, home=fusion.home, batch_wait=0, sleep=lambda s: None)
    events.insert(fusion.conn, source="telegram", external_id="c1", session_id=OWNER,
                  payload={"text": "/clear", "reply_to": ME}, now=NOW)
    res = worker.tick(NOW)
    assert res.handled == "command"
    assert "cleared" in res.reply.lower()

    events.insert(fusion.conn, source="telegram", external_id="c2", session_id=OWNER,
                  payload={"text": "/dream", "reply_to": ME}, now=NOW)
    res2 = worker.tick(NOW)
    assert res2.handled == "command"
    assert "Dream" in res2.reply


def test_f09_remember_preference_replace_remove_and_memory_target(fusion):
    ctx = fusion.ctx("s", ME, NOW, "r1")
    tools = default_tools()
    tools.execute("remember_preference", {"entry": "Alex prefers tea."}, ctx)
    out = tools.execute("remember_preference", {
        "action": "replace", "old_text": "Alex prefers tea", "entry": "Alex prefers coffee.", "target": "user"
    }, ctx)
    assert json.loads(out)["success"] is True
    assert fusion.curated.entries("user") == ["Alex prefers coffee."]

    out2 = tools.execute("remember_preference", {"action": "add", "target": "memory", "entry": "Use pytest -q."}, ctx)
    assert json.loads(out2)["success"] is True
    assert fusion.curated.entries("memory") == ["Use pytest -q."]

    out3 = tools.execute("remember_preference", {"action": "remove", "target": "memory", "old_text": "pytest"}, ctx)
    assert json.loads(out3)["success"] is True
    assert fusion.curated.entries("memory") == []


def _fake_urlopen_capture(seen):
    class FakeResp:
        def __init__(self, payload):
            self._payload = payload
        def read(self):
            return json.dumps(self._payload).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake(req, timeout=60.0):
        seen.append(json.loads(req.data.decode("utf-8")))
        url = req.full_url
        if "anthropic" in url:
            return FakeResp({"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "usage": {}})
        return FakeResp({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})
    return fake


def test_f11_anthropic_omits_tool_choice_when_no_tools(monkeypatch):
    seen = []
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_capture(seen))
    p = AnthropicProvider(api_key="x", model="m")
    p("sys", [{"role": "user", "content": "hi"}], [], tool_choice="none")
    assert "tool_choice" not in seen[0]


def test_f11_openai_omits_tool_choice_when_no_tools(monkeypatch):
    seen = []
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_capture(seen))
    p = OpenAIProvider(api_key="x", model="m")
    p("sys", [{"role": "user", "content": "hi"}], [], tool_choice="none")
    assert "tool_choice" not in seen[0]


def test_f12_db_has_fts_triggers_and_busy_timeout(tmp_path):
    from openagent.db import connect
    conn = connect(tmp_path / "h")
    triggers = {r[1] for r in conn.execute("SELECT * FROM sqlite_master WHERE type='trigger'").fetchall()}
    assert {"facts_ai", "facts_ad", "facts_au", "episodes_ai", "episodes_ad", "episodes_au"} <= triggers
    busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert busy == 5000
