from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_health(url: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.1)
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


def test_serve_http_auth_and_durable(tmp_path: Path):
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["OPENAGENT_HOME"] = str(tmp_path / "home")
    env["OPENAGENT_PROVIDER"] = "scripted"
    cmd = [sys.executable, "-m", "openagent", "serve", "--host", "127.0.0.1", "--port", str(port),
           "--poll", "0.1", "--batch-wait", "0", "--token", "secret", "--rate-limit", "100"]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        health = _wait_health(f"http://127.0.0.1:{port}/health")
        assert health["ok"] is True

        code, _ = _post(f"http://127.0.0.1:{port}/events", {"text": "hello"})
        assert code == 401
        code, _ = _post(f"http://127.0.0.1:{port}/events", {"text": "hello"}, token="wrong")
        assert code == 401
        code, _ = _post(f"http://127.0.0.1:{port}/events", {"text": ""}, token="secret")
        assert code == 400

        code, data = _post(f"http://127.0.0.1:{port}/events", {"text": "hello", "session_id": "s1"}, token="secret")
        assert code == 202 and data["queued"] is True and data["durable"] is True

        import sqlite3
        db = tmp_path / "home" / "state.db"
        for _ in range(50):
            if db.exists():
                conn = sqlite3.connect(db)
                rows = conn.execute("SELECT source, session_id, status FROM events ORDER BY id").fetchall()
                conn.close()
                if rows:
                    break
            time.sleep(0.1)
        assert rows[0][0] == "http"
        assert rows[0][1] == "s1"
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def test_serve_http_rate_limit(tmp_path: Path):
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["OPENAGENT_HOME"] = str(tmp_path / "home")
    env["OPENAGENT_PROVIDER"] = "scripted"
    cmd = [sys.executable, "-m", "openagent", "serve", "--host", "127.0.0.1", "--port", str(port),
           "--poll", "0.1", "--batch-wait", "0", "--token", "secret", "--rate-limit", "2"]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        _wait_health(f"http://127.0.0.1:{port}/health")
        c1, _ = _post(f"http://127.0.0.1:{port}/events", {"text": "a"}, token="secret")
        c2, _ = _post(f"http://127.0.0.1:{port}/events", {"text": "b"}, token="secret")
        c3, d3 = _post(f"http://127.0.0.1:{port}/events", {"text": "c"}, token="secret")
        assert c1 == 202 and c2 == 202
        assert c3 == 429
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def _options(url: str, origin: str = "http://localhost:3000"):
    req = urllib.request.Request(url, headers={"origin": origin}, method="OPTIONS")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, dict(r.headers.items())


def test_serve_http_cors_audit_and_payload_limit(tmp_path: Path):
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["OPENAGENT_HOME"] = str(tmp_path / "home")
    env["OPENAGENT_PROVIDER"] = "scripted"
    cmd = [sys.executable, "-m", "openagent", "serve", "--host", "127.0.0.1", "--port", str(port),
           "--poll", "0.1", "--batch-wait", "0", "--token", "secret", "--max-body", "64",
           "--cors-origin", "http://localhost:3000"]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        _wait_health(f"http://127.0.0.1:{port}/health")
        status, headers = _options(f"http://127.0.0.1:{port}/events")
        assert status == 204
        assert headers.get("access-control-allow-origin") == "http://localhost:3000"

        code, _ = _post(f"http://127.0.0.1:{port}/events", {"text": "x" * 200}, token="secret")
        assert code == 413

        code, _ = _post(f"http://127.0.0.1:{port}/events", {"text": "ok"}, token="secret")
        assert code == 202
        audit = tmp_path / "home" / "logs" / "ingress.jsonl"
        for _ in range(30):
            if audit.exists() and audit.read_text().strip():
                break
            time.sleep(0.1)
        assert audit.exists()
        lines = [json.loads(l) for l in audit.read_text().splitlines() if l.strip()]
        assert any(l.get("status") == 413 for l in lines)
        assert any(l.get("status") == 202 for l in lines)
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def test_serve_http_concurrent_clients(tmp_path: Path):
    import threading
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["OPENAGENT_HOME"] = str(tmp_path / "home")
    env["OPENAGENT_PROVIDER"] = "scripted"
    cmd = [sys.executable, "-m", "openagent", "serve", "--host", "127.0.0.1", "--port", str(port),
           "--poll", "0.1", "--batch-wait", "0", "--token", "secret", "--rate-limit", "100"]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    results = []
    try:
        _wait_health(f"http://127.0.0.1:{port}/health")
        def hit(i):
            code, _ = _post(f"http://127.0.0.1:{port}/events", {"text": f"hi {i}", "session_id": f"s{i}"}, token="secret")
            results.append(code)
        threads = [threading.Thread(target=hit, args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=10)
        assert len(results) == 8
        assert all(c == 202 for c in results)
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
