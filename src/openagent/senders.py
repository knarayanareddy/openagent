"""Outbound senders for the always-on outbox.

Provenance: sender/address shape follows waku/alwayson/senders/ and dispatcher.py.
These are small stdlib adapters; real deployments can replace them.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable

Sender = Callable[[dict, str], None]


def stdout_sender(target: dict, body: str) -> None:
    ident = target.get("chat_id") or target.get("channel") or target.get("id") or "default"
    print(f"[send stdout:{ident}] {body}", flush=True)


def make_webhook_sender(url: str | None = None, timeout: float = 10.0) -> Sender:
    endpoint = url or os.environ.get("OPENAGENT_WEBHOOK_URL", "")

    def send(target: dict, body: str) -> None:
        if not endpoint:
            raise RuntimeError("OPENAGENT_WEBHOOK_URL is not set")
        payload = json.dumps({"target": target, "body": body}).encode("utf-8")
        req = urllib.request.Request(endpoint, data=payload, headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    return send


def make_telegram_sender(token: str | None = None, timeout: float = 10.0) -> Sender:
    bot_token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")

    def send(target: dict, body: str) -> None:
        if not bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
        chat_id = target.get("chat_id")
        if chat_id is None:
            raise ValueError(f"telegram target missing chat_id: {target!r}")
        api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = json.dumps({"chat_id": chat_id, "text": body}).encode("utf-8")
        req = urllib.request.Request(api, data=payload, headers={"content-type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram API {e.code}: {detail[:300]}") from e
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data}")
    return send


def build_senders() -> dict[str, Sender]:
    """Default sender map. Telegram is enabled when TELEGRAM_BOT_TOKEN is set."""
    senders: dict[str, Sender] = {"stdout": stdout_sender, "cli": stdout_sender, "local": stdout_sender}
    if os.environ.get("OPENAGENT_WEBHOOK_URL"):
        senders["webhook"] = make_webhook_sender()
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        senders["telegram"] = make_telegram_sender()
    return senders
