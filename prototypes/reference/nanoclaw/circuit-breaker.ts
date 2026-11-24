/**
 * NanoClaw's startup circuit breaker, distilled: a crash-looping process slows itself down.
 *
 * Upstream: github.com/qwibitai/nanoclaw  src/circuit-breaker.ts (MIT)
 *
 * If this process starts soon after a start that never shut down cleanly, it waits before doing
 * anything, and waits longer each time. A clean shutdown, or an hour of quiet, resets it.
 *
 *   crashes:   1   2   3   4    5    6+
 *   delay s:   0   0  10  30  120  300 -> 900 (capped)
 *
 * Why it matters for an always-on agent: a poison message that kills the worker is reclaimed on
 * restart and kills it again. Without a breaker that loop runs as fast as the supervisor restarts
 * it, and every iteration calls the model provider.
 *
 * Run:  npx tsx circuit-breaker.ts
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const RESET_WINDOW_MS = 60 * 60 * 1000;
export const BACKOFF_SCHEDULE_S = [0, 0, 10, 30, 120, 300, 900];

interface State {
  attempt: number;
  timestamp: string;
}

export function getDelay(attempt: number): number {
  return BACKOFF_SCHEDULE_S[Math.min(attempt - 1, BACKOFF_SCHEDULE_S.length - 1)];
}

function read(file: string): State | null {
  try {
    return JSON.parse(fs.readFileSync(file, "utf-8")) as State;
  } catch {
    return null; // missing or corrupt state is the same as a clean start
  }
}

export function resetCircuitBreaker(file: string): void {
  fs.rmSync(file, { force: true });
}

export async function enforceStartupBackoff(
  file: string,
  now: Date = new Date(),
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
): Promise<{ attempt: number; delaySec: number }> {
  const previous = read(file);
  const recent = previous !== null && now.getTime() - new Date(previous.timestamp).getTime() < RESET_WINDOW_MS;
  const attempt = recent && previous ? previous.attempt + 1 : 1;

  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ attempt, timestamp: now.toISOString() }, null, 2) + "\n");

  const delaySec = getDelay(attempt);
  if (delaySec > 0) await sleep(delaySec * 1000);
  return { attempt, delaySec };
}

// ---- demo --------------------------------------------------------------------------------------------

const isMain = typeof process !== "undefined" && process.argv[1]?.endsWith("circuit-breaker.ts");
if (isMain) {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "breaker-")), "circuit-breaker.json");
  const slept: number[] = [];
  const fakeSleep = async (ms: number) => void slept.push(ms / 1000);
  const t0 = new Date("2026-03-02T09:00:00Z");

  (async () => {
    console.log("seven crashes in a row:");
    for (let i = 0; i < 7; i++) {
      const { attempt, delaySec } = await enforceStartupBackoff(file, new Date(t0.getTime() + i * 5000), fakeSleep);
      console.log(`  start ${attempt}: wait ${delaySec}s`);
    }
    const quiet = await enforceStartupBackoff(file, new Date(t0.getTime() + 2 * 3600 * 1000), fakeSleep);
    console.log(`two quiet hours later: attempt ${quiet.attempt}, wait ${quiet.delaySec}s (reset)`);
    resetCircuitBreaker(file);
    console.log("clean shutdown removes the state file:", !fs.existsSync(file));
  })();
}
