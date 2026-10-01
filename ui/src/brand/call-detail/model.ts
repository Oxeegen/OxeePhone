// Call-detail data model: turns a workflow run (logs.realtime_feedback_events,
// usage_info, annotations...) into what the page renders. Pure functions only,
// unit-tested in model.test.ts.

export interface FeedbackEvent {
  type: string;
  payload: Record<string, unknown>;
  timestamp?: string;
  turn?: number;
  node_id?: string;
  node_name?: string;
}

export interface CallRun {
  id: number;
  mode?: string | null;
  created_at?: string | null;
  is_completed?: boolean;
  call_type?: string | null;
  recording_url?: string | null;
  user_recording_url?: string | null;
  bot_recording_url?: string | null;
  transcript_url?: string | null;
  usage_info?: Record<string, unknown> | null;
  cost_info?: Record<string, unknown> | null;
  initial_context?: Record<string, unknown> | null;
  gathered_context?: Record<string, unknown> | null;
  annotations?: Record<string, unknown> | null;
  logs?: { realtime_feedback_events?: FeedbackEvent[] } | null;
}

export const RECORDING_STARTED = "oxee-recording-started";
export const LATENCY_BREAKDOWN = "oxee-latency-breakdown";

const ms = (iso?: string | null): number | null => {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
};
const str = (value: unknown): string => (typeof value === "string" ? value : "");
const num = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);

export function events(run: CallRun): FeedbackEvent[] {
  return run.logs?.realtime_feedback_events ?? [];
}

// ------------------------------------------------------------- time anchor

export interface RecordingAnchor {
  /** Epoch ms of the recordings' first sample. */
  epochMs: number;
  source: "marker" | "bot-onset" | "first-event";
}

/**
 * Where t=0 of the recordings is. New calls carry an explicit marker; older
 * ones are aligned by matching the first bot message with the first sound in
 * the bot track (``botOnsetSecs``), else the first event.
 */
export function recordingAnchor(run: CallRun, botOnsetSecs?: number | null): RecordingAnchor | null {
  const all = events(run);
  const marker = all.find((e) => e.type === RECORDING_STARTED);
  const markerMs = ms(marker?.timestamp);
  if (markerMs !== null) return { epochMs: markerMs, source: "marker" };

  const firstBot = all.find((e) => e.type === "rtf-bot-text");
  const firstBotMs = ms(str(firstBot?.payload.timestamp)) ?? ms(firstBot?.timestamp);
  if (firstBotMs !== null && botOnsetSecs != null && botOnsetSecs >= 0) {
    return { epochMs: firstBotMs - botOnsetSecs * 1000, source: "bot-onset" };
  }
  const first = all.map((e) => ms(e.timestamp)).find((t) => t !== null);
  return first != null ? { epochMs: first, source: "first-event" } : null;
}

// ---------------------------------------------------------------- timeline

export interface TimelineMessage {
  kind: "message";
  id: string;
  role: "user" | "agent";
  text: string;
  turn?: number;
  nodeName?: string;
  startMs: number | null;
  endMs: number | null;
  /** Seconds from the recording start. */
  start: number | null;
  end: number | null;
  interrupted: boolean;
  latencySecs?: number;
}

export interface TimelineToolCall {
  kind: "tool";
  id: string;
  name: string;
  args: unknown;
  result: unknown;
  status: "completed" | "running";
  turn?: number;
  startMs: number | null;
  start: number | null;
  durationMs: number | null;
}

export interface TimelineNode {
  kind: "node";
  id: string;
  name: string;
  previous?: string;
  /** Label of the pathway (edge) the LLM took, when known. */
  pathway?: string;
  startMs: number | null;
  start: number | null;
}

export interface TimelineError {
  kind: "error";
  id: string;
  text: string;
  fatal: boolean;
  startMs: number | null;
  start: number | null;
}

export type TimelineItem = TimelineMessage | TimelineToolCall | TimelineNode | TimelineError;

function parseMaybeJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return value;
  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

