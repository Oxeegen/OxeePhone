"use client";

import { AudioLines, Bot, Info, Mic, MoreHorizontal, Send, Timer, Type, Wrench } from "lucide-react";
import type { ComponentType } from "react";

import { averageFirstToken, averageStages, type LatencyTurn, type Stage, STAGES } from "./model";

const STAGE_META: Record<Stage, { label: string; color: string; icon: ComponentType<{ className?: string }>; help: string }> = {
  endpointing: {
    label: "Endpointing",
    color: "#22C55E",
    icon: Timer,
    help: "Deciding the caller has finished: VAD silence + turn detection.",
  },
  transcriber: {
    label: "Transcriber",
    color: "#F97316",
    icon: Mic,
    help: "Speech-to-text: time to the final transcript of the caller's turn.",
  },
  llm: {
    label: "LLM",
    color: "#EAB308",
    icon: Bot,
    help: "Language model: from the end of the caller's turn until its first sentence is ready (first token, then streaming; all LLM calls of the turn).",
  },
  tools: { label: "Tools", color: "#EC4899", icon: Wrench, help: "Tool / function execution during the turn." },
  sentence: {
    label: "First sentence",
    color: "#14B8A6",
    icon: Type,
    help: "LLM streaming until the first complete sentence the voice can speak.",
  },
  voice: { label: "Voice", color: "#3B82F6", icon: AudioLines, help: "Text-to-speech: time to the first audio." },
  transport: { label: "Transport", color: "#A855F7", icon: Send, help: "Sending the first audio to the caller." },
  other: {
    label: "Other",
    color: "#94A3B8",
    icon: MoreHorizontal,
    help: "Pipeline time between stages (text aggregation, queuing...). Stages always add up to the total.",
  },
};

const fmt = (msValue: number) => `${Math.round(msValue)}ms`;

export function LatencyTab({ turns }: { turns: LatencyTurn[] }) {
  if (!turns.length) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        No latency breakdown for this call (recorded for calls made with OxeePhone call insights enabled).
      </p>
    );
  }
  const avg = averageStages(turns);
  const firstToken = averageFirstToken(turns);
  const shown = STAGES.filter((s) => turns.some((t) => t.stages[s] > 0));
  const barTotal = shown.reduce((sum, s) => sum + avg.stages[s], 0) || 1;

  return (
    <div className="space-y-5 py-2">
      <div className="rounded-xl border border-border/70 p-4">
        <div className="mb-3 flex items-baseline justify-between">
          <h3 className="font-semibold">Latency breakdown</h3>
          <span className="text-sm text-muted-foreground">
            Average response: <span className="font-semibold text-foreground">{fmt(avg.totalMs)}</span> over {avg.count} turn{avg.count > 1 ? "s" : ""}
          </span>
        </div>
        <div className="flex h-3 w-full overflow-hidden rounded-full">
          {shown.map((s) => (
            <div
              key={s}
              title={`${STAGE_META[s].label}: ${fmt(avg.stages[s])}`}
              style={{ width: `${(avg.stages[s] / barTotal) * 100}%`, background: STAGE_META[s].color }}
            />
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {shown.map((s) => {
          const meta = STAGE_META[s];
          const Icon = meta.icon;
          return (
            <div key={s} className="flex items-center gap-3 rounded-xl border border-border/70 p-4">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: meta.color }} />
              <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1 font-medium">
                  {meta.label}
                  <span title={meta.help}>
                    <Info className="h-3.5 w-3.5 text-muted-foreground" />
                  </span>
                </p>
                <p className="text-xs text-muted-foreground">
                  Avg latency{s === "llm" && firstToken > 0 ? ` · first token ${fmt(firstToken)}` : ""}
                </p>
              </div>
              <span className="rounded-md bg-muted px-2 py-1 font-semibold tabular-nums">{fmt(avg.stages[s])}</span>
            </div>
          );
        })}
      </div>

      <div className="overflow-hidden rounded-xl border border-border/70">
        <div className="flex items-baseline justify-between px-4 py-3">
          <div>
            <h3 className="font-semibold">Latency per turn</h3>
            <p className="text-xs text-muted-foreground">From the caller falling silent to the agent speaking (milliseconds).</p>
          </div>
          <span className="text-sm text-muted-foreground">{turns.length} turns</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-y border-border/70 bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Turn</th>
                <th className="px-4 py-2 text-right font-medium">Total</th>
                {shown.map((s) => (
                  <th key={s} className="px-4 py-2 text-right font-medium">{STAGE_META[s].label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {turns.map((t, i) => (
                <tr key={i} className="border-b border-border/50 last:border-0">
                  <td className="px-4 py-2">{t.greeting ? "Greeting" : `#${t.turn ?? i}`}</td>
                  <td className="px-4 py-2 text-right">
                    <span className="rounded bg-muted px-1.5 py-0.5 font-semibold tabular-nums">{fmt(t.totalMs)}</span>
                  </td>
                  {shown.map((s) => (
                    <td key={s} className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                      {t.stages[s] ? fmt(t.stages[s]) : "—"}
                      {s === "llm" && t.llmFirstTokenMs > 0 && (
                        <span className="block text-[10px] opacity-70">first token {fmt(t.llmFirstTokenMs)}</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="border-t border-border/50 px-4 py-2 text-[11px] text-muted-foreground">
          The greeting is timed from the call connecting and is not included in the averages.
        </p>
      </div>
    </div>
  );
}
