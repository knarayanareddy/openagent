import { useState } from "react";
import { Btn, Label, Panel, Pill } from "../ui";

// A browser mirror of prototypes/waku/waku_slice.py. Same rules, same order.

interface Step {
  stage: "inbox" | "gate" | "recall" | "loop" | "outbox";
  text: string;
  tone: "ok" | "bad" | "warn" | "info" | "mute";
  tag: string;
}

const words = (q: string) => [...new Set((q.toLowerCase().match(/[\p{L}\p{N}]{2,}/gu) ?? []))];
const hash = (s: string) => {
  let h = 0xcbf29ce4;
  for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 0x01000193) >>> 0;
  return h.toString(16).padStart(8, "0") + "9d3b";
};

const PRESETS = ["Book a catch-up with Alex on Friday", "what is 2+2", "message Sam I'm running late"];
const SEED = ["Alex prefers morning meetings.", "Priya owns the Acme demo."];

export function WakuSim() {
  const [text, setText] = useState(PRESETS[0]);
  const [twice, setTwice] = useState(false);
  const [seen, setSeen] = useState<string[]>([]);
  const [outbox, setOutbox] = useState<string[]>([]);
  const [parked, setParked] = useState<{ tool: string; sha: string }[]>([]);
  const [steps, setSteps] = useState<Step[]>([]);
  const [n, setN] = useState(0);

  const send = () => {
    const out: Step[] = [];
    const id = `u${n + 1}`;
    setN(n + 1);
    out.push({ stage: "inbox", tag: "stored", tone: "ok", text: `INSERT OR IGNORE INTO events (telegram, ${id}) -> row written before any model call` });
    if (twice) out.push({ stage: "inbox", tag: "dropped", tone: "warn", text: `second delivery of ${id}: UNIQUE(source, external_id) -> 0 rows, a no-op` });

    const retrieve = /alex|meeting|remember|book/i.test(text);
    out.push({
      stage: "gate",
      tag: retrieve ? "retrieve" : "skip",
      tone: retrieve ? "info" : "mute",
      text: retrieve ? "small model: this message references the user's life -> search memory" : "small model: self-contained, memory would only bias the answer -> skip",
    });
    let recalled: string[] = [];
    if (retrieve) {
      const w = words(text);
      recalled = SEED.filter((f) => w.some((x) => f.toLowerCase().includes(x)));
      out.push({ stage: "recall", tag: `${recalled.length} hit`, tone: recalled.length ? "ok" : "mute", text: recalled.length ? recalled.join(" | ") : "FTS5 MATCH returned nothing" });
    }

    let reply = "OK.";
    const lower = text.toLowerCase();
    let newParked = parked;
    if (lower.includes("book")) {
      const morning = recalled.some((r) => r.includes("morning"));
      out.push({ stage: "loop", tag: "iteration 1", tone: "info", text: `model asks for create_event(time=${morning ? "09:00" : "14:00"})${morning ? "  <- chosen because memory said mornings" : ""}` });
      out.push({ stage: "loop", tag: "iteration 2", tone: "ok", text: "no tool call -> exit 1: the model is talking to the human" });
      reply = `Done. booked Catch-up with Alex at ${morning ? "09:00" : "14:00"}`;
    } else if (lower.startsWith("message sam")) {
      const args = { to: "sam", body: "running late" };
      const sha = hash(JSON.stringify(["send_message", args]));
      out.push({ stage: "loop", tag: "iteration 1", tone: "warn", text: `model asks for send_message(to=sam). Mode is 'ask': park it, do not run it.` });
      out.push({ stage: "loop", tag: "parked", tone: "warn", text: `stored with sha256 ${sha.slice(0, 10)}…  the run ends, the owner is asked` });
      reply = `Waiting for your yes to run send_message. (${sha.slice(0, 10)})`;
      newParked = [...parked, { tool: "send_message", sha: sha.slice(0, 10) }];
    } else {
      out.push({ stage: "loop", tag: "iteration 1", tone: "ok", text: "no tool call -> exit 1" });
    }
    setParked(newParked);

    const key = `reply:${id}`;
    const dupKey = outbox.includes(key);
    out.push({ stage: "outbox", tag: dupKey ? "dropped" : "queued", tone: dupKey ? "warn" : "ok", text: `idempotency_key ${key} -> "${reply}"` });
    setOutbox(dupKey ? outbox : [...outbox, key]);
    setSeen([...seen, id]);
    setSteps(out);
  };

  const reset = () => {
    setSeen([]);
    setOutbox([]);
    setParked([]);
    setSteps([]);
    setN(0);
  };

  const stageColor = { inbox: "#f5a524", gate: "#a78bfa", recall: "#2dd4bf", loop: "#38bdf8", outbox: "#34d399" } as const;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div className="space-y-4">
        <div>
          <Label>Send a Telegram message</Label>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <Btn key={p} active={text === p} onClick={() => setText(p)} color="var(--color-waku)">
                {p}
              </Btn>
            ))}
          </div>
          <div className="mt-2 flex gap-2">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              className="min-w-0 flex-1 rounded-md border border-line bg-ink px-3 py-2 font-mono text-[13px] text-white outline-none focus:border-waku"
            />
            <Btn onClick={send} active color="var(--color-waku)">
              Send
            </Btn>
          </div>
          <label className="mt-2 flex items-center gap-2 text-[13px] text-mute">
            <input type="checkbox" checked={twice} onChange={(e) => setTwice(e.target.checked)} className="accent-[#f5a524]" />
            Telegram delivers it twice (the timeout-and-resend case)
          </label>
        </div>

        <Panel className="min-h-[220px] p-3">
          <Label>What the harness did</Label>
          {steps.length === 0 && <p className="py-8 text-center text-sm text-mute">Send a message to watch the pipeline.</p>}
          <ol className="space-y-1.5">
            {steps.map((s, i) => (
              <li key={i} className="rise flex items-start gap-2.5 text-[13px]" style={{ animationDelay: `${i * 60}ms` }}>
                <span className="mt-0.5 w-14 shrink-0 font-mono text-[10px] uppercase tracking-wider" style={{ color: stageColor[s.stage] }}>
                  {s.stage}
                </span>
                <Pill tone={s.tone}>{s.tag}</Pill>
                <span className="min-w-0 break-words text-[#c9cfdb]">{s.text}</span>
              </li>
            ))}
          </ol>
        </Panel>
      </div>

      <div className="space-y-3">
        <Panel className="p-3">
          <Label>sqlite: facts</Label>
          {SEED.map((f) => (
            <div key={f} className="font-mono text-[11px] leading-relaxed text-[#b9c1d0]">
              {f}
            </div>
          ))}
        </Panel>
        <Panel className="p-3">
          <Label>events ({seen.length}) / outbox ({outbox.length})</Label>
          <div className="font-mono text-[11px] text-[#b9c1d0]">
            {seen.length === 0 ? <span className="text-mute">empty</span> : seen.map((s) => <div key={s}>{s} · done</div>)}
          </div>
        </Panel>
        <Panel className="p-3">
          <Label>parked ({parked.length})</Label>
          <div className="font-mono text-[11px] text-[#b9c1d0]">
            {parked.length === 0 ? <span className="text-mute">none</span> : parked.map((p, i) => <div key={i}>{p.tool} · {p.sha}…</div>)}
          </div>
        </Panel>
        <Btn onClick={reset}>Reset</Btn>
      </div>
    </div>
  );
}
