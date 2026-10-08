import { describe, expect, it } from "vitest";

import run8 from "./__fixtures__/run8.json";
import {
  activeMessageId,
  averageStages,
  buildTimeline,
  type CallRun,
  eventRows,
  extractedVariables,
  formatOffset,
  latencyTurns,
  recordingAnchor,
  STAGES,
  type TimelineMessage,
  type TimelineToolCall,
  usageSummary,
  VOICE_STATS,
  voiceFluency,
} from "./model";

// A real call recorded on the local stack with Oxeegen models (scrubbed).
const run = run8 as unknown as CallRun;

describe("recording anchor", () => {
  it("uses the recording-start marker when present", () => {
    const anchor = recordingAnchor(run)!;
    expect(anchor.source).toBe("marker");
    expect(new Date(anchor.epochMs).toISOString()).toBe("2026-09-30T16:45:56.099Z");
  });

  it("falls back to aligning the first bot message with the bot track onset", () => {
    const legacy: CallRun = {
      ...run,
      logs: { realtime_feedback_events: run.logs!.realtime_feedback_events!.filter((e) => e.type !== "oxee-recording-started") },
    };
    const anchor = recordingAnchor(legacy, 0.95)!;
    expect(anchor.source).toBe("bot-onset");
    // first bot speech starts at 16:45:57.070
    expect(new Date(anchor.epochMs).toISOString()).toBe("2026-09-30T16:45:56.120Z");
    expect(recordingAnchor(legacy)!.source).toBe("first-event");
  });
});

describe("timeline", () => {
  const timeline = buildTimeline(run, recordingAnchor(run));
  const messages = timeline.filter((i): i is TimelineMessage => i.kind === "message");

  it("places messages on the recording with start/end offsets", () => {
    expect(messages[0]).toMatchObject({ role: "agent", text: expect.stringContaining("cabinet du docteur Martin") });
    expect(messages[0].start).toBeCloseTo(0.971, 2);
    expect(messages[0].end).toBeCloseTo(5.452, 2);
    expect(messages[1].role).toBe("user");
    expect(messages.every((m, i) => i === 0 || (m.startMs ?? 0) >= (messages[i - 1].startMs ?? 0))).toBe(true);
  });

  it("pairs tool calls and parses their JSON", () => {
    const tool = timeline.find((i): i is TimelineToolCall => i.kind === "tool")!;
    expect(tool.name).toBe("check_availability");
    expect(tool.status).toBe("completed");
    expect(tool.durationMs).not.toBeNull();
    expect(JSON.stringify(tool.result)).toContain("11h15");
  });

  it("flags interrupted agent messages and attaches turn latency", () => {
    expect(messages.filter((m) => m.interrupted)).toHaveLength(2);
    // Reply time: 2.159 s heard, minus the 0.55 s end-of-turn wait.
    expect(messages.find((m) => m.role === "agent" && m.turn === 2)?.latencySecs).toBeCloseTo(1.608, 2);
  });

  it("finds the message being heard", () => {
    expect(activeMessageId(timeline, 3)).toBe(messages[0].id);
    expect(activeMessageId(timeline, 0.2)).toBeNull();
  });
});

describe("latency", () => {
  const turns = latencyTurns(run);

  it("builds stages that add up to the measured total", () => {
    expect(turns).toHaveLength(6);
    expect(turns[0].greeting).toBe(true);
    const t2 = turns.find((t) => t.turn === 2)!;
    expect(t2.stages.endpointing).toBeCloseTo(550, 0);
    expect(t2.stages.transcriber).toBeCloseTo(291, 0);
    expect(t2.stages.voice).toBeCloseTo(383, 0);
    // LLM covers first token *and* streaming until the first sentence.
    expect(t2.llmFirstTokenMs).toBeCloseTo(329, 0);
    expect(t2.stages.llm).toBeGreaterThan(t2.llmFirstTokenMs);
    // The stages add up to what the caller hears; the reply time leaves out
    // the end-of-turn wait (a setting).
    const sum = STAGES.reduce((s, k) => s + t2.stages[k], 0);
    expect(sum).toBeCloseTo(t2.perceivedMs, 0);
    expect(t2.totalMs).toBeCloseTo(t2.perceivedMs - t2.stages.endpointing, 0);
    // The timeline accounts for (almost) everything: little is left over.
    expect(t2.stages.other).toBeLessThan(0.1 * t2.perceivedMs);
  });

  it("averages replies only (not the greeting)", () => {
    const avg = averageStages(turns);
    expect(avg.count).toBe(5);
    expect(avg.stages.llm).toBeGreaterThan(0);
  });

  it("counts tool time in the turn that called the tool", () => {
    expect(turns.find((t) => t.turn === 3)!.stages.tools).toBeGreaterThan(0);
  });
});

describe("events, usage, analysis", () => {
  it("labels every event with an offset", () => {
    const rows = eventRows(run, recordingAnchor(run));
    expect(rows).toHaveLength(run.logs!.realtime_feedback_events!.length);
    expect(rows.find((r) => r.raw.type === "rtf-function-call-start")?.summary).toContain("check_availability(");
    expect(rows[0].label).toBe("Recording started");
  });

  it("summarises usage", () => {
    const usage = usageSummary(run, buildTimeline(run, recordingAnchor(run)));
    expect(usage.llm[0]).toMatchObject({ model: "Oxee-flash", prompt: 4290, completion: 1089 });
    expect(usage.toolCalls).toBe(1);
    expect(usage.userSpeechSeconds).toBeGreaterThan(5);
  });

  it("hides internal context keys", () => {
    expect(Object.keys(extractedVariables(run))).not.toContain("nodes_visited");
  });

  it("formats offsets like the recording clock", () => {
    expect(formatOffset(5.1)).toBe("+00:05.10");
    expect(formatOffset(75.456)).toBe("+01:15.46");
  });
});

describe("sentence aggregation", () => {
  it("becomes its own stage when recorded", () => {
    const events = run.logs!.realtime_feedback_events!.map((e) =>
      e.type === "oxee-latency-breakdown" && e.turn === 2
        ? { ...e, payload: { ...e.payload, text_aggregation: { processor: "TTS", start_time: 0, duration_secs: 0.4 } } }
        : e,
    );
    const t2 = latencyTurns({ ...run, logs: { realtime_feedback_events: events } }).find((t) => t.turn === 2)!;
    expect(t2.stages.sentence).toBeCloseTo(400, 0);
    expect(STAGES.reduce((s, k) => s + t2.stages[k], 0)).toBeCloseTo(t2.perceivedMs, 0);
  });
});

describe("voice fluency", () => {
  it("sums the sentences of each reply", () => {
    const stat = (context_id: string, synthesis_ms: number, audio_ms: number, gaps = 0) => ({
      type: VOICE_STATS,
      timestamp: "2026-10-08T10:00:00Z",
      payload: { context_id, synthesis_ms, audio_ms, speed: audio_ms / synthesis_ms, gaps, gap_ms: gaps * 100 },
    });
    const voice = voiceFluency({
      ...run,
      logs: { realtime_feedback_events: [stat("a", 400, 1600), stat("a", 600, 1200, 1), stat("b", 500, 2000)] },
    })!;
    expect(voice.replies).toBe(2);
    expect(voice.speed).toBeCloseTo(3.2, 2);
    expect(voice.speedMin).toBe(2);
    expect(voice.repliesWithGaps).toBe(1);
    expect(voice.replySynthesisMs).toEqual([500, 1000]);
    expect(voiceFluency(run)).toBeNull();
  });
});
