// Every prototype file is imported as raw text, so what the preview shows is byte for byte
// what is on disk under /prototypes. There is no second copy to drift.
import runs from "./runs.json";
import trace from "./fusion-trace.json";

const raw = import.meta.glob("/prototypes/**/*.{py,ts,md}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

export type RepoKey = "waku" | "hermes" | "nanobot" | "openclaw" | "nanoclaw" | "memu" | "fusion";
export type Lang = "python" | "typescript" | "markdown";

export interface ProtoFile {
  path: string; // relative to /prototypes
  lang: Lang;
  repo: RepoKey;
  code: string;
  lines: number;
}

const langOf = (p: string): Lang => (p.endsWith(".py") ? "python" : p.endsWith(".ts") ? "typescript" : "markdown");
const repoOf = (p: string): RepoKey => {
  const top = p.split("/")[0];
  return (["waku", "hermes", "nanobot", "openclaw", "nanoclaw", "fusion"].includes(top) ? top : "fusion") as RepoKey;
};

export const files: ProtoFile[] = Object.entries(raw)
  .map(([full, code]) => {
    const path = full.replace("/prototypes/", "");
    return { path, lang: langOf(path), repo: repoOf(path), code, lines: code.split("\n").length };
  })
  .sort((a, b) => {
    const rank = (f: ProtoFile) => (f.path === "README.md" ? 0 : f.repo === "fusion" ? 2 : 1);
    return rank(a) - rank(b) || a.path.localeCompare(b.path);
  });

export const fileByPath = (path: string) => files.find((f) => f.path === path);

export const realOutputs = runs.outputs as Record<string, string>;
export const fusionTests = runs.fusion_tests as string[];

export interface TraceEvent {
  kind: string;
  lane: "alwayson" | "loop" | "guard" | "memory";
  title: string;
  detail: Record<string, unknown>;
}
export interface SceneState {
  clock: string;
  user_md: string[];
  memory_md: string[];
  usage: { user: string; memory: string };
  facts: string[];
  events: { id: number; source: string; session: string; status: string; text: string }[];
  outbox: { id: number; to: string; body: string; status: string; attempts: number }[];
  parked: { tool: string; args: Record<string, unknown>; sha256: string }[];
  calendar: string[];
  timers: { kind: string; spec: string; next: string; window: string }[];
  delivered: { to: string; body: string }[];
  git: string[];
}
export interface Scene {
  id: string;
  title: string;
  blurb: string;
  events: TraceEvent[];
  state: SceneState;
}
export const scenes = (trace as { scenes: Scene[] }).scenes;

export const stats = {
  pyFiles: files.filter((f) => f.lang === "python").length,
  tsFiles: files.filter((f) => f.lang === "typescript").length,
  lines: files.filter((f) => f.lang !== "markdown").reduce((n, f) => n + f.lines, 0),
};
