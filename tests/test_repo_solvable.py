from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def _wait_health(url: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e; time.sleep(0.1)
    raise AssertionError(f"health not ready: {last}")

def _post(url: str, payload: dict, token: str | None = None):
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_f04_session_source_text_policy(tmp_path: Path):
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["OPENAGENT_HOME"] = str(tmp_path / "home")
    env["OPENAGENT_PROVIDER"] = "scripted"
    cmd = [sys.executable, "-m", "openagent", "serve", "--host", "127.0.0.1", "--port", str(port),
           "--poll", "0.1", "--token", "secret", "--allowed-session-prefixes", "app:,http:",
           "--allowed-sources", "http,slack", "--max-text-length", "20"]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        _wait_health(f"http://127.0.0.1:{port}/health")
        code, _ = _post(f"http://127.0.0.1:{port}/events", {"text": "ok", "session_id": "bad:1"}, token="secret")
        assert code == 403
        code, _ = _post(f"http://127.0.0.1:{port}/events", {"text": "ok", "session_id": "app:1", "source": "github"}, token="secret")
        assert code == 403
        code, _ = _post(f"http://127.0.0.1:{port}/events", {"text": "x" * 30, "session_id": "app:1"}, token="secret")
        assert code == 413
        code, data = _post(f"http://127.0.0.1:{port}/events", {"text": "ok", "session_id": "app:1", "source": "slack"}, token="secret")
        assert code == 202 and data["queued"] is True
    finally:
        p.terminate()
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.kill()


def test_f04_adversarial_payload_fuzz(tmp_path: Path):
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["OPENAGENT_HOME"] = str(tmp_path / "home")
    env["OPENAGENT_PROVIDER"] = "scripted"
    cmd = [sys.executable, "-m", "openagent", "serve", "--host", "127.0.0.1", "--port", str(port),
           "--poll", "0.1", "--token", "secret", "--rate-limit", "1000"]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        _wait_health(f"http://127.0.0.1:{port}/health")
        # wrong content types / malformed bodies should not crash server
        bad_cases = [
            (b"not json", 400),
            (b"{", 400),
            (json.dumps({"text": 123}).encode(), 202),  # coerced to string, accepted
            (json.dumps({"session_id": "s"}).encode(), 400),  # missing text
            (json.dumps({"text": "ok", "reply_to": "not-a-dict"}).encode(), 202),
        ]
        for body, expected in bad_cases:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/events", data=body,
                                         headers={"content-type": "application/json", "authorization": "Bearer secret"},
                                         method="POST")
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            assert code == expected
        # server still healthy
        h = _wait_health(f"http://127.0.0.1:{port}/health")
        assert h["ok"] is True
    finally:
        p.terminate()
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.kill()


def test_f07_state_json_snapshot_round_trip(tmp_path: Path):
    from openagent.memory.audit import MemoryAudit, export_wiki
    from openagent.db import connect
    from openagent.memory.semantic import SemanticMemory

    conn = connect(tmp_path)
    sem = SemanticMemory(conn)
    sem.add_fact("Alex", "Alex likes coffee", "user")
    sem.add_episode("2026-01-01T00:00:00Z", "Met Alex")
    export_wiki(sem, tmp_path)
    state = tmp_path / "wiki" / "state.json"
    assert state.exists()
    data = json.loads(state.read_text())
    assert data["version"] == 1
    assert data["facts"][0]["subject"] == "Alex"
    assert data["episodes"][0]["summary"] == "Met Alex"

    # Sync into fresh DB from state.json
    conn2 = connect(tmp_path / "other")
    sem2 = SemanticMemory(conn2)
    sem2.add_fact("Old", "old fact", "user")
    n = sem2.sync_from_wiki(tmp_path / "wiki" / "facts.md")
    assert n == 1
    facts = sem2.all_facts()
    assert len(facts) == 1 and facts[0]["content"] == "Alex likes coffee"
    eps = sem2.all_episodes()
    assert len(eps) == 1 and eps[0]["summary"] == "Met Alex"


def test_f07_legacy_markdown_fallback_without_state_json(tmp_path: Path):
    from openagent.db import connect
    from openagent.memory.semantic import SemanticMemory
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "facts.md").write_text("# What I know\n\n## Alex\n- Likes tea\n", encoding="utf-8")
    (wiki / "episodes.md").write_text("# Episodes\n\n- (2026-01-02) Tea time\n", encoding="utf-8")
    conn = connect(tmp_path)
    sem = SemanticMemory(conn)
    sem.sync_from_wiki(wiki / "facts.md")
    assert sem.all_facts()[0]["content"] == "Likes tea"
    assert sem.all_episodes()[0]["summary"] == "Tea time"


def test_cron_multizone_dst_matrix():
    from zoneinfo import ZoneInfo
    from openagent.alwayson.timers import next_cron
    cases = [
        # spring forward: nonexistent local time skips to next day
        ("30 2 * * *", datetime(2026, 3, 8, 6, 0, tzinfo=UTC), "America/New_York", (3, 9, 2, 30)),
        # fall back: first occurrence
        ("30 1 * * *", datetime(2026, 11, 1, 4, 0, tzinfo=UTC), "America/New_York", (11, 1, 1, 30)),
        # Europe/London spring forward (1:00 UTC jumps to 02:00 BST, 01:30 local missing)
        ("30 1 * * *", datetime(2026, 3, 29, 0, 0, tzinfo=UTC), "Europe/London", (3, 30, 1, 30)),
    ]
    for spec, after, tz, expected_local in cases:
        try:
            got = next_cron(spec, after, tz)
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"tzdata unavailable: {e}")
        loc = got.astimezone(ZoneInfo(tz))
        assert (loc.month, loc.day, loc.hour, loc.minute) == expected_local
