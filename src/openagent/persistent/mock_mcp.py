"""A tiny MCP server (JSON-RPC over HTTP) for tests and the demo. Stdlib only.

Tools:
  calendar_free_busy   readOnlyHint=true    -> ALLOW through the guard
  calendar_send_invite readOnlyHint=false   -> HOLD for the owner's yes
  crm_note             (no annotations)     -> HOLD (unknown means not read-only)

`state["slots"]` maps a person to their free slots, so a test can change the world between
heartbeats. `sse=True` answers as text/event-stream, as many hosted MCP servers do.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = [
    {"name": "calendar_free_busy", "description": "Look up when a person has free calendar slots.",
     "inputSchema": {"type": "object", "properties": {"who": {"type": "string"}}, "required": ["who"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "calendar_send_invite", "description": "Send a calendar invitation to a person.",
     "inputSchema": {"type": "object", "properties": {"who": {"type": "string"}, "when": {"type": "string"}},
                     "required": ["who", "when"]},
     "annotations": {"readOnlyHint": False}},
    {"name": "crm_note", "description": "Write a note on a contact in the CRM.",
     "inputSchema": {"type": "object", "properties": {"who": {"type": "string"}, "note": {"type": "string"}}}},
]


class MockMcp:
    def __init__(self, *, sse: bool = False, token: str = "") -> None:
        self.state: dict = {"slots": {}}
        self.calls: list[dict] = []          # every tools/call that actually reached the server
        self.sse, self.token = sse, token
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a: object) -> None:  # silence
                return

            def do_POST(self) -> None:  # noqa: N802
                if outer.token and self.headers.get("Authorization") != f"Bearer {outer.token}":
                    self.send_response(401)
                    self.end_headers()
                    return
                msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                method, mid = msg.get("method"), msg.get("id")
                if mid is None:                                  # a notification
                    self.send_response(202)
                    self.end_headers()
                    return
                result: dict = {}
                if method == "initialize":
                    result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "mock-tools", "version": "0.1"}}
                elif method == "tools/list":
                    result = {"tools": TOOLS}
                elif method == "tools/call":
                    p = msg["params"]
                    outer.calls.append(p)
                    who = p.get("arguments", {}).get("who", "")
                    if p["name"] == "calendar_free_busy":
                        slots = outer.state["slots"].get(who, [])
                        text = f"{who} free: {', '.join(slots)}" if slots else f"{who} has no free slots this week"
                    else:
                        text = f"done: {p['name']} {json.dumps(p.get('arguments', {}))}"
                    result = {"content": [{"type": "text", "text": text}]}
                else:
                    body = json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown method"}})
                    self._send(body)
                    return
                self._send(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}))

            def _send(self, body: str) -> None:
                self.send_response(200)
                self.send_header("Mcp-Session-Id", "mock-session-1")
                if outer.sse:
                    body = f"event: message\ndata: {body}\n\n"
                    self.send_header("Content-Type", "text/event-stream")
                else:
                    self.send_header("Content-Type", "application/json")
                data = body.encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/mcp"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> MockMcp:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
