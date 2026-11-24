import { Panel, Pill, SectionTitle } from "../components/ui";

const method = [
  ["Cloned", "ShenSeanChen/waku-agent at HEAD, plus the five repos it is compared against"],
  ["Read", "loop/agent.py, memory/{retrieval_gate,consolidation,semantic/store}.py, alwayson/{events,outbox,approvals,worker}.py, db.py, graph/engine.py, skills, docs/architecture.md and docs/roadmap.md"],
  ["Ran", "pip install -e '.[dev,eval]' then pytest evals/deterministic: 2,363 passed, 62 skipped (macOS-only), 6 failed"],
  ["Checked", "Every gap below was grepped for, then confirmed by reading the code around the hit"],
];

const pillars = [
  {
    name: "Harness",
    grade: "Strong",
    tone: "ok" as const,
    points: [
      "One dialect inside the loop (Anthropic content blocks). Each provider costs a ~60-line adapter in loop/models.py.",
      "Gateways (CLI, voice, Telegram, Discord, WhatsApp) all call the same respond().",
      "Terminal and browser tools are skeletons on purpose. The roadmap says so instead of over-promising.",
    ],
  },
  {
    name: "Loop",
    grade: "Strong",
    tone: "ok" as const,
    points: [
      "The README's '~95 lines' holds up: run_loop spans 110 lines with its docstring, 60 lines of code.",
      "Two exits. At max_iterations it makes one last call with tools off, so what the turn gathered is answered and not thrown away.",
      "A 4xx from a provider is never retried without streaming, because that doubles what a metered tenant pays to be told no.",
    ],
  },
  {
    name: "Memory",
    grade: "Strong, 3 gaps",
    tone: "warn" as const,
    points: [
      "The retrieval gate decides whether to read memory at all, and fails open.",
      "The FTS5 query builder is unusually careful: unicode61-compatible tokens, CJK handled, lowercased so 'Alex and Bob' is never a boolean expression.",
      "Consolidation guards come from dated incidents in the comments (2026-10-05 and 10-07): ops state is dropped, restated findings are dropped.",
      "Gaps: no write-time scan, no frozen snapshot, no audit trail (see findings).",
    ],
  },
  {
    name: "Eval / LLM-Ops",
    grade: "Strong",
    tone: "ok" as const,
    points: [
      "1,815 test functions across 155 files expand to 2,363 deterministic cases. They run offline with no key.",
      "Deterministic tier (0 or 1) beside an LLM-as-judge tier (a score), with a release gate.",
      "My 6 failures are all subprocess tests that cannot see my user-site install (ModuleNotFoundError: dotenv, anthropic). The sandbox caused them. They are not defects.",
    ],
  },
  {
    name: "Always-on",
    grade: "Strong, 3 gaps",
    tone: "warn" as const,
    points: [
      "Idempotency at three layers: UNIQUE(source, external_id) in, idempotency_key out, and a SHA-256 on parked calls.",
      "recover() returns claimed rows to pending, serve.lock allows one worker per home, the outbox backs off 10 / 60 / 600 / 3600 s and goes dead after 5.",
      "Gaps: replay is hash-checked but not re-judged, there is no crash-loop counter, and timers have no quiet hours.",
    ],
  },
];

const findings = [
  {
    sev: "Medium",
    tone: "warn" as const,
    title: "An approved call is replayed without re-running policy",
    body: "On a yes, worker._resolve checks approvals.intact(run), which is a hash-integrity test, then runs the call. approvals.mode() is not called again. If the destination was revoked between the question and the answer, the call still runs.",
    evidence: "waku/alwayson/worker.py:568, 587. No call to mode() in the file.",
    fix: "guard.py: HOLD becomes ALLOW only for the exact hash, and a DENY is never upgraded. (NanoClaw's runGuarded.)",
  },
  {
    sev: "Medium",
    tone: "warn" as const,
    title: "A message that kills the process is retried forever",
    body: "A Python exception marks the event failed. A hard death (OOM, SIGKILL, segfault) leaves it claimed, and startup returns every claimed row to pending. Nothing counts attempts on an event or slows restarts. I did not reproduce this, so it is a reading of the code.",
    evidence: "waku/alwayson/events.py recover(); grep for attempt|backoff|poison in worker.py, events.py, serve.py finds nothing.",
    fix: "alwayson/breaker.py: NanoClaw's startup backoff, 0 / 0 / 10 / 30 / 120 / 300 / 900 s, reset after an hour or a clean stop.",
  },
  {
    sev: "Medium",
    tone: "warn" as const,
    title: "Memory writes are not scanned",
    body: "Memory text goes into future prompts, so a poisoned entry persists across sessions. grep for threat|poison|exfil|inject under waku/memory returns zero matches.",
    evidence: "waku/memory/: 0 matches.",
    fix: "memory/curated.py: scan() runs on every write. (Hermes tools/threat_patterns.py.) The list here is a starter set.",
  },
  {
    sev: "Low",
    tone: "info" as const,
    title: "No small, stable, always-in-prompt profile",
    body: "All personal context goes through the gate. That is a defensible choice, but a few hundred characters (name, timezone, tone) pay for themselves on every turn, and a hard budget forces curation. There is also no frozen snapshot, so there is no cache-stability story.",
    evidence: "No prefix-cache or frozen-snapshot logic in waku/runtime, app.py or waku/memory.",
    fix: "CuratedMemory (2,200 and 1,375 character budgets) plus one snapshot per session.",
  },
  {
    sev: "Low",
    tone: "info" as const,
    title: "Memory is not diffable or revertable",
    body: "Facts live in SQLite. Consolidation can add a fact you did not want, and you cannot see last night's changes as a diff or undo them.",
    evidence: "No git or revert logic under waku/memory.",
    fix: "Dream commits the memory directory, and facts are mirrored to wiki/facts.md so a SQLite change becomes a git diff.",
  },
  {
    sev: "Low",
    tone: "info" as const,
    title: "Timers have timezones but no quiet hours",
    body: "waku/alwayson/timers.py resolves zones carefully, including TZ in containers, but a due timer always fires. A 03:00 job messages you at 03:00.",
    evidence: "No active-hours or window logic in timers.py.",
    fix: "ActiveHours from OpenClaw: outside the window a timer is deferred, not dropped.",
  },
];

