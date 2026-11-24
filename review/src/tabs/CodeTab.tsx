import { useState } from "react";
import { CodeView } from "../components/Code";
import { RepoChip, SectionTitle } from "../components/ui";
import { files, stats } from "../data/files";

export function CodeTab() {
  const [path, setPath] = useState("fusion/waku_fusion/guard.py");
  const file = files.find((f) => f.path === path) ?? files[0];
  const groups = ["README.md", "waku", "hermes", "nanobot", "openclaw", "nanoclaw", "fusion"];

  return (
    <div className="space-y-6">
      <SectionTitle eyebrow="05 / The code" title="Every file, in the language of the repo it came from">
        {files.length} files, {stats.lines.toLocaleString()} lines: {stats.pyFiles} Python and {stats.tsFiles} TypeScript. What you see is read from /prototypes at build time,
        so it is byte for byte what is on disk. Copy or download any file. Run the fusion with{" "}
        <code className="font-mono text-[12px] text-waku">cd prototypes/fusion &amp;&amp; python demo.py</code>.
      </SectionTitle>

      <div className="grid gap-4 lg:grid-cols-[290px_minmax(0,1fr)]">
        <nav className="scroll-thin space-y-4 rounded-lg border border-line bg-panel p-3 lg:max-h-[78vh] lg:overflow-auto">
          {groups.map((g) => {
            const list = g === "README.md" ? files.filter((f) => f.path === g) : files.filter((f) => f.path.startsWith(g + "/"));
            if (!list.length) return null;
            return (
              <div key={g}>
                <div className="mb-1.5 flex items-center gap-2">
                  {g === "README.md" ? <span className="font-mono text-[10px] uppercase tracking-widest text-mute">start here</span> : <RepoChip k={g as never} small />}
                </div>
                {list.map((f) => {
                  const label = g === "README.md" ? f.path : f.path.slice(g.length + 1);
                  const active = f.path === path;
                  return (
                    <button
                      key={f.path}
                      onClick={() => setPath(f.path)}
                      className="flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left font-mono text-[11.5px] transition hover:bg-panel2"
                      style={active ? { background: "var(--color-panel2)", color: "#fff" } : { color: "#9aa3b3" }}
                    >
                      <span className="truncate">{label}</span>
                      <span className="shrink-0 text-[10px] text-[#5b6577]">{f.lines}</span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </nav>
        <CodeView path={`prototypes/${file.path}`} code={file.code} lang={file.lang} maxHeight="78vh" />
      </div>
    </div>
  );
}
