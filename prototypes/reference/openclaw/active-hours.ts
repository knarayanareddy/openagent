/**
 * OpenClaw's scheduling idea, distilled: a job carries a wall-clock window, and
 * "outside the window" means wait, not fail.
 *
 * Upstream: github.com/openclaw/openclaw (MIT)
 *   src/cron/active-hours.ts      assertCronActiveHours, isCronWithinActiveHours
 *   src/cron/active-jobs.ts       jobs, their state and run history
 *   docs/gateway/heartbeat.md     heartbeat monitors became ordinary automation jobs, with a
 *                                 per-job "scratch" notebook that survives between runs
 *
 * What is worth copying:
 *   - Compare WALL-CLOCK minutes in the job's timezone, not instants. It survives DST (both
 *     occurrences of a repeated hour) and overnight windows (22:00 to 06:00) with one branch.
 *   - start === end is an EMPTY window, not "all day". "Always" is spelled by omitting the window.
 *   - A monitor is a job, not a special case. It has a schedule, a prompt, scratch, and delivery.
 *
 * Run:  npx tsx active-hours.ts
 */

export interface ActiveHours {
  start: string; // "HH:MM"
  end: string; // "HH:MM", or "24:00"
  timezone?: "user" | "local" | string; // an IANA zone, or one of the two keywords
}

export function assertActiveHours(active: ActiveHours): void {
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(active.start) || !/^(([01]\d|2[0-3]):[0-5]\d|24:00)$/.test(active.end)) {
    throw new Error("activeHours requires HH:MM start/end (24:00 is allowed only for end)");
  }
  const tz = active.timezone;
  if (tz !== undefined && tz !== "user" && tz !== "local") {
    try {
      new Intl.DateTimeFormat("en-US", { timeZone: tz }).format(0);
    } catch {
      throw new Error("activeHours.timezone must be user, local, or an IANA timezone");
    }
  }
}

const toMinutes = (value: string): number => Number(value.slice(0, 2)) * 60 + Number(value.slice(3));

export function isWithinActiveHours(active: ActiveHours | undefined, nowMs: number, userTimezone = "UTC"): boolean {
  if (!active) return true;
  const timeZone =
    !active.timezone || active.timezone === "user"
      ? userTimezone
      : active.timezone === "local"
        ? Intl.DateTimeFormat().resolvedOptions().timeZone
        : active.timezone;
  const parts = new Intl.DateTimeFormat("en-US", { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(
    new Date(nowMs),
  );
  const minute =
    Number(parts.find((p) => p.type === "hour")?.value) * 60 + Number(parts.find((p) => p.type === "minute")?.value);
  const start = toMinutes(active.start);
  const end = toMinutes(active.end);
  if (start === end) return false;
  return end > start ? minute >= start && minute < end : minute >= start || minute < end;
}

// ---- a monitor is just a job with scratch -----------------------------------------------------

export interface Job {
  id: string;
  prompt: string;
  everyMinutes: number;
  activeHours?: ActiveHours;
  scratch: string; // notes the job leaves for its next run
  nextRunMs: number;
}

export interface Tick {
  jobId: string;
  action: "ran" | "deferred" | "idle";
  note?: string;
}

/** One scheduler pass. A deferred job keeps its nextRunMs, so it runs on the first pass inside the window. */
export function tick(jobs: Job[], nowMs: number, run: (job: Job) => string): Tick[] {
  return jobs.map((job): Tick => {
    if (job.nextRunMs > nowMs) return { jobId: job.id, action: "idle" };
    if (!isWithinActiveHours(job.activeHours, nowMs)) {
      return { jobId: job.id, action: "deferred", note: `outside ${job.activeHours?.start}-${job.activeHours?.end}` };
    }
    job.scratch = run(job); // the run's output becomes the next run's scratch
    // Skip every missed slot: one catch-up run, never a storm.
    while (job.nextRunMs <= nowMs) job.nextRunMs += job.everyMinutes * 60_000;
    return { jobId: job.id, action: "ran", note: job.scratch };
  });
}

// ---- demo -----------------------------------------------------------------------------------------

const isMain = typeof process !== "undefined" && process.argv[1]?.endsWith("active-hours.ts");
if (isMain) {
  const at = (h: number, m = 0) => Date.UTC(2026, 2, 2, h, m);
  const day: ActiveHours = { start: "08:00", end: "20:00", timezone: "UTC" };
  const night: ActiveHours = { start: "22:00", end: "06:00", timezone: "UTC" };
  const ny: ActiveHours = { start: "08:00", end: "20:00", timezone: "America/New_York" };
  for (const [label, window, ms] of [
    ["08:00-20:00 at 09:00 UTC", day, at(9)],
    ["08:00-20:00 at 03:00 UTC", day, at(3)],
    ["22:00-06:00 at 23:00 UTC (overnight)", night, at(23)],
    ["22:00-06:00 at 12:00 UTC", night, at(12)],
    ["08:00-20:00 New York at 09:00 UTC (= 04:00 there)", ny, at(9)],
    ["08:00-08:00 (empty window)", { start: "08:00", end: "08:00" }, at(8)],
    ["no window", undefined, at(3)],
  ] as const) {
    console.log(String(isWithinActiveHours(window, ms)).padEnd(5), label);
  }
  try {
    assertActiveHours({ start: "8am", end: "20:00" });
  } catch (error) {
    console.log("rejects bad input:", (error as Error).message);
  }

  const job: Job = {
    id: "inbox-monitor",
    prompt: "Check the inbox. Note anything urgent.",
    everyMinutes: 60,
    activeHours: day,
    scratch: "",
    nextRunMs: at(3),
  };
  let runs = 0;
  const run = (j: Job) => `${j.scratch ? j.scratch + " | " : ""}run ${++runs}`;
  for (const hour of [3, 6, 8, 9]) {
    const result = tick([job], at(hour), run)[0];
    console.log(`${String(hour).padStart(2, "0")}:00`, result.action.padEnd(8), result.note ?? "");
  }
}