export function buildTimeline(
  run: CallRun,
  anchor: RecordingAnchor | null,
  options: { hiddenToolCallIds?: Set<string>; pathwayByNodeItem?: Map<string, string> } = {},
): TimelineItem[] {
  const rel = (t: number | null) => (t !== null && anchor ? (t - anchor.epochMs) / 1000 : null);
  const latencyByTurn = new Map<number, number>();
  for (const e of events(run)) {
    if (e.type === LATENCY_BREAKDOWN && e.turn != null) latencyByTurn.set(e.turn, num(e.payload.total_secs));
  }

  const items: TimelineItem[] = [];
  const tools = new Map<string, TimelineToolCall>();
  events(run).forEach((e, index) => {
    const eventMs = ms(e.timestamp);
    if (e.type === "rtf-user-transcription" || e.type === "rtf-bot-text") {
      if (e.type === "rtf-user-transcription" && e.payload.final === false) return;
      const text = str(e.payload.text).trim();
      if (!text) return;
      const role = e.type === "rtf-bot-text" ? "agent" : "user";
      const startMs = ms(str(e.payload.timestamp)) ?? eventMs;
      const endMs = ms(str(e.payload.end_timestamp));
      items.push({
        kind: "message",
        id: `${role}-${e.turn ?? "x"}-${index}`,
        role,
        text,
        turn: e.turn,
        nodeName: e.node_name,
        startMs,
        endMs,
        start: rel(startMs),
        end: rel(endMs),
        interrupted: e.payload.interrupted === true,
        latencySecs: role === "agent" && e.turn != null ? latencyByTurn.get(e.turn) : undefined,
      });
    } else if (e.type === "rtf-function-call-start") {
      const id = str(e.payload.tool_call_id) || `tool-${index}`;
      if (options.hiddenToolCallIds?.has(id)) return; // node transitions, shown as markers
      const call: TimelineToolCall = {
        kind: "tool",
        id,
        name: str(e.payload.function_name) || "tool",
        args: parseMaybeJson(e.payload.arguments),
        result: undefined,
        status: "running",
        turn: e.turn,
        startMs: eventMs,
        start: rel(eventMs),
        durationMs: null,
      };
      tools.set(id, call);
      items.push(call);
    } else if (e.type === "rtf-function-call-end") {
      const call = tools.get(str(e.payload.tool_call_id));
      if (call) {
        call.result = parseMaybeJson(e.payload.result);
        call.status = "completed";
        const endMs = eventMs;
        call.durationMs = endMs !== null && call.startMs !== null ? endMs - call.startMs : null;
      }
    } else if (e.type === "rtf-node-transition") {
      items.push({
        kind: "node",
        id: `node-${index}`,
        name: str(e.payload.node_name) || str(e.node_name) || "node",
        previous: str(e.payload.previous_node_name) || undefined,
        pathway: options.pathwayByNodeItem?.get(`node-${index}`),
        startMs: eventMs,
        start: rel(eventMs),
      });
    } else if (e.type === "rtf-pipeline-error") {
      items.push({
        kind: "error",
        id: `error-${index}`,
        text: str(e.payload.error) || "Pipeline error",
        fatal: e.payload.fatal === true,
        startMs: eventMs,
        start: rel(eventMs),
      });
    }
  });
  return items.sort((a, b) => (a.startMs ?? 0) - (b.startMs ?? 0));
}

/** The message being heard at ``time`` (seconds), if any. */
export function activeMessageId(items: TimelineItem[], time: number): string | null {
  let best: TimelineMessage | null = null;
  for (const item of items) {
    if (item.kind !== "message" || item.start === null) continue;
    const end = item.end ?? item.start + 2;
    if (time >= item.start && time <= end) best = item;
  }
  return best?.id ?? null;
}

// ----------------------------------------------------------------- latency

export const STAGES = ["endpointing", "transcriber", "llm", "tools", "sentence", "voice", "transport", "other"] as const;
export type Stage = (typeof STAGES)[number];

export interface LatencyTurn {
  turn: number | null;
  greeting: boolean;
  totalMs: number;
  stages: Record<Stage, number>;
  /** LLM time to first token (sum over the turn's LLM calls), for reference. */
  llmFirstTokenMs: number;
}

