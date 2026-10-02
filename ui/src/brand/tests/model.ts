// Test campaigns (api/brand/test_campaigns.py, test_runs.py): shared types,
// labels and formatting.

export type Range = [number, number];

export interface DimensionInfo {
  label: string;
  levels: Record<string, string>;
}

export interface Voice {
  id: string;
  gender: "female" | "male" | "unknown";
  label?: string | null;
}

export interface TestSettings {
  tester_telephony_configuration_id: number | null;
  test_inbound_number: string | null;
  caller_numbers: string[];
  voices: Voice[];
  concurrency: number;
  tester_workflow_id: number | null;
}

export interface SettingsResponse {
  settings: TestSettings;
  telephony_configurations: Array<{ id: number; name: string; provider: string }>;
  dimensions: Record<string, DimensionInfo>;
  default_ranges: Record<string, Range>;
  default_speed: Range;
  speed_limits: Range;
}

export type ToolsMode = "simulated" | "real" | "real_with_header";

export interface Persona {
  name: string;
  age: number | null;
  gender: string;
  situation: string;
  personality: string;
}

export interface Scenario {
  id: string;
  title: string;
  intent: string;
  levels: Record<string, number>;
  speed: number;
  voice: Voice | null;
  caller_number: string | null;
  persona: Persona;
  goal: string;
  behaviour: string;
  facts: Record<string, string>;
  criteria: string[];
  forbidden: string[];
  expected_end_node: string | null;
  expected_variables: Record<string, string>;
  expected_tools: string[];
  tool_hints: string;
  variant_of: string | null;
  enabled: boolean;
}

export type ExecutionStatus = "queued" | "running" | "done" | "failed" | "cancelled" | "interrupted";
export type Verdict = "pass" | "partial" | "fail";
export type Channel = "phone" | "text";

export interface ExecutionSummary {
  id: string;
  campaign_id: string;
  workflow_id: number;
  definition_id: number;
  version_number: number;
  version_status: string;
  channel: Channel;
  passes: number;
  personas: "frozen" | "fresh";
  status: ExecutionStatus;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  created_by?: { id: number | null; email: string | null } | null;
  progress: { total: number; finished: number; running: number };
  pass_rate: number | null;
  score: number | null;
  verdicts: Record<Verdict, number> | null;
  latency_p50_ms: number | null;
}

export interface CampaignSummary {
  id: string;
  name: string;
  workflow_id: number;
  workflow_name: string;
  status: "generating" | "ready" | "failed";
  generation: { done: number; total: number; error: string | null } | null;
  count: number;
  tools_mode: ToolsMode;
  language: string;
  created_at: string;
  updated_at: string;
  scenarios: number;
  executions: number;
  last_execution: ExecutionSummary | null;
  last_done: ExecutionSummary | null;
  previous_done: ExecutionSummary | null;
}

export interface Campaign extends Omit<CampaignSummary, "scenarios" | "executions" | "last_execution" | "last_done" | "previous_done"> {
  ranges: Record<string, Range>;
  speed: Range;
  max_duration_seconds: number;
  instructions: string | null;
  scenarios: Scenario[];
  executions: ExecutionSummary[];
}

export interface CallMetrics {
  duration_seconds: number | null;
  caller_turns: number;
  agent_turns: number;
  interruptions: number;
  latency: { turns: number; p50_ms: number | null; p90_ms: number | null; greeting_ms: number | null };
  tools: Array<{ name: string; ms: number | null; failed: boolean }>;
  path: string[];
  end_node: string | null;
  end_status: string;
  extracted_variables: Record<string, unknown>;
}

export interface Judge {
  goal_reached: boolean;
  criteria: Array<{ text: string; pass: boolean; evidence: string }>;
  forbidden: Array<{ text: string; violated: boolean; evidence: string }>;
  scores: Record<string, number>;
  failure_node: string | null;
  summary: string;
  issues: string[];
  /** The judge thinks the scenario itself is flawed. */
  scenario_issue: string | null;
  error: string | null;
}

export interface TestCall {
  index: number;
  pass: number;
  scenario_id: string;
  scenario: Scenario;
  status: "pending" | "running" | "judging" | "done" | "error" | "cancelled";
  error?: string;
  agent_run_id?: number;
  caller_run_id?: number;
  ended_by?: string | null;
  metrics?: CallMetrics;
  checks?: Array<{ kind: string; label: string; pass: boolean; detail: string }>;
  judge?: Judge | null;
  verdict?: Verdict | null;
  fix_id?: string;
}

export interface ScenarioRow {
  scenario_id: string;
  title: string;
  levels: Record<string, number>;
  calls: number;
  pass: number;
  partial: number;
  fail: number;
  error: number;
  pass_rate: number | null;
  score: number | null;
  unstable: boolean;
  avg_score: number | null;
}

