import { useState } from "react";
import { Btn, Label, Panel, Pill } from "../ui";

// ---------------------------------------------------------------------------------------------
// OpenClaw: this is the same algorithm as prototypes/openclaw/active-hours.ts
// ---------------------------------------------------------------------------------------------

const toMin = (v: string) => Number(v.slice(0, 2)) * 60 + Number(v.slice(3));
const hhmm = (m: number) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

function localMinute(utcMinute: number, tz: string) {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(
    new Date(Date.UTC(2026, 2, 2, Math.floor(utcMinute / 60), utcMinute % 60)),
  );
  return Number(parts.find((p) => p.type === "hour")?.value) * 60 + Number(parts.find((p) => p.type === "minute")?.value);
}

export function OpenClawSim() {
  const [start, setStart] = useState("08:00");
  const [end, setEnd] = useState("20:00");
  const [tz, setTz] = useState("UTC");
  const [now, setNow] = useState(3 * 60);

  const minute = localMinute(now, tz);
  const s = toMin(start);
  const e = toMin(end);
  const within = s === e ? false : e > s ? minute >= s && minute < e : minute >= s || minute < e;
  const segs: [number, number][] = s === e ? [] : e > s ? [[s, e]] : [[s, 1440], [0, e]];

  const preset = (a: string, b: string) => {
    setStart(a);
    setEnd(b);
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <Label>window start</Label>
          <input type="time" value={start} onChange={(ev) => setStart(ev.target.value)} className="rounded-md border border-line bg-ink px-2 py-1.5 font-mono text-sm text-white" />
        </div>
        <div>
          <Label>window end</Label>
          <input type="time" value={end} onChange={(ev) => setEnd(ev.target.value)} className="rounded-md border border-line bg-ink px-2 py-1.5 font-mono text-sm text-white" />
        </div>
        <div>
          <Label>job timezone</Label>
          <select value={tz} onChange={(ev) => setTz(ev.target.value)} className="rounded-md border border-line bg-ink px-2 py-2 font-mono text-sm text-white">
            <option>UTC</option>
            <option>America/New_York</option>
            <option>Asia/Tokyo</option>
          </select>
        </div>
        <Btn onClick={() => preset("08:00", "20:00")}>daytime</Btn>
        <Btn onClick={() => preset("22:00", "06:00")}>overnight</Btn>
        <Btn onClick={() => preset("08:00", "08:00")}>start = end</Btn>
      </div>

      <div>
        <Label>
          24 hours in {tz} · now is {hhmm(minute)} here ({hhmm(now)} UTC)
        </Label>
        <div className="relative h-10 overflow-hidden rounded-md border border-line bg-panel2">
          {segs.map(([a, b], i) => (
            <div key={i} className="absolute inset-y-0" style={{ left: `${(a / 1440) * 100}%`, width: `${((b - a) / 1440) * 100}%`, background: "color-mix(in srgb, var(--color-openclaw) 28%, transparent)", borderLeft: "2px solid var(--color-openclaw)" }} />
          ))}
          <div className="absolute inset-y-0 w-0.5 bg-white" style={{ left: `${(minute / 1440) * 100}%` }} />
          {[0, 6, 12, 18].map((h) => (
            <span key={h} className="absolute bottom-0.5 font-mono text-[9px] text-mute" style={{ left: `calc(${(h / 24) * 100}% + 3px)` }}>
              {String(h).padStart(2, "0")}
            </span>
          ))}
        </div>
        <input type="range" min={0} max={1439} step={5} value={now} onChange={(ev) => setNow(Number(ev.target.value))} className="mt-3 w-full accent-[#f87171]" />
      </div>

      <Panel className="flex flex-wrap items-center gap-3 p-4">
        <Pill tone={within ? "ok" : "warn"}>{within ? "inside window" : "outside window"}</Pill>
        <span className="text-[14px] text-[#d5d9e2]">
          {s === e
            ? "start equals end is an empty window: the job never runs. 'Always' is spelled by leaving the window out."
            : within
              ? "A due job runs now and its output becomes the next run's scratch."
              : "A due job is deferred. It keeps its slot and runs on the first poll inside the window. Nothing is dropped."}
        </span>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// NanoClaw: the same rules as prototypes/nanoclaw/guard.ts and circuit-breaker.ts
// ---------------------------------------------------------------------------------------------

type Verdict = "allow" | "deny" | "hold";
const SCHEDULE = [0, 0, 10, 30, 120, 300, 900];

export function NanoClawSim() {
  const [to, setTo] = useState("sam");
  const [revoked, setRevoked] = useState(false);
  const [log, setLog] = useState<{ label: string; out: string; tone: "ok" | "bad" | "warn" | "info"; why: string }[]>([]);

  const decide = (dest: string): { v: Verdict; why: string } => {
    if (dest === "sam" && revoked) return { v: "deny", why: "sam was revoked" };
    return dest === "ana" ? { v: "allow", why: "reply to the requester" } : { v: "hold", why: "a message to someone else is a write" };
  };
  const call = (replay: boolean) => {
    const d = decide(to);
    let out = "";
    let tone: "ok" | "bad" | "warn" | "info" = "ok";
    if (d.v === "deny") { out = "denied"; tone = "bad"; }
    else if (d.v === "hold" && !replay) { out = "held: owner asked"; tone = "warn"; }
    else { out = "ran"; tone = "ok"; }
    setLog([{ label: `${replay ? "approved replay" : "fresh call"} → ${to}`, out, tone, why: d.why + (replay && d.v === "hold" ? " · grant satisfies the hold" : replay && d.v === "deny" ? " · a grant never upgrades a deny" : "") }, ...log].slice(0, 6));
  };

  const [attempt, setAttempt] = useState(0);
  const delay = attempt === 0 ? 0 : SCHEDULE[Math.min(attempt - 1, SCHEDULE.length - 1)];

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Panel className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-sm font-semibold text-white">The guard</h4>
          <Pill tone="info">guard.ts</Pill>
        </div>
        <Label>send_message to</Label>
        <div className="mb-3 flex flex-wrap gap-2">
          {["ana", "sam", "lee"].map((d) => (
            <Btn key={d} active={to === d} color="var(--color-nanoclaw)" onClick={() => setTo(d)}>
              {d}{d === "ana" ? " (requester)" : ""}
            </Btn>
          ))}
        </div>
        <label className="mb-3 flex items-center gap-2 text-[13px] text-mute">
          <input type="checkbox" checked={revoked} onChange={(e) => setRevoked(e.target.checked)} className="accent-[#38bdf8]" />
          sam was revoked after the call was parked
        </label>
        <div className="mb-3 flex gap-2">
          <Btn active color="var(--color-nanoclaw)" onClick={() => call(false)}>Fresh call</Btn>
          <Btn onClick={() => call(true)}>Approved replay</Btn>
          <Btn onClick={() => setLog([])}>Clear</Btn>
        </div>
        <div className="space-y-1.5">
          {log.length === 0 && <p className="text-sm text-mute">Try sam, then an approved replay, then revoke sam and replay again.</p>}
          {log.map((l, i) => (
            <div key={i} className="rise flex flex-wrap items-center gap-2 text-[12.5px]">
              <Pill tone={l.tone}>{l.out}</Pill>
              <span className="font-mono text-[#d5d9e2]">{l.label}</span>
              <span className="text-mute">{l.why}</span>
            </div>
          ))}
        </div>
      </Panel>

      <Panel className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-sm font-semibold text-white">The startup circuit breaker</h4>
          <Pill tone="info">circuit-breaker.ts</Pill>
        </div>
        <div className="mb-3 flex flex-wrap gap-2">
          <Btn active color="var(--color-nanoclaw)" onClick={() => setAttempt(attempt + 1)}>Crash and restart</Btn>
          <Btn onClick={() => setAttempt(0)}>An hour of quiet, or a clean stop</Btn>
        </div>
        <div className="flex items-end gap-1.5">
          {SCHEDULE.map((d, i) => {
            const on = attempt === i + 1 || (i === SCHEDULE.length - 1 && attempt > SCHEDULE.length);
            return (
              <div key={i} className="flex flex-1 flex-col items-center gap-1">
                <div className="w-full rounded-sm transition-all" style={{ height: `${6 + (Math.log(d + 1) / Math.log(901)) * 70}px`, background: on ? "var(--color-nanoclaw)" : attempt > i + 1 ? "#2a3a4a" : "#1c222b" }} />
                <span className="font-mono text-[10px] text-mute">{d}s</span>
              </div>
            );
          })}
        </div>
        <div className="mt-3 text-[13px] text-[#d5d9e2]">
          {attempt === 0 ? "Clean start. No wait." : <>Start <b>{attempt}</b>: wait <b className="text-nanoclaw">{delay}s</b> before touching anything{attempt > 7 ? " (capped at 900s)" : ""}.</>}
        </div>
        <p className="mt-2 text-[12px] leading-relaxed text-mute">
          A poison message that kills the worker is reclaimed on restart and kills it again. Without a breaker that loop runs as fast as the
          supervisor restarts it, calling the model each time.
        </p>
      </Panel>
    </div>
  );
}
