# Prototypes: five agents, one fusion

Everything under `prototypes/` is runnable source in the language of the repo it comes from.
Copy a file, change an import, and it belongs to that repo's tree.

| Folder | Language | Distils | Run it |
|---|---|---|---|
| `waku/waku_slice.py` | Python | ShenSeanChen/waku-agent | `python waku/waku_slice.py` |
| `hermes/bounded_memory.py` | Python | NousResearch/hermes-agent | `python hermes/bounded_memory.py` |
| `nanobot/dream_slice.py` | Python | HKUDS/nanobot | `python nanobot/dream_slice.py` |
| `openclaw/active-hours.ts` | TypeScript | openclaw/openclaw | `npx tsx openclaw/active-hours.ts` |
| `nanoclaw/guard.ts`, `circuit-breaker.ts` | TypeScript | qwibitai/nanoclaw | `npx tsx nanoclaw/guard.ts` |
| `fusion/waku_fusion/` | Python | all of the above | `cd fusion && python demo.py` |

The fusion is Python because the base, Waku, is Python and so are two of the three other
Python donors. The OpenClaw and NanoClaw ideas are ported to Python inside it, and the
original TypeScript stays beside them for TypeScript stacks.

```bash
cd prototypes/fusion
python -m pip install pytest      # the only dependency; the package itself is standard library
python -m pytest -q               # 35 deterministic evals, no API key
python demo.py                    # a day in the life, 12 scenes
python demo.py --json trace.json  # the trace the preview app replays
```

Python 3.11+, SQLite with FTS5 (bundled with CPython on every major platform), and `git` for the
audit trail. Without `git` the audit is a quiet no-op.

## Where each module goes in waku-agent

`waku_fusion/` mirrors `waku/` on purpose. Dropping a module in is a rename and an import fix.

| Fusion module | Replaces or joins in waku-agent | Idea from |
|---|---|---|
| `loop.py` | `waku/loop/agent.py` (adds exit 3: parked) | Waku, NanoClaw |
| `guard.py` | the `allow`/`ask` modes in `waku/alwayson/approvals.py` | NanoClaw |
| `memory/curated.py` | new, beside `waku/memory/semantic/` | Hermes |
| `memory/semantic.py` | `waku/memory/semantic/store.py` | Waku |
| `memory/gate.py` | `waku/memory/retrieval_gate.py` | Waku |
| `memory/dream.py` | `waku/memory/consolidation.py` | nanobot + Waku |
| `memory/audit.py` | new | nanobot, memU |
| `alwayson/events.py`, `outbox.py` | same names in `waku/alwayson/` | Waku |
| `alwayson/approvals.py` | `waku/alwayson/approvals.py` | Waku + NanoClaw |
| `alwayson/timers.py` | `waku/alwayson/timers.py` | Waku, nanobot, OpenClaw |
| `alwayson/breaker.py` | new, called from `waku/alwayson/serve.py` | NanoClaw |
| `tests/test_fusion.py` | `evals/deterministic/` | Waku |

## What was taken from each, and what was left

| Repo | Took | Left on purpose |
|---|---|---|
| **waku-agent** | the whole skeleton: 3-exit loop, gate that fails open, FTS5 memory, inbox/outbox with idempotency, parked approvals by hash, deterministic evals | LLM-as-judge tier, dashboard, hosted/, gateways: orthogonal to the fusion |
| **hermes-agent** | bounded `MEMORY.md`/`USER.md`, write-time threat scan, frozen prompt snapshot | the per-turn background review fork. Dream batching costs less and is easier to audit, so the fusion uses that. The fork is in `hermes/bounded_memory.py` if you want it. |
| **nanobot** | cursor that moves only on success, memory under git, schedule kinds | the full cron grammar (swap in `croniter`), AutoCompact session TTL |
| **openclaw** | active-hours window, defer-not-drop semantics | the 50-channel gateway, the Markdown memory notebook |
| **nanoclaw** | ALLOW/DENY/HOLD with the replay rule, command gate, startup breaker | per-agent container isolation. That is infrastructure, not a module. |
| **memU** | memory as a readable wiki (`wiki/facts.md`) so SQLite changes diff in git | hosted cross-device sync, skill distillation |

## Honest limits

- The model is scripted (`testing.ScriptedLLM`). The harness is real; model behaviour is not tested.
  Waku's own judge tier is the right place to test that, and it is not ported.
- The outbox decouples sending from running, so a reply can say "queued" while a retry is pending.
  That is the design, and the scripted replies say "queued" for that reason.
- `restates()` and `is_ops_state()` are Waku's heuristics, trimmed. They tune to English prose.
- The threat list in `curated.py` is a starter set. Hermes' `tools/threat_patterns.py` is the real list.
- Timers use `at`, `every`, and `daily [weekdays]`. That covers Waku's and most of nanobot's cases.

## Licensing

Waku, Hermes, nanobot, OpenClaw and NanoClaw are MIT. memU is Apache-2.0. The code here is
original, written from reading each repo, with upstream paths named in every docstring. No upstream
source file was copied.

Two things you must not carry over: the Waku name and mark (`LICENSE-BRAND` upstream: not MIT)
and waku-agent's `hosted/` directory (Elastic License 2.0: you can run it, you cannot resell it as a service).
