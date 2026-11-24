import { useEffect, useMemo, useRef, useState } from "react";
import { Btn, Label, Panel, Pill, RepoChip, SectionTitle } from "../components/ui";
import { fusionTests, scenes, stats } from "../data/files";
import type { RepoKey, Scene } from "../data/files";
import { colorOf } from "../data/repos";

// Who contributed the behaviour behind each kind of trace event.
const DONOR: Record<string, RepoKey> = {
  inbox: "waku", dedupe: "waku", claim: "waku", recover: "waku", outbox: "waku", sent: "waku", retry: "waku", dead: "waku",
  llm: "waku", tool: "waku", reply: "waku", limit: "waku", gate: "waku", recall: "waku", dropped: "waku", approval: "waku",
  timer: "waku", defer: "openclaw", breaker: "nanoclaw", guard: "nanoclaw", command: "nanoclaw",
  snapshot: "hermes", curated: "hermes", dream: "nanobot", audit: "memu",
};

const LAYERS: { title: string; blurb: string; items: { name: string; file: string; from: RepoKey; note: string }[] }[] = [
  {
    title: "Always-on shell",
    blurb: "What happens around a run",
    items: [
      { name: "circuit breaker", file: "alwayson/breaker.py", from: "nanoclaw", note: "slows a crash loop: 0, 0, 10, 30, 120, 300, 900 s" },
      { name: "timers", file: "alwayson/timers.py", from: "waku", note: "at / every / daily, as events" },
      { name: "active hours", file: "alwayson/timers.py", from: "openclaw", note: "outside the window: defer, never drop" },
      { name: "inbox", file: "alwayson/events.py", from: "waku", note: "UNIQUE(source, external_id), claim, recover" },
      { name: "outbox", file: "alwayson/outbox.py", from: "waku", note: "idempotency key, 10/60/600/3600 s backoff" },
    ],
  },
  {
    title: "One run",
    blurb: "Rebuilt every turn",
    items: [
      { name: "command gate", file: "guard.py", from: "nanoclaw", note: "pass, filter, deny before the model" },
      { name: "frozen snapshot", file: "agent.py", from: "hermes", note: "curated memory read once per session" },
      { name: "retrieval gate", file: "memory/gate.py", from: "waku", note: "does this turn need memory? fails open" },
      { name: "loop", file: "loop.py", from: "waku", note: "3 exits: no tool call, step limit, parked" },
      { name: "guard", file: "guard.py", from: "nanoclaw", note: "ALLOW / DENY / HOLD, unknown tools denied" },
      { name: "approvals", file: "alwayson/approvals.py", from: "waku", note: "SHA-256 park, replay re-judged by the guard" },
    ],
  },
  {
    title: "Memory",
    blurb: "Four tiers, one directory plus one SQLite file",
    items: [
      { name: "curated", file: "memory/curated.py", from: "hermes", note: "MEMORY.md / USER.md, budgeted, scanned" },
      { name: "semantic + episodic", file: "memory/semantic.py", from: "waku", note: "FTS5 BM25, unicode-safe queries" },
      { name: "dream", file: "memory/dream.py", from: "nanobot", note: "cursor moves only on success; Waku's guards" },
      { name: "audit + wiki", file: "memory/audit.py", from: "memu", note: "facts.md mirror, git commit per night" },
    ],
  },
];

const GAPS: [string, RepoKey, string, string][] = [
  ["Write-time memory scan", "hermes", "none under waku/memory (0 grep hits)", "curated.scan on every write"],
  ["Budgeted always-on profile + frozen snapshot", "hermes", "no snapshot or cache logic found", "CuratedMemory + one snapshot per session"],
  ["Diffable, revertable memory", "memu", "no git or revert logic under waku/memory", "wiki/facts.md + a commit per dream"],
  ["Cursor that waits for success", "nanobot", "per-row consolidated flag; failure path not verified", "dream_cursor moves after the call succeeds"],
  ["Quiet hours on timers", "openclaw", "timezone-aware, no window", "within_active_hours: defer, never drop"],
  ["Crash-loop breaker", "nanoclaw", "recover() only; no attempt counter on events", "breaker.enforce_startup_backoff"],
  ["Replay re-judged by policy", "nanoclaw", "_resolve checks the hash, never calls mode() again", "Guard.decide(grant): a grant never upgrades a DENY"],
  ["Three-way verdict, fail-closed on unknown tools", "nanoclaw", "per-tool allow/ask modes", "ALLOW / DENY / HOLD"],
];