export function ReviewTab() {
  return (
    <div className="space-y-12">
      <SectionTitle eyebrow="01 / End-to-end review" title="waku-agent: a codebase you can actually read, with six real gaps">
        I cloned it, read the core, and ran its offline test suite. The headline claims hold. The gaps are all in places Waku's sibling projects
        solved, which is what made the fusion worth building.
      </SectionTitle>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["18.5k", "lines in waku/ outside ops/ and plugins/"],
          ["2,363", "deterministic cases passing, offline"],
          ["110", "lines in run_loop, 60 of them code"],
          ["1", "SQLite file holds everything durable"],
        ].map(([n, l]) => (
          <Panel key={l} className="p-4">
            <div className="font-mono text-3xl font-semibold text-waku">{n}</div>
            <div className="mt-1 text-[13px] leading-snug text-mute">{l}</div>
          </Panel>
        ))}
      </div>

      <Panel className="divide-y divide-line">
        {method.map(([k, v]) => (
          <div key={k} className="grid gap-1 px-4 py-3 sm:grid-cols-[90px_1fr] sm:gap-4">
            <div className="font-mono text-[11px] uppercase tracking-widest text-waku">{k}</div>
            <div className="text-[14px] leading-relaxed text-[#c9cfdb]">{v}</div>
          </div>
        ))}
      </Panel>

      <div>
        <h3 className="mb-4 text-lg font-semibold text-white">The five pillars, graded on what the code does</h3>
        <div className="grid gap-4 lg:grid-cols-2">
          {pillars.map((p) => (
            <Panel key={p.name} className="p-5">
              <div className="mb-3 flex items-center justify-between">
                <h4 className="text-[15px] font-semibold text-white">{p.name}</h4>
                <Pill tone={p.tone}>{p.grade}</Pill>
              </div>
              <ul className="space-y-2">
                {p.points.map((pt) => (
                  <li key={pt} className="flex gap-2 text-[13.5px] leading-relaxed text-[#b9c1d0]">
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-waku" />
                    {pt}
                  </li>
                ))}
              </ul>
            </Panel>
          ))}
        </div>
      </div>

      <div>
        <h3 className="mb-1 text-lg font-semibold text-white">Findings</h3>
        <p className="mb-4 text-sm text-mute">Each one was grepped, then confirmed by reading the surrounding code. None is a bug in the sense of a crash. They are missing guarantees.</p>
        <div className="space-y-3">
          {findings.map((f, i) => (
            <Panel key={f.title} className="p-5">
              <div className="mb-2 flex flex-wrap items-center gap-3">
                <span className="font-mono text-xs text-mute">F{i + 1}</span>
                <Pill tone={f.tone}>{f.sev}</Pill>
                <h4 className="text-[15px] font-semibold text-white">{f.title}</h4>
              </div>
              <p className="text-[14px] leading-relaxed text-[#b9c1d0]">{f.body}</p>
              <div className="mt-3 grid gap-3 text-[12.5px] sm:grid-cols-2">
                <div className="rounded border border-line bg-ink/60 p-3">
                  <div className="mb-1 font-mono text-[10px] uppercase tracking-widest text-mute">Evidence</div>
                  <div className="font-mono text-[#c9cfdb]">{f.evidence}</div>
                </div>
                <div className="rounded border border-line bg-ink/60 p-3">
                  <div className="mb-1 font-mono text-[10px] uppercase tracking-widest text-waku">Fusion fix</div>
                  <div className="text-[#c9cfdb]">{f.fix}</div>
                </div>
              </div>
            </Panel>
          ))}
        </div>
      </div>

      <Panel className="p-5">
        <h4 className="mb-2 text-[15px] font-semibold text-white">What I did not check</h4>
        <p className="text-[14px] leading-relaxed text-[#b9c1d0]">
          I did not run Waku against a live model, so I cannot speak to answer quality. I did not review the hosted/ platform, the dashboard JavaScript, or the Docker eval tier.
          The six failing tests are environment problems I diagnosed to their cause but did not fix by building a proper venv.
        </p>
      </Panel>
    </div>
  );
}
