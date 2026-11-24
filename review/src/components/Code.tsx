import { useMemo, useState } from "react";
import hljs from "highlight.js/lib/core";
import python from "highlight.js/lib/languages/python";
import typescript from "highlight.js/lib/languages/typescript";
import markdown from "highlight.js/lib/languages/markdown";
import type { Lang } from "../data/files";

hljs.registerLanguage("python", python);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("markdown", markdown);

const LANG_LABEL: Record<Lang, string> = { python: "Python", typescript: "TypeScript", markdown: "Markdown" };

export function LangBadge({ lang }: { lang: Lang }) {
  const dot = lang === "python" ? "#4b8bbe" : lang === "typescript" ? "#3178c6" : "#8a93a3";
  return (
    <span className="inline-flex items-center gap-1.5 rounded border border-line px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-mute">
      <i className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: dot }} />
      {LANG_LABEL[lang]}
    </span>
  );
}

export function CodeView({
  path,
  code,
  lang,
  maxHeight = "70vh",
}: {
  path: string;
  code: string;
  lang: Lang;
  maxHeight?: string;
}) {
  const [copied, setCopied] = useState(false);
  const html = useMemo(() => hljs.highlight(code, { language: lang }).value, [code, lang]);
  const lineCount = code.split("\n").length;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      const t = document.createElement("textarea");
      t.value = code;
      document.body.appendChild(t);
      t.select();
      document.execCommand("copy");
      t.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };

  const download = () => {
    const url = URL.createObjectURL(new Blob([code], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = path.split("/").pop() ?? "file.txt";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-panel">
      <div className="flex items-center justify-between gap-3 border-b border-line bg-panel2 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <LangBadge lang={lang} />
          <span className="truncate font-mono text-xs text-[#c9cfdb]">{path}</span>
          <span className="hidden font-mono text-[10px] text-mute sm:inline">{lineCount} lines</span>
        </div>
        <div className="flex shrink-0 gap-1.5">
          <button
            onClick={copy}
            className="rounded border border-line px-2 py-1 font-mono text-[11px] text-mute transition hover:border-[#3a4150] hover:text-white"
          >
            {copied ? "copied" : "copy"}
          </button>
          <button
            onClick={download}
            className="rounded border border-line px-2 py-1 font-mono text-[11px] text-mute transition hover:border-[#3a4150] hover:text-white"
          >
            download
          </button>
        </div>
      </div>
      <div className="scroll-thin overflow-auto" style={{ maxHeight }}>
        <pre className="m-0 flex font-mono text-[12px] leading-[1.6]">
          <code className="select-none border-r border-line px-3 py-3 text-right text-[#4b5363]" aria-hidden>
            {Array.from({ length: lineCount }, (_, i) => i + 1).join("\n")}
          </code>
          <code className="hljs block flex-1 whitespace-pre px-4 py-3" dangerouslySetInnerHTML={{ __html: html }} />
        </pre>
      </div>
    </div>
  );
}

export function Terminal({ title, text }: { title: string; text: string }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-[#07090c]">
      <div className="flex items-center gap-2 border-b border-line px-3 py-1.5">
        <span className="h-2 w-2 rounded-full bg-[#3a4150]" />
        <span className="h-2 w-2 rounded-full bg-[#3a4150]" />
        <span className="h-2 w-2 rounded-full bg-[#3a4150]" />
        <span className="ml-2 font-mono text-[11px] text-mute">{title}</span>
      </div>
      <pre className="scroll-thin m-0 max-h-72 overflow-auto px-4 py-3 font-mono text-[11.5px] leading-relaxed text-[#b7f0c0]">
        {text}
      </pre>
    </div>
  );
}