const ENDPOINTING_KEYS = new Set(["endpointing_wait", "turn_detection", "waiting_for_user"]);

// Processor names look like "SpeachesSTTService#0" / "LocalModelsTTSService#0";
// match the service suffix, since "STTS" also contains "TTS".
function serviceKind(processor: string): "stt" | "llm" | "tts" | null {
  const match = /(STT|TTS|LLM)Service/.exec(processor);
  if (!match) return null;
  return match[1] === "STT" ? "stt" : match[1] === "TTS" ? "tts" : "llm";
}

/**
 * Per-turn stages from pipecat's breakdown, laid on its own timeline.
 *
 * Endpointing (VAD silence + turn detection), transcription and transport are
 * named contributions. The LLM stage runs from the end of the caller's turn to
 * the TTS request that produced the first audio, minus tool execution and the
 * sentence aggregation: a model's time to first token is only the start of it,
 * it must also stream a whole first sentence before the voice can speak. Voice
 * is that TTS request's time to first audio. Whatever is left of the measured
 * total is "other", so the stages always add up.
 */
export function latencyTurns(run: CallRun): LatencyTurn[] {
  return events(run)
    .filter((e) => e.type === LATENCY_BREAKDOWN)
    .map((e) => {
      const p = e.payload;
      const contributions = (p.contributions as Array<Record<string, unknown>>) ?? [];
      const ttfb = (p.ttfb as Array<Record<string, unknown>>) ?? [];
      const calls = (p.function_calls as Array<Record<string, unknown>>) ?? [];
      const aggregation = p.text_aggregation as Record<string, unknown> | null | undefined;
      const stages: Record<Stage, number> = {
        endpointing: 0, transcriber: 0, llm: 0, tools: 0, sentence: 0, voice: 0, transport: 0, other: 0,
      };

      let turnEnd = 0; // epoch seconds when the caller's turn was released
      let sttTtfb = 0;
      for (const c of contributions) {
        const duration = num(c.duration_secs);
        const key = str(c.key);
        if (ENDPOINTING_KEYS.has(key)) stages.endpointing += duration * 1000;
        else if (key === "output_transport") stages.transport += duration * 1000;
        else if (key === "transcription") stages.transcriber += duration * 1000;
        if (ENDPOINTING_KEYS.has(key) || key === "transcription") {
          turnEnd = Math.max(turnEnd, num(c.start_time) + duration);
        }
      }
      const llmCalls = ttfb.filter((t) => serviceKind(str(t.processor)) === "llm");
      const ttsCalls = ttfb.filter((t) => serviceKind(str(t.processor)) === "tts");
      for (const t of ttfb) {
        if (serviceKind(str(t.processor)) === "stt") sttTtfb = Math.max(sttTtfb, num(t.duration_secs) * 1000);
      }
      if (!stages.transcriber) stages.transcriber = sttTtfb;
      stages.tools = calls.reduce((sum, c) => sum + num(c.duration_secs) * 1000, 0);
      stages.sentence = aggregation ? num(aggregation.duration_secs) * 1000 : 0;
      const llmFirstTokenMs = llmCalls.reduce((sum, t) => sum + num(t.duration_secs) * 1000, 0);

      // The TTS request that produced the first audio is the last one issued.
      const firstAudio = ttsCalls.reduce<Record<string, unknown> | null>(
        (last, t) => (!last || num(t.start_time) > num(last.start_time) ? t : last),
        null,
      );
      stages.voice = firstAudio ? num(firstAudio.duration_secs) * 1000 : 0;
      if (llmCalls.length && firstAudio) {
        const llmRequest = Math.min(...llmCalls.map((t) => num(t.start_time)));
        const llmStart = Math.max(llmRequest, turnEnd || llmRequest);
        stages.llm = Math.max(0, (num(firstAudio.start_time) - llmStart) * 1000 - stages.tools - stages.sentence);
      } else {
        stages.llm = llmFirstTokenMs;
      }

      const totalMs = num(p.total_secs) * 1000;
      const named = STAGES.filter((s) => s !== "other").reduce((sum, s) => sum + stages[s], 0);
      stages.other = Math.max(0, totalMs - named);
      return {
        turn: e.turn ?? null,
        greeting: p.measured_from === "client_connected",
        totalMs: Math.max(totalMs, named),
        stages,
        llmFirstTokenMs,
      };
    });
}

