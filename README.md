# OpenAgent

OpenAgent is a local-first personal agent harness: a small, auditable core that combines
proven patterns from several open-source agent projects into one working codebase.

It is **not** a demo-only prototype. The core loop, memory, guard, always-on inbox/outbox,
approvals, timers, dream consolidation, and audit trail are implemented and covered by
deterministic tests.

## What it includes

- **3-exit agent loop** — model calls tools until it replies, hits the iteration limit (answers with tools off), or parks on a held approval.
- **ALLOW / DENY / HOLD guard** — every tool call is judged before execution; held calls require owner approval; replayed approvals never upgrade a DENY.
- **Curated memory** — bounded `MEMORY.md` / `USER.md`, write-time threat scan, frozen per-session prompt snapshot.
- **Semantic + episodic memory** — SQLite FTS5 (BM25), unicode-safe query builder, retrieval gate that fails open.
- **Dream consolidation** — cursor-based distillation with guards (drops ops state, restatements, duplicates), git-auditable memory directory, wiki export.
- **Always-on primitives** — event inbox with dedupe, outbox with idempotency/backoff/dead-letter, timers (`at/every/daily` + active-hours defer-not-drop), parked approvals, startup circuit breaker.
- **Provider adapters** — Anthropic Messages API and OpenAI Chat Completions (stdlib urllib, no required SDK). ScriptedLLM for offline/demo mode.
- **CLI** — `openagent chat`, `openagent ask`, `openagent demo`, `openagent dream`, `openagent info`.

## Quickstart

```bash
# From repo root, Python 3.11+
python -m pip install -e . --no-deps

# Run deterministic tests (no API key)
python -m pytest -q

# Run the scripted end-to-end demo
openagent demo
# or
python -m openagent demo

# Inspect config
openagent info
```

### Use a real model

```bash
# Anthropic
export ANTHROPIC_API_KEY=...
export OPENAGENT_PROVIDER=anthropic   # optional if key is set
export OPENAGENT_MODEL=claude-sonnet-4-5
openagent chat

# OpenAI
export OPENAI_API_KEY=...
export OPENAGENT_PROVIDER=openai
export OPENAGENT_MODEL=gpt-4o-mini
openagent chat

# One-shot
openagent ask "Remember that Alex prefers morning meetings."
openagent ask "Book a catch-up with Alex on Friday" --session work
```

### Configuration

| Env var | Default | Purpose |
|---|---|---|
| `OPENAGENT_HOME` | `~/.openagent` | State dir (`state.db`, memories, audit) |
| `OPENAGENT_PROVIDER` | inferred | `anthropic`, `openai`, or `scripted` |
| `OPENAGENT_MODEL` | provider default | Main model |
| `OPENAGENT_SMALL_MODEL` | same as model | Gate/dream model |
| `OPENAGENT_OWNER` | `local:owner` | Owner address for approvals |
| `OPENAGENT_MAX_ITERATIONS` | `10` | Loop iteration cap |
| `ANTHROPIC_API_KEY` | - | Anthropic API key |
| `OPENAI_API_KEY` | - | OpenAI API key |

## Project layout

```text
.
├── src/openagent/           # Main package
│   ├── agent.py             # Fusion.respond() orchestration
│   ├── cli.py               # CLI entrypoint
│   ├── config.py            # Env config
│   ├── db.py                # SQLite schema + helpers
│   ├── demo.py              # Scripted end-to-end demo
│   ├── guard.py             # ALLOW/DENY/HOLD + command gate
│   ├── llm.py               # Internal LLM dialect
│   ├── loop.py              # 3-exit agent loop
│   ├── testing.py           # ScriptedLLM for deterministic evals
│   ├── tools.py             # Tool registry + built-ins + rules
│   ├── trace.py             # Observer/trace
│   ├── alwayson/            # inbox, outbox, approvals, timers, breaker, worker
│   ├── memory/              # curated, semantic, gate, dream, audit
│   └── providers/           # Anthropic/OpenAI adapters
├── tests/                   # Deterministic pytest suite (35 tests)
├── examples/                # Demo script
├── prototypes/reference/    # Reference slices from studied repos (original languages)
├── review/                  # Review preview app + built artifact
├── docs/                    # Design/review notes
├── NOTICE.md                # Attribution and provenance
└── pyproject.toml
```

## Architecture

```text
User/event
  -> inbox event row (durable)
  -> retrieval gate (small model, fails open)
  -> semantic recall (FTS5) if needed
  -> frozen curated snapshot + recalled memory in system prompt
  -> agent loop
       -> LLM
       -> tool call -> guard (ALLOW/DENY/HOLD)
       -> tool result / parked approval
  -> chat log
  -> outbox row for reply (idempotent)
  -> dream consolidation when due (cursor, guards, git audit)
```

## Safety and guard model

- **Unknown tools are denied**.
- **Third-party sends are held** for owner approval; owner replies are allowed.
- **Approval replay rule**: a grant can satisfy a HOLD for the exact same call hash; it never upgrades a DENY.
- **Curated memory writes are scanned** for prompt-injection / secret / invisible-character patterns before writing.
- **Dream cursor moves only on success** so failed consolidation is retried, not skipped.

## Provenance / attribution

This codebase was built by studying and combining ideas from:

- [ShenSeanChen/waku-agent](https://github.com/ShenSeanChen/waku-agent) (MIT; note upstream `hosted/` is Elastic 2.0 and name/mark are not MIT)
- [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT)
- [HKUDS/nanobot](https://github.com/HKUDS/nanobot) (MIT)
- [openclaw/openclaw](https://github.com/openclaw/openclaw) (MIT)
- [qwibitai/nanoclaw](https://github.com/qwibitai/nanoclaw) (MIT)
- [NevaMind-AI/memU](https://github.com/NevaMind-AI/memU) (Apache-2.0)

Upstream names/paths are retained in docstrings for attribution. No Waku name/mark or
upstream `hosted/` ELv2 code is included. See [NOTICE.md](NOTICE.md).

## Review artifact

The original review/preview package is preserved under `review/`. The built preview is
`review/waku-fusion-review.html` (static report artifact).

## Development

```bash
python -m pip install -e ".[dev]" --break-system-packages  # or use a venv
python -m pytest -q
openagent demo
```

## License

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
