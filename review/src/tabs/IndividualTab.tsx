import { useState } from "react";
import type { ReactNode } from "react";
import { CodeView, Terminal } from "../components/Code";
import { WakuSim } from "../components/sims/WakuSim";
import { HermesSim, NanobotSim } from "../components/sims/MemorySims";
import { NanoClawSim, OpenClawSim } from "../components/sims/TsSims";
import { Panel, RepoChip, SectionTitle } from "../components/ui";
import { fileByPath, realOutputs } from "../data/files";
import type { RepoKey } from "../data/files";
import { repos } from "../data/repos";

const SIMS: Partial<Record<RepoKey, ReactNode>> = {
  waku: <WakuSim />,
  hermes: <HermesSim />,
  nanobot: <NanobotSim />,
  openclaw: <OpenClawSim />,
  nanoclaw: <NanoClawSim />,
};

const SHOWN = repos.filter((r) => r.key !== "memu");

export function IndividualTab() {
  const [key, setKey] = useState<RepoKey>("waku");
  const repo = SHOWN.find((r) => r.key === key)!;
  const paths = [repo.entry, ...(repo.extra ?? [])];
  const [pathIdx, setPathIdx] = useState(0);
  const path = paths[Math.min(pathIdx, paths.length - 1)];
  const file = fileByPath(path);

  return (
    <div className="space-y-6">
      <SectionTitle eyebrow="03 / Each project, alone" title="Five prototypes, one per repo, in that repo's language">
        Each slice runs on its own and shows only that project's signature mechanism. Click the simulator, then read the file it mirrors. The terminal
        beneath is the real output of running that file.
      </SectionTitle>

      <div className="flex flex-wrap gap-2">
        {SHOWN.map((r) => (
          <button
            key={r.key}
            onClick={() => {
              setKey(r.key);
              setPathIdx(0);
            }}
            className="rounded-lg border px-3.5 py-2 text-left transition"
            style={
              key === r.key
                ? { borderColor: r.color, background: `color-mix(in srgb, ${r.color} 10%, transparent)` }
                : { borderColor: "var(--color-line)", background: "var(--color-panel)" }
            }
          >
            <div className="text-[13px] font-semibold" style={{ color: key === r.key ? r.color : "#e6e9ef" }}>
              {r.name}
            </div>
            <div className="font-mono text-[10px] text-mute">{r.lang}</div>
          </button>
        ))}
      </div>

      <Panel className="p-5" key={repo.key}>
        <div className="mb-1 flex flex-wrap items-center gap-3">
          <RepoChip k={repo.key} />
          <span className="font-mono text-[11px] text-mute">{path}</span>
        </div>
        <p className="mb-5 mt-2 max-w-3xl text-[15px] font-medium leading-snug text-white">{repo.signature}</p>
        {SIMS[repo.key]}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div>
          {paths.length > 1 && (
            <div className="mb-2 flex gap-2">
              {paths.map((p, i) => (
                <button
                  key={p}
                  onClick={() => setPathIdx(i)}
                  className="rounded border px-2.5 py-1 font-mono text-[11px]"
                  style={i === pathIdx ? { borderColor: repo.color, color: repo.color } : { borderColor: "var(--color-line)", color: "var(--color-mute)" }}
                >
                  {p.split("/")[1]}
                </button>
              ))}
            </div>
          )}
          {file && <CodeView path={`prototypes/${file.path}`} code={file.code} lang={file.lang} maxHeight="560px" />}
        </div>
        <div className="space-y-3">
          <div className="font-mono text-[10px] uppercase tracking-widest text-mute">
            real output of {file?.lang === "python" ? "python" : "npx tsx"} {path.split("/")[1]}
          </div>
          <Terminal title={`$ ${file?.lang === "python" ? "python" : "npx tsx"} ${path}`} text={realOutputs[path] ?? ""} />
          <Panel className="p-4">
            <div className="mb-2 font-mono text-[10px] uppercase tracking-widest" style={{ color: repo.color }}>
              What to adapt
            </div>
            <ul className="space-y-1.5">
              {repo.took.map((t) => (
                <li key={t} className="flex gap-2 text-[13px] text-[#c9cfdb]">
                  <span style={{ color: repo.color }}>→</span>
                  {t}
                </li>
              ))}
            </ul>
            <div className="mt-3 border-t border-line pt-3 font-mono text-[11px] text-mute">upstream: github.com/{repo.slug}</div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