export interface Report {
  calls: number;
  played: number;
  judged: number;
  errors: number;
  cancelled: number;
  verdicts: Record<Verdict, number>;
  pass_rate: number | null;
  score: number | null;
  goal_rate: number | null;
  scores: Record<string, number>;
  by_scenario: ScenarioRow[];
  by_dimension: Record<string, Record<string, { calls: number; pass: number; pass_rate: number | null }>>;
  latency: {
    turns: number;
    p50_ms: number | null;
    p90_ms: number | null;
    greeting_p50_ms: number | null;
    slow_turns_rate: number | null;
    stages_p50_ms: Record<string, number | null>;
  };
  interruptions: { total: number; per_call: number | null; calls_rate: number | null };
  tools: { calls: number; failure_rate: number | null; by_tool: Record<string, { calls: number; failed: number; avg_ms: number | null }> };
  coverage: {
    nodes_total: number;
    nodes_visited: number;
    edges_total: number;
    edges_used: number;
    nodes_rate: number | null;
    edges_rate: number | null;
    nodes_never_visited: string[];
    edges_never_used: Array<{ from: string; to: string; label: string }>;
    node_visits: Record<string, number>;
  };
  duration: { p50_seconds: number | null; p90_seconds: number | null; turns_p50: number | null };
  end_status: Record<string, number>;
  criteria_failures: Array<{ text: string; count: number }>;
  checks_failed: Array<{ label: string; count: number }>;
  failure_nodes: Record<string, number>;
  scenario_issues?: Array<{ index: number; scenario_id: string; title: string; issue: string }>;
}

export interface Execution extends Omit<ExecutionSummary, "progress" | "pass_rate" | "score" | "verdicts" | "latency_p50_ms"> {
  campaign_name: string;
  workflow_name: string;
  concurrency: number;
  tools_mode: ToolsMode;
  language: string;
  phone: { destination: string; provider: string } | null;
  calls: TestCall[];
  report: Report | null;
}

export interface Indicator {
  key: string;
  label: string;
  kind: "rate" | "score" | "ms" | "seconds" | "number";
  better: "higher" | "lower";
  a: number | null;
  b: number | null;
  delta: number | null;
  trend: "better" | "worse" | "same" | null;
}

export interface Comparison {
  a: Partial<Execution>;
  b: Partial<Execution>;
  indicators: Indicator[];
  scenarios: Array<{
    scenario_id: string;
    title: string;
    a: Pick<ScenarioRow, "calls" | "pass" | "partial" | "fail" | "error" | "score"> | null;
    b: Pick<ScenarioRow, "calls" | "pass" | "partial" | "fail" | "error" | "score"> | null;
    change: "improved" | "regressed" | "same" | "new" | "removed" | "unknown";
  }>;
  changes: Record<string, number>;
  coverage: { nodes_gained: string[]; nodes_lost: string[] };
  version_diff: import("../versions/model").VersionDiff | null;
  /** Executions made before the versions were kept in the execution. */
  version_unavailable?: boolean;
}

export const DIMENSION_ORDER = [
  "vocabulary",
  "mood",
  "clarity",
  "complexity",
  "depth",
  "impatience",
  "dictation",
  "traps",
] as const;

export const SHORT_LABEL: Record<string, string> = {
  vocabulary: "Vocab.",
  mood: "Mood",
  clarity: "Clarity",
  complexity: "Complex.",
  depth: "Depth",
  impatience: "Impat.",
  dictation: "Dictation",
  traps: "Traps",
};

export const TOOLS_MODE_LABEL: Record<ToolsMode, string> = {
  simulated: "Simulated (nothing executed)",
  real: "Real",
  real_with_header: "Real, with the X-Oxee-Test header",
};

export const STATUS_LABEL: Record<ExecutionStatus, string> = {
  queued: "Queued",
  running: "Running",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
};

export const VERDICT_META: Record<Verdict, { label: string; className: string }> = {
  pass: { label: "Pass", className: "text-emerald-700 dark:text-emerald-300" },
  partial: { label: "Partial", className: "text-amber-700 dark:text-amber-300" },
  fail: { label: "Fail", className: "text-red-700 dark:text-red-300" },
};

export const busy = (status: ExecutionStatus | undefined) => status === "queued" || status === "running";

export function pct(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)} %`;
}

export function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
}

export function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const s = Math.round(value);
  return s >= 60 ? `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")}` : `${s} s`;
}

export function formatIndicator(kind: Indicator["kind"], value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  switch (kind) {
    case "rate":
      return pct(value);
    case "ms":
      return ms(value);
    case "seconds":
      return seconds(value);
    case "score":
      return value.toFixed(2);
    default:
      return String(Math.round(value * 100) / 100);
  }
}

/** Signed delta in the indicator's unit (rates in percentage points). */
export function formatDelta(kind: Indicator["kind"], delta: number | null): string {
  if (delta === null || delta === 0) return delta === 0 ? "=" : "";
  const sign = delta > 0 ? "+" : "−";
  const abs = Math.abs(delta);
  switch (kind) {
    case "rate":
      return `${sign}${(abs * 100).toFixed(0)} pts`;
    case "ms":
      return `${sign}${ms(abs)}`;
    case "seconds":
      return `${sign}${seconds(abs)}`;
    case "score":
      return `${sign}${abs.toFixed(2)}`;
    default:
      return `${sign}${Math.round(abs * 100) / 100}`;
  }
}

export function rangeLabel([lo, hi]: Range): string {
  return lo === hi ? String(lo) : `${lo}–${hi}`;
}

export function versionLabel(e: Pick<ExecutionSummary, "version_number" | "version_status">): string {
  return `v${e.version_number}${e.version_status === "draft" ? " (draft)" : e.version_status === "published" ? "" : ` (${e.version_status})`}`;
}

/** Estimated wall time of an execution, in minutes (phone: ~2.5 min a call). */
export function estimateMinutes(calls: number, channel: Channel, concurrency: number): number {
  const perCall = channel === "phone" ? 2.5 : 1;
  return Math.max(1, Math.ceil((calls * perCall) / Math.max(1, channel === "phone" ? concurrency : 1)));
}

export function parseNumbers(text: string): string[] {
  return Array.from(new Set(text.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean)));
}
