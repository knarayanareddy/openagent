import type { ReactNode } from "react";
import type { RepoKey } from "../data/files";
import { colorOf, repoByKey } from "../data/repos";

export function RepoChip({ k, small }: { k: RepoKey; small?: boolean }) {
  const c = colorOf(k);
  const name = k === "fusion" ? "fusion" : (repoByKey(k)?.name ?? k);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-mono ${small ? "px-1.5 py-px text-[10px]" : "px-2 py-0.5 text-[11px]"}`}
      style={{ borderColor: `color-mix(in srgb, ${c} 45%, transparent)`, color: c, background: `color-mix(in srgb, ${c} 10%, transparent)` }}
    >
      <i className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: c }} />
      {name}
    </span>
  );
}

export function SectionTitle({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <div className="mb-6 max-w-3xl">
      <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-waku">{eyebrow}</div>
      <h2 className="text-2xl font-semibold leading-tight tracking-tight text-white sm:text-3xl">{title}</h2>
      {children && <p className="mt-3 text-[15px] leading-relaxed text-[#a9b1c0]">{children}</p>}
    </div>
  );
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-lg border border-line bg-panel ${className}`}>{children}</div>;
}

export function Label({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-mute">{children}</div>;
}

export function Btn({
  children,
  onClick,
  active,
  color,
  disabled,
}: {
  children: ReactNode;
  onClick?: () => void;
  active?: boolean;
  color?: string;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="rounded-md border px-3 py-1.5 text-[13px] font-medium transition disabled:cursor-not-allowed disabled:opacity-40"
      style={
        active
          ? { borderColor: color ?? "#f5a524", color: color ?? "#f5a524", background: `color-mix(in srgb, ${color ?? "#f5a524"} 12%, transparent)` }
          : { borderColor: "var(--color-line)", color: "#c9cfdb", background: "var(--color-panel2)" }
      }
    >
      {children}
    </button>
  );
}

export function Pill({ children, tone = "mute" }: { children: ReactNode; tone?: "ok" | "bad" | "warn" | "mute" | "info" }) {
  const map = {
    ok: ["#34d399", "#34d39918"],
    bad: ["#f87171", "#f8717118"],
    warn: ["#fbbf24", "#fbbf2418"],
    info: ["#38bdf8", "#38bdf818"],
    mute: ["#8a93a3", "#8a93a318"],
  }[tone];
  return (
    <span className="inline-block rounded px-1.5 py-0.5 font-mono text-[10.5px] font-medium" style={{ color: map[0], background: map[1] }}>
      {children}
    </span>
  );
}
