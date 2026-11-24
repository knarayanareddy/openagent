import type { RepoKey } from "./files";

export interface Repo {
  key: RepoKey;
  name: string;
  slug: string;
  color: string;
  lang: string;
  license: string;
  tagline: string;
  signature: string; // the one idea worth stealing
  took: string[];
  left: string[];
  /** Verified by reading or running the cloned repo, with how. */
  verified: string;
  size: string;
  entry: string; // default file shown in the Individual tab
  extra?: string[];
}

export const repos: Repo[] = [
  {
    key: "waku",
    name: "waku-agent",
    slug: "ShenSeanChen/waku-agent",
    color: "var(--color-waku)",
    lang: "Python",
    license: "MIT (hosted/ is Elastic 2.0; name and mark are not MIT)",
    tagline: "Local-first assistant that shows the five pillars: harness, loop, memory, eval, always-on.",
    signature:
      "Everything that must survive a crash is a row in one SQLite file, with idempotency enforced by UNIQUE constraints.",
    took: [
      "The 3-exit loop and the observer pattern",
      "A retrieval gate that fails open",
      "FTS5 memory and its unicode-safe query builder",
      "Inbox and outbox with UNIQUE idempotency",
      "Parked approvals, keyed by a SHA-256 of the call",
      "The deterministic eval tier",
    ],
    left: ["LLM-as-judge tier", "Dashboard, voice, hosted/", "Gateways beyond the event-source seam"],
    verified: "Cloned; read the loop, gate, memory, consolidation, inbox, outbox, approvals and schema; ran evals/deterministic: 2,363 passed, 6 sandbox failures, 62 skipped.",
    size: "18.5k lines in waku/ outside ops/ and plugins/",
    entry: "waku/waku_slice.py",
  },
  {
    key: "hermes",
    name: "hermes-agent",
    slug: "NousResearch/hermes-agent",
    color: "var(--color-hermes)",
    lang: "Python",
    license: "MIT",
    tagline: "Self-hosted agent that grows with you: curated memory, self-written skills, 20+ gateways.",
    signature:
      "Memory is two small files with a hard character budget, scanned on write and frozen for the session.",
    took: ["Bounded MEMORY.md and USER.md (§-delimited)", "Write-time injection scan", "Frozen prompt snapshot for cache stability"],
    left: ["Per-turn background review fork (see README for why)", "Seven terminal backends", "Importers"],
    verified: "Cloned; read tools/memory_tool.py, memory_tool_store.py, agent/background_review.py.",
    size: "Very large; the memory slice alone is a few hundred lines",
    entry: "hermes/bounded_memory.py",
  },
  {
    key: "nanobot",
    name: "nanobot",
    slug: "HKUDS/nanobot",
    color: "var(--color-nanobot)",
    lang: "Python (asyncio)",
    license: "MIT",
    tagline: "The 'ultra-lightweight OpenClaw': journal, dream, cron, many channels.",
    signature:
      "Memory consolidation is a scheduled pass over a journal with a cursor, and its diff is committed to git.",
    took: ["Cursor that advances only on success", "Memory directory under git", "Schedule kinds: at, every, cron"],
    left: ["Full cron grammar", "AutoCompact session TTL", "Channels"],
    verified: "Cloned; read agent/dream.py, memory.py, autocompact.py, cron/types.py.",
    size: "agent/loop.py alone is 2,671 lines today, so the 'about 4,000 lines' headline is out of date",
    entry: "nanobot/dream_slice.py",
  },
  {
    key: "openclaw",
    name: "OpenClaw",
    slug: "openclaw/openclaw",
    color: "var(--color-openclaw)",
    lang: "TypeScript",
    license: "MIT",
    tagline: "Gateway-first personal agent across WhatsApp, Telegram, Slack, Discord and more.",
    signature:
      "A scheduled job carries a wall-clock window, and 'outside the window' means defer, not fail.",
    took: ["Active-hours window, including overnight and DST", "Defer-not-drop semantics", "Monitor = ordinary job with scratch"],
    left: ["The channel gateway", "Markdown memory notebook"],
    verified: "Cloned; read src/cron/active-hours.ts, docs/gateway/heartbeat.md (HEARTBEAT.md is now retired).",
    size: "Largest of the set; the window logic is 40 lines",
    entry: "openclaw/active-hours.ts",
  },
  {
    key: "nanoclaw",
    name: "NanoClaw",
    slug: "qwibitai/nanoclaw",
    color: "var(--color-nanoclaw)",
    lang: "TypeScript",
    license: "MIT",
    tagline: "Container-per-agent isolation with approval cards and a credential vault.",
    signature:
      "One guard decides allow, deny or hold, and an approved replay can satisfy a hold but never a deny.",
    took: ["ALLOW/DENY/HOLD verdicts", "Replay rule", "Command gate", "Startup circuit breaker"],
    left: ["Container isolation (infrastructure, not a module)", "Credential vault"],
    verified: "Cloned; read src/guard/index.ts, delivery-guard.ts, command-gate.ts, circuit-breaker.ts.",
    size: "About 100k lines of non-test TypeScript",
    entry: "nanoclaw/guard.ts",
    extra: ["nanoclaw/circuit-breaker.ts"],
  },
  {
    key: "memu",
    name: "memU",
    slug: "NevaMind-AI/memU",
    color: "var(--color-memu)",
    lang: "Python",
    license: "Apache-2.0",
    tagline: "Personal memory stored as a wiki, shared across agents and devices.",
    signature: "Memory is a readable wiki, so you can diff it.",
    took: ["Wiki export of facts, so SQLite changes show up in git"],
    left: ["Hosted sync", "Skill distillation", "Host adapters"],
    verified: "Cloned; read README and layout. Only the wiki idea is used, so I did not audit its internals.",
    size: "About 20k lines",
    entry: "fusion/waku_fusion/memory/audit.py",
  },
];

export const repoByKey = (key: RepoKey) => repos.find((r) => r.key === key);
export const colorOf = (key: RepoKey) => (key === "fusion" ? "#e6e9ef" : (repoByKey(key)?.color ?? "#999"));
