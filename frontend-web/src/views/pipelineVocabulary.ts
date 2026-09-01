import type { BoardBranch, BoardStage } from "../lib/queries";

/**
 * One vocabulary for the board and everything that reports against it.
 *
 * Auto mode used to describe the same nine stages in words of its own —
 * "auto Sub-strands", a wall of identical buttons in no particular order —
 * while the board next door showed those stages with their real state. Two
 * descriptions of one pipeline is one description too many: the operator has
 * to hold the mapping in their head, and the two drift the first time a stage
 * is renamed on one screen.
 */

export type Tone = "ok" | "warn" | "danger" | "accent" | "neutral";

export const TONE: Record<string, Tone> = {
  approved: "ok",
  reviewed: "accent",
  built: "warn",
  running: "accent",
  failing: "danger",
  blocked: "neutral",
  not_started: "neutral",
};

export const WORDS: Record<string, string> = {
  approved: "approved",
  reviewed: "awaiting sign-off",
  built: "built, not through the gate",
  running: "running",
  failing: "failing",
  blocked: "waiting upstream",
  not_started: "not started",
};

/**
 * Least-finished first, with failure ahead of everything.
 *
 * A grade rolled up across seven learning areas has seven answers per stage.
 * Reporting the best of them is how a stage reads "approved" while two subjects
 * in it have not started — so the rollup reports the one that still needs work,
 * and a failure anywhere outranks progress everywhere.
 */
const RANK = [
  "failing", "running", "blocked", "not_started", "built", "reviewed", "approved",
];

export function worst(statuses: string[]): string {
  let best = RANK.length;
  for (const s of statuses) {
    const i = RANK.indexOf(s);
    if (i >= 0 && i < best) best = i;
  }
  return RANK[best] ?? "not_started";
}

/** Sum one stage across the branches selected, keeping the board's numbers. */
export function rollupStages(branches: BoardBranch[]): Map<string, BoardStage> {
  const out = new Map<string, BoardStage>();
  const statuses = new Map<string, string[]>();

  for (const branch of branches) {
    for (const stage of branch.stages) {
      const carry = out.get(stage.stage);
      if (!carry) {
        out.set(stage.stage, { ...stage });
      } else {
        carry.expected += stage.expected;
        carry.built += stage.built;
        carry.reviewed += stage.reviewed;
        carry.approved += stage.approved;
        carry.running += stage.running;
        carry.failed += stage.failed;
        carry.cost_usd += stage.cost_usd;
        // The first branch's blocker is not the rollup's blocker; the first
        // one that is actually blocked is.
        if (!carry.blocked_by && stage.blocked_by) carry.blocked_by = stage.blocked_by;
      }
      statuses.set(stage.stage, [...(statuses.get(stage.stage) || []), stage.status]);
    }
  }

  for (const [name, stage] of out) {
    stage.status = worst(statuses.get(name) || []);
    stage.percentage = stage.expected
      ? Math.round((stage.built / stage.expected) * 100)
      : stage.built
        ? 100
        : 0;
  }
  return out;
}
