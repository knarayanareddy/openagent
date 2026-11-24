"""Command-line interface for OpenAgent."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from openagent import __version__
from openagent.agent import Fusion
from openagent.config import Config
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