export function averageFirstToken(turns: LatencyTurn[]): number {
  const replies = turns.filter((t) => !t.greeting && t.llmFirstTokenMs > 0);
  return replies.length ? replies.reduce((s, t) => s + t.llmFirstTokenMs, 0) / replies.length : 0;
}

export function averageStages(turns: LatencyTurn[]): { count: number; totalMs: number; stages: Record<Stage, number> } {
  const replies = turns.filter((t) => !t.greeting);
  const avg = (pick: (t: LatencyTurn) => number) =>
    replies.length ? replies.reduce((s, t) => s + pick(t), 0) / replies.length : 0;
  const stages = Object.fromEntries(STAGES.map((s) => [s, avg((t) => t.stages[s])])) as Record<Stage, number>;
  return { count: replies.length, totalMs: avg((t) => t.totalMs), stages };
}

// ------------------------------------------------------------------ events

export type EventCategory = "transcript" | "agent" | "tool" | "node" | "latency" | "error" | "system";

export interface EventRow {
  index: number;
  timeMs: number | null;
  offset: number | null;
  category: EventCategory;
  label: string;
  summary: string;
  node?: string;
  turn?: number;
  raw: FeedbackEvent;
}

const EVENT_LABELS: Record<string, [EventCategory, string]> = {
  "rtf-user-transcription": ["transcript", "User transcript"],
  "rtf-bot-text": ["agent", "Agent speech"],
  "rtf-function-call-start": ["tool", "Tool call started"],
  "rtf-function-call-end": ["tool", "Tool call completed"],
  "rtf-node-transition": ["node", "Node transition"],
  "rtf-ttfb-metric": ["latency", "LLM time to first token"],
  "rtf-latency-measured": ["latency", "Response latency"],
  [LATENCY_BREAKDOWN]: ["latency", "Latency breakdown"],
  "rtf-pipeline-error": ["error", "Pipeline error"],
  "rtf-interrupt-warning": ["system", "Interruption"],
  [RECORDING_STARTED]: ["system", "Recording started"],
};

function eventSummary(e: FeedbackEvent): string {
  const p = e.payload;
  switch (e.type) {
    case "rtf-user-transcription":
    case "rtf-bot-text":
      return str(p.text) + (p.interrupted === true ? "  (interrupted)" : "");
    case "rtf-function-call-start":
      return `${str(p.function_name)}(${typeof p.arguments === "string" ? p.arguments : JSON.stringify(p.arguments ?? {})})`;
    case "rtf-function-call-end":
      return `${str(p.function_name)} → ${typeof p.result === "string" ? p.result : JSON.stringify(p.result)}`;
    case "rtf-node-transition":
      return `${str(p.previous_node_name) || "start"} → ${str(p.node_name)}`;
    case "rtf-ttfb-metric":
      return `${Math.round(num(p.ttfb_seconds) * 1000)} ms · ${str(p.model) || str(p.processor)}`;
    case "rtf-latency-measured":
      return `${Math.round(num(p.latency_seconds) * 1000)} ms from user silence to agent speech`;
    case LATENCY_BREAKDOWN:
      return `${Math.round(num(p.total_secs) * 1000)} ms total`;
    case "rtf-pipeline-error":
      return str(p.error);
    default:
      return "";
  }
}

export function eventRows(run: CallRun, anchor: RecordingAnchor | null): EventRow[] {
  return events(run).map((e, index) => {
    const timeMs = ms(e.timestamp);
    const [category, label] = EVENT_LABELS[e.type] ?? ["system", e.type];
    return {
      index,
      timeMs,
      offset: timeMs !== null && anchor ? (timeMs - anchor.epochMs) / 1000 : null,
      category,
      label,
      summary: eventSummary(e),
      node: e.node_name,
      turn: e.turn,
      raw: e,
    };
  });
}

