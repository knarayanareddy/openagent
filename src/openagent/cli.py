"""Command-line interface for OpenAgent."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import queue
import sqlite3
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from openagent import __version__
from openagent.agent import Fusion
from openagent.alwayson import events
from openagent.alwayson.worker import Worker
from openagent.config import Config
from openagent.senders import build_senders
from openagent.testing import ScriptedLLM


def _now() -> datetime:
    return datetime.now(UTC)


def build_llm(cfg: Config):
    if cfg.provider == "anthropic":
        from openagent.providers.anthropic import AnthropicProvider
        return AnthropicProvider(model=cfg.model)
    if cfg.provider == "openai":
        from openagent.providers.openai import OpenAIProvider
        return OpenAIProvider(model=cfg.model)
    return ScriptedLLM()


def build_small_llm(cfg: Config):
    if cfg.provider == "scripted":
        return ScriptedLLM()
    # reuse same provider type with small_model
    if cfg.provider == "anthropic":
        from openagent.providers.anthropic import AnthropicProvider
        return AnthropicProvider(model=cfg.small_model)
    if cfg.provider == "openai":
        from openagent.providers.openai import OpenAIProvider
        return OpenAIProvider(model=cfg.small_model)
    return ScriptedLLM()


def build_agent(cfg: Config, observer=None) -> Fusion:
    llm = build_llm(cfg)
    small = build_small_llm(cfg)
    return Fusion(cfg.home, llm, small, owner=cfg.owner, observer=observer or (lambda k, e=None: None),
                  max_iterations=cfg.max_iterations)


def cmd_info(args: argparse.Namespace) -> int:
    cfg = args.cfg
    print(f"openagent {__version__}")
    print(f"home:      {cfg.home}")
    print(f"provider:  {cfg.provider}")
    print(f"model:     {cfg.model}")
    print(f"small:     {cfg.small_model}")
    print(f"owner:     {cfg.owner}")
    if cfg.provider == "scripted":
        print("note:      no API key detected; using ScriptedLLM (rule-based demo mode)")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    cfg = args.cfg
    agent = build_agent(cfg)
    session = args.session
    reply_to = {"via": "cli", "chat_id": cfg.owner}
    turn = agent.respond(session, args.text, reply_to, _now())
    if args.json:
        print(json.dumps({
            "reply": turn.reply,
            "parked": turn.loop.parked,
            "iterations": turn.loop.iterations,
            "tool_calls": turn.loop.tool_calls,
            "recalled": turn.recalled,
            "dream": turn.dream.__dict__ if turn.dream else None,
        }, ensure_ascii=False, default=str))
    else:
        print(turn.reply or "(no reply - the run may be parked awaiting approval)")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    cfg = args.cfg
    if cfg.provider == "scripted":
        print("[openagent] No API key detected (ANTHROPIC_API_KEY / OPENAI_API_KEY).")
        print("[openagent] Running in scripted demo mode. Responses are rule-based.\n")
    agent = build_agent(cfg)
    session = args.session
    reply_to = {"via": "cli", "chat_id": cfg.owner}
    print(f"OpenAgent chat ({cfg.provider}:{cfg.model})  session={session}")
    print("Type /exit to quit, /new for a fresh session, /dream to force memory consolidation.\n")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text in ("/exit", "/quit"):
            break
        if text == "/new":
            agent.new_session(session)
            print("[session reset]\n")
            continue
        if text == "/dream":
            result = agent.run_dream(_now(), force=True)
            print(f"[dream] ran={result.ran} kept={len(result.kept)} dropped={len(result.dropped)} commit={result.commit} error={result.error}\n")
            continue
        turn = agent.respond(session, text, reply_to, _now())
        if turn.loop.parked:
            print("agent> [parked awaiting approval]\n")
        else:
            print(f"agent> {turn.reply}\n")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    # Run the bundled scripted demo
    from openagent.demo import main as demo_main
    demo_main()
    return 0


def cmd_dream(args: argparse.Namespace) -> int:
    cfg = args.cfg
    agent = build_agent(cfg)
    result = agent.run_dream(_now(), force=True)
    print(json.dumps({
        "ran": result.ran, "kept": result.kept, "dropped": result.dropped,
        "episode": result.episode, "commit": result.commit, "error": result.error,
    }, ensure_ascii=False, indent=2))
    return 0



class _RateLimiter:
    """Simple in-memory fixed-window rate limiter (best-effort, per process)."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = max(1, int(limit))
        self.window = float(window_seconds)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        ts = time.monotonic() if now is None else now
        cutoff = ts - self.window
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.limit:
                retry_after = max(1, int(self.window - (ts - q[0]) + 0.999))
                return False, retry_after
            q.append(ts)
            return True, 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the always-on worker loop with optional HTTP event ingress."""
    cfg = args.cfg
    agent = build_agent(cfg)
    senders = build_senders()
    inbox: "queue.Queue[dict]" = queue.Queue(maxsize=256)

    def drain_inbox() -> None:
        while True:
            try:
                msg = inbox.get_nowait()
            except queue.Empty:
                break
            events.insert(agent.conn, source=msg["source"], external_id=msg["external_id"],
                          session_id=msg["session_id"], payload=msg["payload"], now=_now())

    def wait_and_drain(seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)
        drain_inbox()

    worker = Worker(agent, senders, home=cfg.home, batch_wait=args.batch_wait, sleep=wait_and_drain)

    ingress_token = (args.token or os.environ.get("OPENAGENT_INGRESS_TOKEN", "")).strip()
    max_body = args.max_body
    allow_unauth = bool(getattr(args, "allow_unauthenticated", False))
    durable_ingress = bool(getattr(args, "durable_ingress", True))
    rate_limit = int(getattr(args, "rate_limit", 60))
    is_loopback = args.host in ("127.0.0.1", "localhost", "::1")
    if not is_loopback and not ingress_token and not allow_unauth:
        print("[openagent] ERROR: refusing non-loopback serve without ingress token. Set --token/OPENAGENT_INGRESS_TOKEN or pass --allow-unauthenticated (unsafe).", flush=True)
        return 2
    if not is_loopback and not ingress_token:
        print("[openagent] WARNING: non-loopback serve without OPENAGENT_INGRESS_TOKEN; /events is unauthenticated", flush=True)

    limiter = _RateLimiter(rate_limit)
    ingress_lock = threading.Lock()
    ingress_conn = sqlite3.connect(cfg.home / "state.db", check_same_thread=False)
    ingress_conn.row_factory = sqlite3.Row
    ingress_conn.execute("PRAGMA busy_timeout=5000")
    cors_origin = str(getattr(args, "cors_origin", "") or "").strip()
    audit_path = cfg.home / "logs" / "ingress.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_lock = threading.Lock()

    def audit(entry: dict) -> None:
        entry = {"ts": _now().isoformat(), **entry}
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with audit_lock:
            with audit_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def log_message(self, fmt, *a):  # quiet
            return

        def _cors_headers(self) -> dict[str, str]:
            if not cors_origin:
                return {}
            return {
                "access-control-allow-origin": cors_origin,
                "access-control-allow-methods": "GET,POST,OPTIONS",
                "access-control-allow-headers": "authorization,content-type",
                "access-control-max-age": "600",
                "vary": "Origin",
            }

        def _send(self, code: int, payload: dict, headers: dict[str, str] | None = None):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            for k, v in self._cors_headers().items():
                self.send_header(k, v)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):  # noqa: N802
            if not cors_origin:
                return self._send(404, {"error": "not found"})
            body = b""
            self.send_response(204)
            for k, v in self._cors_headers().items():
                self.send_header(k, v)
            self.send_header("content-length", "0")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                return self._send(200, {"ok": True, "provider": cfg.provider, "model": cfg.model})
            return self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/events":
                return self._send(404, {"error": "not found"})
            ip = self.client_address[0] if self.client_address else "unknown"
            ok, retry_after = limiter.allow(ip)
            if not ok:
                audit({"ip": ip, "path": self.path, "status": 429})
                return self._send(429, {"error": "rate limit exceeded"}, {"retry-after": str(retry_after)})
            if ingress_token:
                auth = self.headers.get("authorization", "")
                if not hmac.compare_digest(auth, f"Bearer {ingress_token}"):
                    audit({"ip": ip, "path": self.path, "status": 401})
                    return self._send(401, {"error": "unauthorized"})
            try:
                length = int(self.headers.get("content-length", "0") or 0)
            except ValueError:
                audit({"ip": ip, "path": self.path, "status": 400, "error": "invalid content-length"})
                return self._send(400, {"error": "invalid content-length"})
            if length <= 0 or length > max_body:
                audit({"ip": ip, "path": self.path, "status": 413, "length": length})
                return self._send(413, {"error": f"content-length must be 1..{max_body}"})
            try:
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception as exc:  # noqa: BLE001
                audit({"ip": ip, "path": self.path, "status": 400, "error": "invalid json"})
                return self._send(400, {"error": f"invalid json: {exc}"})
            text = str(payload.get("text", "")).strip()
            if not text:
                audit({"ip": ip, "path": self.path, "status": 400, "error": "text required"})
                return self._send(400, {"error": "text is required"})
            session_id = str(payload.get("session_id", "http:default"))
            # Namespace untrusted HTTP sessions to prevent owner spoofing when no token is configured.
            if not ingress_token and session_id == cfg.owner:
                session_id = f"http:{session_id}"
            msg = {
                "source": str(payload.get("source", "http")),
                "external_id": str(payload.get("external_id") or f"http-{uuid.uuid4().hex}"),
                "session_id": session_id,
                "payload": {
                    "text": text,
                    "reply_to": payload.get("reply_to") or {"via": "stdout", "chat_id": session_id},
                },
            }
            try:
                if durable_ingress:
                    with ingress_lock:
                        rowid = events.insert(ingress_conn, source=msg["source"], external_id=msg["external_id"],
                                              session_id=msg["session_id"], payload=msg["payload"], now=_now())
                    audit({"ip": ip, "path": self.path, "status": 202, "session_id": session_id, "external_id": msg["external_id"], "inserted": rowid is not None, "durable": True})
                    return self._send(202, {"queued": True, "durable": True, "external_id": msg["external_id"], "inserted": rowid is not None})
                inbox.put_nowait(msg)
            except queue.Full:
                audit({"ip": ip, "path": self.path, "status": 503, "error": "queue full"})
                return self._send(503, {"error": "inbox queue full"})
            except Exception as exc:  # noqa: BLE001
                audit({"ip": ip, "path": self.path, "status": 503, "error": str(exc)})
                return self._send(503, {"error": f"ingress unavailable: {exc}"})
            audit({"ip": ip, "path": self.path, "status": 202, "session_id": session_id, "external_id": msg["external_id"], "durable": False})
            return self._send(202, {"queued": True, "durable": False, "external_id": msg["external_id"]})

    httpd = None
    if not args.no_http:
        httpd = HTTPServer((args.host, args.port), Handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        print(f"[openagent] http ingress on http://{args.host}:{args.port}  POST /events  GET /health", flush=True)

    print(f"[openagent] serve loop started provider={cfg.provider} home={cfg.home}", flush=True)
    worker.start(_now())
    clean_shutdown = False
    try:
        while True:
            drain_inbox()
            result = worker.tick(_now())
            if result.handled != "idle":
                print(f"[openagent] handled={result.handled} session={result.session_id} parked={result.parked}", flush=True)
                continue  # drain/process pending work before sleeping
            threading.Event().wait(args.poll)
    except KeyboardInterrupt:
        clean_shutdown = True
        print("\n[openagent] stopping...", flush=True)
    finally:
        try:
            ingress_conn.close()
        except Exception:
            pass
        if clean_shutdown:
            worker.stop()  # reset breaker only on clean shutdown
        if httpd is not None:
            httpd.shutdown()
    return 0

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="openagent", description="OpenAgent - a personal agent harness")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--home", help="State directory (default: ~/.openagent or OPENAGENT_HOME)")
    p.add_argument("--provider", choices=["anthropic", "openai", "scripted"], help="LLM provider")
    p.add_argument("--model", help="Model name")
    p.add_argument("--small-model", help="Small model for gate/dream")
    p.add_argument("--owner", help="Owner address (default: local:owner)")
    p.add_argument("--max-iterations", type=int, default=None)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("info", help="Show resolved configuration")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("ask", help="Send one message and print the reply")
    s.add_argument("text", help="Message text")
    s.add_argument("--session", default="cli")
    s.add_argument("--json", action="store_true", help="Emit JSON")
    s.set_defaults(func=cmd_ask)

    s = sub.add_parser("chat", help="Interactive chat REPL")
    s.add_argument("--session", default="cli")
    s.set_defaults(func=cmd_chat)

    s = sub.add_parser("dream", help="Force a memory consolidation pass")
    s.set_defaults(func=cmd_dream)

    s = sub.add_parser("demo", help="Run the scripted end-to-end demo")
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help="Run always-on worker loop with optional HTTP ingress")
    s.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    s.add_argument("--port", type=int, default=8787, help="HTTP bind port")
    s.add_argument("--poll", type=float, default=2.0, help="Worker poll interval seconds")
    s.add_argument("--batch-wait", type=float, default=0.2, help="Batch wait seconds for same-session events")
    s.add_argument("--token", default="", help="Ingress bearer token (or OPENAGENT_INGRESS_TOKEN)")
    s.add_argument("--max-body", type=int, default=65536, help="Max HTTP request body bytes")
    s.add_argument("--rate-limit", type=int, default=60, help="Max /events requests per IP per minute")
    s.add_argument("--cors-origin", default="", help="Optional CORS allow-origin for browser clients")
    s.add_argument("--allow-unauthenticated", action="store_true", help="Allow non-loopback HTTP ingress without token (unsafe)")
    s.add_argument("--no-durable-ingress", dest="durable_ingress", action="store_false", help="Queue events in memory before ack (less durable)")
    s.set_defaults(durable_ingress=True)
    s.add_argument("--no-http", action="store_true", help="Disable HTTP ingress")
    s.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    # CLI overrides
    if args.home:
        cfg.home = Path(args.home).expanduser()
    if args.provider:
        cfg.provider = args.provider
    if args.model:
        cfg.model = args.model
    if getattr(args, "small_model", None):
        cfg.small_model = args.small_model
    if args.owner:
        cfg.owner = args.owner
    if args.max_iterations is not None:
        cfg.max_iterations = args.max_iterations
    args.cfg = cfg
    return args.func(args)
