// Automatic fixes of analysis findings (api/brand/fixes.py): API shapes and
// the small pure helpers the fix cards render with.

import type { VersionDiff } from "@/brand/versions/model";

export type FixStatus =
  | "proposing"
  | "proposed"
  | "applied"
  | "testing"
  | "tested"
  | "published"
  | "discarded"
  | "failed"
  | "not_fixable"
  | "rolled_back";

export interface ReplayMessage {
  role: "caller" | "agent" | "system";
  text: string;
  node?: string | null;
}

export interface PathMetrics {
  steps: number;
  revisits: number;
  ping_pong: number;
  max_replies_in_a_node: number;
  agent_replies: number;
}

export interface Replay {
  run_id: number;
  path: string[];
  transcript: ReplayMessage[];
  tool_calls: Array<{ name: string; arguments: Record<string, unknown> }>;
  ended: boolean;
  caller_turns_used: number;
  error: string | null;
  metrics?: PathMetrics;
}

export interface SimulationCase {
  case: number;
  source_call: number;
  caller_turns: number;
  original_path: string[];
  baseline: Replay | null;
  candidate: Replay;
  verdict?: "improved" | "unchanged" | "regressed" | null;
  notes?: string;
}

export interface Simulation {
  status: "queued" | "starting" | "running" | "done" | "failed";
  started_at?: string;
  finished_at?: string;
  total?: number;
  cases: SimulationCase[];
  verdict?: "pass" | "mixed" | "fail" | "inconclusive" | null;
  summary?: string;
  model?: string | null;
  error?: string;
  judge_error?: string | null;
}

export interface FollowUp {
  status: "waiting" | "fixed" | "still_present" | "worse" | "manual";
  checked_at: string;
  min_calls: number;
  calls_after: number;
  calls_before?: number;
  before?: { severity: string; title: string } | null;
  after?: { severity: string; title: string } | null;
  note?: string;
}

export interface Fix {
  id: string;
  created_at: string;
  updated_at: string;
  status: FixStatus;
  report_id: string;
  finding: { id: string; title: string; rule: string | null; node: string | null; agent: string | null; calls: number[] };
  workflow_id: number | null;
  workflow_name?: string;
  base_version_number?: number;
  review?: boolean;
  review_reason?: string | null;
  reason?: string | null;
  error?: string | null;
  model?: string;
  proposal?: {
    summary: string;
    rationale: string;
    expected_effect: string;
    risks: string[];
    test_focus: string;
    operations: Array<Record<string, unknown>>;
  } | null;
  draft_definition_id?: number;
  draft_version_number?: number;
  combined_with?: string[];
  simulation?: Simulation | null;
  preview?: VersionDiff | null;
  follow_up?: FollowUp | null;
  rolled_back_to?: number;
  rolled_back_at?: string;
  preview_error?: string;
}

// Mirrors api/brand/fixes.py fixability(): what only the infrastructure or an
// external service can fix.
const NOT_FIXABLE_RULES: Record<string, string> = {
  reply_latency: "The time to first audio comes from the models and the infrastructure.",
  greeting_latency: "The greeting delay comes from the models and the infrastructure.",
  dead_air_agent: "Silences before the agent answers come from model latency.",
  tool_errors: "The tool itself fails: fix the webhook or the service it calls.",
  tool_slow: "The tool itself is slow: speed up the service it calls.",
  pipeline_errors: "Pipeline errors are technical failures, not configuration issues.",
};

export function fixability(finding: { rule: string | null; category: string }): { fixable: boolean; reason?: string } {
  const rule = finding.rule ?? "";
  if (NOT_FIXABLE_RULES[rule]) return { fixable: false, reason: NOT_FIXABLE_RULES[rule] };
  if (rule.startsWith("stage_")) return { fixable: false, reason: "A slow stage is a model / infrastructure matter." };
  if (!rule && ["latency", "tools", "reliability"].includes(finding.category)) {
    return { fixable: false, reason: "This is not a configuration issue." };
  }
  return { fixable: true };
}

export const BUSY: FixStatus[] = ["proposing", "testing"];

export const STATUS_LABEL: Record<FixStatus, string> = {
  proposing: "Preparing a fix…",
  proposed: "Fix proposed",
  applied: "Draft ready",
  testing: "Testing…",
  tested: "Tested",
  published: "Published",
  discarded: "Discarded",
  failed: "Failed",
  not_fixable: "Not fixable automatically",
  rolled_back: "Rolled back",
};

export const FOLLOW_UP_LABEL: Record<FollowUp["status"], string> = {
  waiting: "Waiting for calls",
  fixed: "Fixed in real calls",
  still_present: "Still present",
  worse: "Worse than before",
  manual: "Check with a new analysis",
};

/** A published (or rolled back) fix of the same problem in another report. */
export function priorFix(
  fixes: Fix[],
  finding: { id: string; rule: string | null; agent: string | null; node: string | null },
  reportId: string,
): Fix | undefined {
  if (!finding.rule) return undefined;
  return fixes
    .filter(
      (f) =>
        f.report_id !== reportId &&
        (f.status === "published" || f.status === "rolled_back") &&
        f.finding.rule === finding.rule &&
        (f.finding.agent ?? null) === (finding.agent ?? null) &&
        (f.finding.node ?? null) === (finding.node ?? null),
    )
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
}

/** The fix to show for a finding: the latest one not discarded, else the latest. */
export function fixForFinding(fixes: Fix[], findingId: string): Fix | undefined {
  const mine = fixes
    .filter((f) => f.finding.id === findingId)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  return mine.find((f) => f.status !== "discarded") ?? mine[0];
}

export function operationLabel(op: Record<string, unknown>): string {
  switch (op.op) {
    case "set_node_field":
      return `Node “${op.node}” › ${op.field}`;
    case "set_edge_field":
      return `Transition ${op.from} → ${op.to} › ${op.field}`;
    case "set_setting":
      return `Setting ${op.key} = ${JSON.stringify(op.value)}`;
    default:
      return String(op.op);
  }
}

export const STEPS = ["Proposal", "Draft", "Test", "Publish"] as const;

/** How far along the 4 steps a fix is (index of the current step). */
export function stepIndex(status: FixStatus): number {
  return { proposing: 0, proposed: 0, failed: 0, not_fixable: 0, applied: 1, testing: 2, tested: 2, published: 3, rolled_back: 3, discarded: 0 }[status];
}
