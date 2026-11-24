# Attribution and provenance

This project is an original implementation built by studying multiple open-source
agent projects and combining their best ideas. Upstream project names and paths are
kept in module docstrings for attribution.

## Upstream projects studied

| Project | License | What informed this work |
|---|---|---|
| [ShenSeanChen/waku-agent](https://github.com/ShenSeanChen/waku-agent) | MIT (note: `hosted/` is Elastic 2.0; name/mark not MIT) | 3-exit loop, retrieval gate, FTS5 memory, inbox/outbox idempotency, parked approvals, deterministic eval style |
| [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | MIT | Bounded curated memory, write-time threat scan, frozen prompt snapshot |
| [HKUDS/nanobot](https://github.com/HKUDS/nanobot) | MIT | Dream cursor semantics, git-audited memory, schedule kinds |
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | MIT | Active-hours window, defer-not-drop timer semantics |
| [qwibitai/nanoclaw](https://github.com/qwibitai/nanoclaw) | MIT | ALLOW/DENY/HOLD guard, replay rule, command gate, startup circuit breaker |
| [NevaMind-AI/memU](https://github.com/NevaMind-AI/memU) | Apache-2.0 | Wiki export idea for diffable memory |

## Constraints

- **No Waku name/mark** is carried over. Upstream naming appears only in attribution/provenance.
- **No `hosted/` ELv2 code** from waku-agent is included.
- No upstream source file was copied; modules were written from reading the referenced projects.
