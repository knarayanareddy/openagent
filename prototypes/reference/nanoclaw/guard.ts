/**
 * NanoClaw's privileged-action guard, distilled: one decision seam, three verdicts, and a rule
 * for replaying an approved call that cannot be talked around.
 *
 * Upstream: github.com/qwibitai/nanoclaw (MIT)
 *   src/guard/guard.ts, guard-actions.ts, types.ts   the decision function and the action catalog
 *   src/delivery-guard.ts                            runGuarded: precheck -> guard -> deny/hold/allow
 *   src/command-gate.ts                              pass / filter / deny for slash commands
 *
 * What is worth copying:
 *   - Guarded actions are VALUES returned by defineGuardedAction(), never names to look up.
 *     A mistyped action is a compile error, not a runtime fail-open.
 *   - Precheck runs BEFORE the guard. A malformed request is answered without ever creating a hold.
 *   - An approved replay carries a grant. The grant satisfies a HOLD but never a DENY, because the
 *     structural checks run again, live. Approve-then-revoke does not execute.
 *
 * Run:  npx tsx guard.ts
 */

export type Verdict = "allow" | "deny" | "hold";
export interface Decision {
  verdict: Verdict;
  reason: string;
}

declare const brand: unique symbol;
export type GuardedAction = { readonly name: string; readonly [brand]: true };

const catalog = new Map<string, (input: Record<string, unknown>, actor: Actor) => Decision>();

export interface Actor {
  userId: string;
  isAdmin: boolean;
  revoked: Set<string>; // destinations that were valid when the call was parked and are not now
}

export function defineGuardedAction(
  name: string,
  decide: (input: Record<string, unknown>, actor: Actor) => Decision,
): GuardedAction {
  if (catalog.has(name)) throw new Error(`guarded action '${name}' is already defined`);
  catalog.set(name, decide);
  return { name } as GuardedAction;
}

export interface Grant {
  approvalId: string;
}

/** The one decision function. */
export function guard(action: GuardedAction, input: Record<string, unknown>, actor: Actor): Decision {
  const decide = catalog.get(action.name);
  if (!decide) return { verdict: "deny", reason: `no rule for ${action.name}` };
  return decide(input, actor);
}

// ---- runGuarded: precheck -> guard -> deny / hold / allow -------------------------------------------

export interface GuardSpec<T extends Record<string, unknown>> {
  action: GuardedAction;
  precheck?: (input: T) => boolean; // false = malformed: answer it, never create a hold
  requestHold: (input: T) => string; // returns the approval id
  onDeny?: (input: T, reason: string) => void;
}

export type Outcome = "ran" | "held" | "denied" | "malformed";

export function runGuarded<T extends Record<string, unknown>>(
  spec: GuardSpec<T>,
  input: T,
  actor: Actor,
  handler: (input: T) => void,
  grant: Grant | null = null, // null on a fresh call; the approval row on a replay
): Outcome {
  if (spec.precheck && !spec.precheck(input)) return "malformed";
  const decision = guard(spec.action, input, actor); // structural checks always run live
  if (decision.verdict === "deny") {
    spec.onDeny?.(input, decision.reason);
    return "denied"; // a grant never upgrades a deny
  }
  if (decision.verdict === "hold" && grant === null) {
    spec.requestHold(input);
    return "held";
  }
  handler(input); // allow, or a hold that has a grant
  return "ran";
}

// ---- the command gate -----------------------------------------------------------------------------------

export type GateResult = { action: "pass" } | { action: "filter" } | { action: "deny"; command: string };

const FILTERED = new Set(["/compact"]);
const ADMIN = new Set(["/clear", "/upload-trace"]);

export function gateCommand(content: string, isAdmin: boolean): GateResult {
  const command = content.trim().startsWith("/") ? content.trim().split(/\s+/)[0].toLowerCase() : null;
  if (command === null) return { action: "pass" };
  if (FILTERED.has(command)) return { action: "filter" };
  if (ADMIN.has(command)) return isAdmin ? { action: "pass" } : { action: "deny", command };
  return { action: "pass" }; // unknown slash commands pass through
}

// ---- demo ------------------------------------------------------------------------------------------------

const isMain = typeof process !== "undefined" && process.argv[1]?.endsWith("guard.ts");
if (isMain) {
  const SEND = defineGuardedAction("send_message", (input, actor) => {
    const to = String(input.to ?? "");
    if (actor.revoked.has(to)) return { verdict: "deny", reason: `${to} was revoked` };
    return to === actor.userId
      ? { verdict: "allow", reason: "reply to the requester" }
      : { verdict: "hold", reason: "a message to someone else is a write" };
  });
  const log: string[] = [];
  const spec: GuardSpec<{ to: string; body: string }> = {
    action: SEND,
    precheck: (i) => i.to.length > 0 && i.body.length > 0,
    requestHold: (i) => {
      log.push(`  hold: asked the admin about ${i.to}`);
      return "appr_1";
    },
    onDeny: (_i, reason) => log.push(`  deny: ${reason}`),
  };
  const actor: Actor = { userId: "ana", isAdmin: false, revoked: new Set() };
  const send = (i: { to: string; body: string }) => log.push(`  SENT to ${i.to}: ${i.body}`);
  const show = (label: string, outcome: Outcome) => {
    console.log(label.padEnd(44), outcome);
    log.splice(0).forEach((l) => console.log(l));
  };

  show("reply to self", runGuarded(spec, { to: "ana", body: "hi" }, actor, send));
  show("message to sam (fresh call)", runGuarded(spec, { to: "sam", body: "late" }, actor, send));
  show("empty body (precheck, no hold created)", runGuarded(spec, { to: "sam", body: "" }, actor, send));
  show("approved replay to sam (grant)", runGuarded(spec, { to: "sam", body: "late" }, actor, send, { approvalId: "appr_1" }));
  actor.revoked.add("sam");
  show("approved replay AFTER sam was revoked", runGuarded(spec, { to: "sam", body: "late" }, actor, send, { approvalId: "appr_1" }));
  console.log("commands:", ["hello", "/compact", "/clear", "/whatever"].map((c) => `${c}=${gateCommand(c, false).action}`).join("  "));
  console.log("admin /clear:", gateCommand("/clear", true).action);
}