// ------------------------------------------------------------------- usage

export interface UsageSummary {
  callSeconds: number | null;
  llm: Array<{ model: string; processor: string; prompt: number; completion: number; cached: number; total: number }>;
  tts: Array<{ model: string; processor: string; characters: number }>;
  userSpeechSeconds: number;
  agentSpeechSeconds: number;
  toolCalls: number;
}

function splitKey(key: string): { processor: string; model: string } {
  const [processor, model] = key.split("|||");
  return { processor: processor ?? key, model: model ?? "" };
}

export function usageSummary(run: CallRun, timeline: TimelineItem[]): UsageSummary {
  const usage = (run.usage_info ?? {}) as Record<string, unknown>;
  const llm = Object.entries((usage.llm as Record<string, Record<string, unknown>>) ?? {}).map(([key, v]) => ({
    ...splitKey(key),
    prompt: num(v.prompt_tokens),
    completion: num(v.completion_tokens),
    cached: num(v.cache_read_input_tokens),
    total: num(v.total_tokens),
  }));
  const tts = Object.entries((usage.tts as Record<string, unknown>) ?? {}).map(([key, v]) => ({
    ...splitKey(key),
    characters: num(v),
  }));
  const speech = (role: "user" | "agent") =>
    timeline
      .filter((i): i is TimelineMessage => i.kind === "message" && i.role === role)
      .reduce((s, m) => s + (m.startMs !== null && m.endMs !== null ? Math.max(0, m.endMs - m.startMs) / 1000 : 0), 0);
  const callSeconds = num(usage.call_duration_seconds) || num(run.cost_info?.call_duration_seconds) || null;
  return {
    callSeconds,
    llm,
    tts,
    userSpeechSeconds: speech("user"),
    agentSpeechSeconds: speech("agent"),
    toolCalls: timeline.filter((i) => i.kind === "tool").length,
  };
}

// --------------------------------------------------------------- analysis

export interface QaResult {
  node: string;
  summary: string;
  score: number | null;
  sentiment: string;
  tags: string[];
  error?: string;
  skipped?: string;
}

export function qaResults(run: CallRun): QaResult[] {
  const results: QaResult[] = [];
  for (const [key, value] of Object.entries(run.annotations ?? {})) {
    if (!key.startsWith("qa_") || typeof value !== "object" || value === null) continue;
    const qa = value as Record<string, unknown>;
    if (qa.skipped) {
      results.push({ node: key.slice(3), summary: "", score: null, sentiment: "", tags: [], skipped: str(qa.reason) || "skipped" });
      continue;
    }
    if (qa.error) {
      results.push({ node: key.slice(3), summary: "", score: null, sentiment: "", tags: [], error: str(qa.error) });
      continue;
    }
    for (const r of Object.values((qa.node_results as Record<string, Record<string, unknown>>) ?? {})) {
      results.push({
        node: str(r.node_name) || key.slice(3),
        summary: str(r.summary),
        score: typeof r.score === "number" ? r.score : null,
        sentiment: str(r.overall_sentiment),
        tags: Array.isArray(r.tags) ? (r.tags as unknown[]).map(String) : [],
      });
    }
  }
  return results;
}

const INTERNAL_CONTEXT_KEYS = new Set([
  "nodes_visited", "trace_url", "call_id", "call_tags", "call_disposition",
  "mapped_call_disposition", "call_duration", "stasis_channel_id", "call_status", "agent_visits",
]);

export function extractedVariables(run: CallRun): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(run.gathered_context ?? {}).filter(([key]) => !INTERNAL_CONTEXT_KEYS.has(key)),
  );
}

// -------------------------------------------------------------- formatting

export function formatOffset(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "";
  const sign = seconds < 0 ? "-" : "+";
  const s = Math.abs(seconds);
  const m = Math.floor(s / 60);
  return `${sign}${String(m).padStart(2, "0")}:${(s - m * 60).toFixed(2).padStart(5, "0")}`;
}

export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