function Detail({ d }: { d: Record<string, unknown> }) {
  const rows = Object.entries(d).filter(([, v]) => v !== "" && v != null && !(Array.isArray(v) && v.length === 0));
  if (!rows.length) return null;
  return (
    <div className="mt-1 space-y-0.5 pl-1">
      {rows.map(([k, v]) => (
        <div key={k} className="flex gap-2 font-mono text-[11px] leading-snug">
          <span className="w-16 shrink-0 text-mute">{k}</span>
          <span className="min-w-0 break-words text-[#aeb6c5]">{typeof v === "string" ? v : JSON.stringify(v)}</span>
        </div>
      ))}
    </div>
  );
}

function StatePanel({ s }: { s: Scene["state"] }) {
  const box = "rounded border border-line bg-ink/50 p-2.5";
  return (
    <div className="space-y-3 text-[12px]">
      <div className="font-mono text-[10px] text-mute">state after this scene · clock {s.clock} UTC</div>
      <div className={box}>
        <Label>USER.md · {s.usage.user} chars</Label>
        {s.user_md.length ? s.user_md.map((e) => <div key={e} className="font-mono text-hermes">§ {e}</div>) : <span className="text-mute">empty</span>}
      </div>
      <div className={box}>
        <Label>facts (sqlite + wiki)</Label>
        {s.facts.length ? s.facts.map((e) => <div key={e} className="font-mono text-[#c9cfdb]">{e}</div>) : <span className="text-mute">empty</span>}
      </div>
      <div className={box}>
        <Label>git log</Label>
        {s.git.length ? s.git.map((e) => <div key={e} className="font-mono text-nanobot">{e}</div>) : <span className="text-mute">no commits yet</span>}
      </div>
      <div className={box}>
        <Label>events</Label>
        {s.events.length ? (
          s.events.map((e) => (
            <div key={e.id} className="flex gap-2 font-mono">
              <span className="text-mute">#{e.id}</span>
              <Pill tone={e.status === "done" ? "ok" : e.status === "failed" ? "bad" : "warn"}>{e.status}</Pill>
              <span className="truncate text-[#aeb6c5]">{e.source}</span>
            </div>
          ))
        ) : (
          <span className="text-mute">empty</span>
        )}
      </div>
      <div className={box}>
        <Label>outbox</Label>
        {s.outbox.length ? (
          s.outbox.map((o) => (
            <div key={o.id} className="flex flex-wrap gap-x-2 font-mono">
              <Pill tone={o.status === "sent" ? "ok" : o.status === "dead" ? "bad" : "warn"}>{o.status}</Pill>
              <span className="text-[#aeb6c5]">{o.to}</span>
              <span className="text-mute">×{o.attempts}</span>
            </div>
          ))
        ) : (
          <span className="text-mute">empty</span>
        )}
      </div>
      {(s.parked.length > 0 || s.calendar.length > 0 || s.timers.length > 0) && (
        <div className={box}>
          {s.parked.map((p, i) => (
            <div key={i} className="font-mono text-openclaw">parked {p.tool} · {p.sha256}…</div>
          ))}
          {s.calendar.map((c) => (
            <div key={c} className="font-mono text-[#c9cfdb]">calendar: {c}</div>
          ))}
          {s.timers.map((t, i) => (
            <div key={i} className="font-mono text-[#aeb6c5]">timer {t.kind} {t.spec} · {t.window}</div>
          ))}
        </div>
      )}
    </div>
  );
}

