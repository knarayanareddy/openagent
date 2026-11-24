import { useEffect, useState } from "react";
import { CodeTab } from "./tabs/CodeTab";
import { FusionTab } from "./tabs/FusionTab";
import { IndividualTab } from "./tabs/IndividualTab";
import { LandscapeTab } from "./tabs/LandscapeTab";
import { ReviewTab } from "./tabs/ReviewTab";
import { RepoChip } from "./components/ui";
import { fusionTests, scenes, stats } from "./data/files";
import type { RepoKey } from "./data/files";

const TABS = [
  ["review", "Review"],
  ["landscape", "Landscape"],
  ["individual", "Each alone"],
  ["fusion", "Combined"],
  ["code", "Code"],
] as const;
type Tab = (typeof TABS)[number][0];

const fromHash = (): Tab => {
  const h = window.location.hash.replace("#", "");
  return (TABS.find(([k]) => k === h)?.[0] ?? "review") as Tab;
};

export default function App() {
  const [tab, setTab] = useState<Tab>(fromHash);

  useEffect(() => {
    const on = () => setTab(fromHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const go = (t: Tab) => {
    window.location.hash = t;
    setTab(t);
    window.scrollTo({ top: 0 });
  };

  return (
    <div className="min-h-screen">
      <header className="relative overflow-hidden border-b border-line">
        <div
          className="pointer-events-none absolute inset-0 opacity-60"
          style={{
            background:
              "radial-gradient(900px 300px at 85% -10%, color-mix(in srgb, var(--color-waku) 16%, transparent), transparent), radial-gradient(700px 260px at 0% 0%, color-mix(in srgb, var(--color-hermes) 10%, transparent), transparent)",
          }}
        />
        <div className="relative mx-auto max-w-[1280px] px-5 pb-7 pt-9 sm:px-8">
          <div className="mb-4 flex flex-wrap items-center gap-1.5">
            {(["waku", "hermes", "nanobot", "openclaw", "nanoclaw", "memu"] as RepoKey[]).map((k) => (
              <RepoChip key={k} k={k} small />
            ))}
          </div>
          <h1 className="max-w-4xl text-3xl font-semibold leading-[1.1] tracking-tight text-white sm:text-5xl">
            Waku, reviewed.
            <br />
            <span className="text-waku">Then fused with five neighbours.</span>
          </h1>
          <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-[#a9b1c0]">
            An end-to-end review of ShenSeanChen/waku-agent, a look at five comparable repos, and one working prototype that keeps Waku's skeleton and adds the
            guarantees it lacked. Every file is in the language of its source repo, ready to adapt.
          </p>
          <div className="mt-6 flex flex-wrap gap-x-8 gap-y-2 font-mono text-[12px] text-mute">
            <span><b className="text-white">{stats.pyFiles}</b> Python files</span>
            <span><b className="text-white">{stats.tsFiles}</b> TypeScript files</span>
            <span><b className="text-white">{stats.lines.toLocaleString()}</b> lines</span>
            <span><b className="text-[#34d399]">{fusionTests.length}</b> evals passing</span>
            <span><b className="text-white">{scenes.length}</b> recorded scenes</span>
          </div>
        </div>
        <nav className="relative mx-auto flex max-w-[1280px] gap-1 overflow-x-auto px-5 sm:px-8">
          {TABS.map(([k, label], i) => (
            <button
              key={k}
              onClick={() => go(k)}
              className="whitespace-nowrap border-b-2 px-4 py-3 text-[13.5px] font-medium transition"
              style={tab === k ? { borderColor: "var(--color-waku)", color: "#fff" } : { borderColor: "transparent", color: "#8a93a3" }}
            >
              <span className="mr-2 font-mono text-[10px] text-[#5b6577]">0{i + 1}</span>
              {label}
            </button>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-[1280px] px-5 py-10 sm:px-8">
        {tab === "review" && <ReviewTab />}
        {tab === "landscape" && <LandscapeTab />}
        {tab === "individual" && <IndividualTab />}
        {tab === "fusion" && <FusionTab />}
        {tab === "code" && <CodeTab />}
      </main>

      <footer className="border-t border-line px-5 py-8 text-center font-mono text-[11px] text-mute sm:px-8">
        Prototype code is original, written from reading each repo. Upstream paths are named in every docstring. waku-agent, hermes-agent, nanobot, OpenClaw and NanoClaw are MIT. memU is Apache-2.0.
        The Waku name and mark are not MIT.
      </footer>
    </div>
  );
}