export function FusionTab() {
  const [idx, setIdx] = useState(0);
  const scene = scenes[idx];
  const [shown, setShown] = useState(scene.events.length);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<number | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    setShown(scenes[idx].events.length);
    setPlaying(false);
  }, [idx]);

  useEffect(() => {
    if (!playing) return;
    timer.current = window.setInterval(() => {
      setShown((n) => {
        if (n >= scene.events.length) {
          setPlaying(false);
          return n;
        }
        return n + 1;
      });
    }, 260);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [playing, scene]);

  const replay = () => {
    setShown(0);
    setPlaying(true);
  };

  const visibleTests = useMemo(() => fusionTests.filter((t) => t.includes(filter.toLowerCase().replace(/ /g, "_"))), [filter]);
  const total = scenes.reduce((n, s) => n + s.events.length, 0);

  return (
    <div className="space-y-14">
      <div>
        <SectionTitle eyebrow="04 / The combination" title="One loop, five borrowed guarantees">
          The fusion keeps Waku's skeleton and bolts on only what Waku was missing. Every box below is a real module with a named donor.{" "}
          {stats.pyFiles} Python files, {fusionTests.length} deterministic tests, nothing but the standard library.
        </SectionTitle>
        <div className="grid gap-4 lg:grid-cols-3">
          {LAYERS.map((layer) => (
            <Panel key={layer.title} className="p-4">
              <div className="mb-3">
                <div className="text-[15px] font-semibold text-white">{layer.title}</div>
                <div className="text-[12px] text-mute">{layer.blurb}</div>
              </div>
              <div className="space-y-2">
                {layer.items.map((it) => (
                  <div key={it.name} className="rounded-md border-l-2 bg-panel2 px-3 py-2" style={{ borderColor: colorOf(it.from) }}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-medium text-white">{it.name}</span>
                      <RepoChip k={it.from} small />
                    </div>
                    <div className="text-[12px] leading-snug text-mute">{it.note}</div>
                    <div className="mt-0.5 font-mono text-[10px] text-[#5b6577]">{it.file}</div>
                  </div>
                ))}
              </div>
            </Panel>
          ))}
        </div>
      </div>

      <div>
        <h3 className="mb-1 text-lg font-semibold text-white">Alone versus combined</h3>
        <p className="mb-4 max-w-3xl text-sm text-mute">
          The left column is what I verified in waku-agent, by grep and by reading. Everything on the right is a module you can run and test.
        </p>
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-[13px]">
            <thead>
              <tr className="border-b border-line font-mono text-[10px] uppercase tracking-widest text-mute">
                <th className="px-4 py-2.5">Capability</th>
                <th className="px-4 py-2.5">From</th>
                <th className="px-4 py-2.5">waku-agent alone</th>
                <th className="px-4 py-2.5">Fusion</th>
              </tr>
            </thead>
            <tbody>
              {GAPS.map(([cap, from, alone, fused]) => (
                <tr key={cap} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-2.5 font-medium text-white">{cap}</td>
                  <td className="px-4 py-2.5"><RepoChip k={from} small /></td>
                  <td className="px-4 py-2.5 text-mute">{alone}</td>
                  <td className="px-4 py-2.5 text-[#c9cfdb]">{fused}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      <div>
        <h3 className="mb-1 text-lg font-semibold text-white">A day in the life: 12 scenes, {total} real trace events</h3>
        <p className="mb-4 max-w-3xl text-sm text-mute">
          This is the recorded output of <code className="font-mono text-[12px] text-waku">python demo.py</code>. The worker, inbox, outbox, guard, memory, timers, breaker and git audit are the real
          modules. Only the model and the two messaging senders are stand-ins. Each event carries the colour of the repo whose idea produced that behaviour.
        </p>
        <div className="grid gap-4 lg:grid-cols-[230px_minmax(0,1fr)_300px]">
          <div className="space-y-1.5 lg:max-h-[640px] lg:overflow-auto">
            {scenes.map((s, i) => (
              <button
                key={s.id}
                onClick={() => setIdx(i)}
                className="flex w-full items-start gap-2.5 rounded-md border px-3 py-2 text-left transition"
                style={i === idx ? { borderColor: "var(--color-waku)", background: "color-mix(in srgb, var(--color-waku) 9%, transparent)" } : { borderColor: "var(--color-line)", background: "var(--color-panel)" }}
              >
                <span className="mt-px font-mono text-[11px] text-mute">{String(i + 1).padStart(2, "0")}</span>
                <span className="text-[12.5px] leading-snug" style={{ color: i === idx ? "#fff" : "#b9c1d0" }}>{s.title}</span>
              </button>
            ))}
          </div>

          <Panel className="p-4">
            <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-[15px] font-semibold text-white">{scene.title}</h4>
              <div className="flex gap-2">
                <Btn onClick={replay} active={playing} color="var(--color-waku)">{playing ? "playing…" : "Replay"}</Btn>
                <Btn onClick={() => { setPlaying(false); setShown(scene.events.length); }}>Show all</Btn>
              </div>
            </div>
            <p className="mb-4 text-[13px] leading-relaxed text-[#a9b1c0]">{scene.blurb}</p>
            <div className="space-y-1">
              {scene.events.length === 0 && <p className="text-sm text-mute">No events in this scene.</p>}
              {scene.events.slice(0, shown).map((e, i) => {
                const donor = DONOR[e.kind] ?? "waku";
                return (
                  <div key={i} className="rise rounded-md border border-line/70 bg-panel2/60 px-3 py-1.5" style={{ borderLeft: `3px solid ${colorOf(donor)}` }}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="w-16 shrink-0 font-mono text-[10px] uppercase tracking-wider" style={{ color: colorOf(donor) }}>{e.kind}</span>
                      <span className="text-[13px] text-[#e2e6ee]">{e.title}</span>
                    </div>
                    <Detail d={e.detail} />
                  </div>
                );
              })}
            </div>
            <div className="mt-4 flex flex-wrap gap-1.5 border-t border-line pt-3">
              {(["waku", "hermes", "nanobot", "openclaw", "nanoclaw", "memu"] as RepoKey[]).map((k) => (
                <RepoChip key={k} k={k} small />
              ))}
            </div>
          </Panel>

          <Panel className="p-3 lg:max-h-[780px] lg:overflow-auto"><StatePanel s={scene.state} /></Panel>
        </div>

        {scenes[scenes.length - 1].state.delivered.length > 0 && (
          <Panel className="mt-4 p-4">
            <Label>every message delivered by the end of the day ({scenes[scenes.length - 1].state.delivered.length})</Label>
            <div className="grid gap-x-6 gap-y-1 md:grid-cols-2">
              {scenes[scenes.length - 1].state.delivered.map((d, i) => (
                <div key={i} className="flex gap-2 font-mono text-[11.5px]">
                  <span className="shrink-0 text-nanoclaw">{d.to}</span>
                  <span className="min-w-0 truncate text-[#b9c1d0]" title={d.body}>{d.body}</span>
                </div>
              ))}
            </div>
          </Panel>
        )}
      </div>

      <div>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold text-white">{fusionTests.length} deterministic evals, all passing</h3>
            <p className="text-sm text-mute">Waku's own style: 0 or 1, no judge, no API key. One test per borrowed idea, named for the property it protects.</p>
          </div>
          <input
            placeholder="filter: guard, dream, outbox…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-56 rounded-md border border-line bg-ink px-3 py-1.5 font-mono text-[12px] text-white outline-none focus:border-waku"
          />
        </div>
        <Panel className="grid gap-x-8 gap-y-1 p-4 md:grid-cols-2">
          {visibleTests.map((t) => (
            <div key={t} className="flex gap-2 font-mono text-[11.5px] text-[#b9c1d0]">
              <span className="text-[#34d399]">✓</span>
              {t.replace(/^test_/, "").replace(/_/g, " ")}
            </div>
          ))}
          {visibleTests.length === 0 && <span className="text-sm text-mute">No test matches.</span>}
        </Panel>
      </div>
    </div>
  );
}
