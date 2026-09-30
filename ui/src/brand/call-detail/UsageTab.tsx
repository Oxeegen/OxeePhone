"use client";

import type { UsageSummary } from "./model";

const n = (value: number) => value.toLocaleString();
const secs = (value: number | null) => (value === null ? "—" : `${value.toFixed(value >= 100 ? 0 : 1)} s`);

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-border/70 p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function UsageTab({ usage }: { usage: UsageSummary }) {
  const prompt = usage.llm.reduce((s, m) => s + m.prompt, 0);
  const completion = usage.llm.reduce((s, m) => s + m.completion, 0);
  const cached = usage.llm.reduce((s, m) => s + m.cached, 0);
  const characters = usage.tts.reduce((s, m) => s + m.characters, 0);
  return (
    <div className="space-y-5 py-2">
      <p className="text-sm text-muted-foreground">
        Resources this call consumed on the model endpoints — useful to size the inference servers.
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Call duration" value={secs(usage.callSeconds)} />
        <Stat label="Caller speech (transcribed)" value={secs(usage.userSpeechSeconds)} hint="Sum of the caller's turns" />
        <Stat label="Agent speech (synthesized)" value={secs(usage.agentSpeechSeconds)} hint={`${n(characters)} characters`} />
        <Stat label="Tool calls" value={n(usage.toolCalls)} />
      </div>
      <div className="overflow-x-auto rounded-xl border border-border/70">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Model</th>
              <th className="px-4 py-2 text-left font-medium">Service</th>
              <th className="px-4 py-2 text-right font-medium">Input tokens</th>
              <th className="px-4 py-2 text-right font-medium">of which cached</th>
              <th className="px-4 py-2 text-right font-medium">Output tokens</th>
              <th className="px-4 py-2 text-right font-medium">Characters</th>
            </tr>
          </thead>
          <tbody>
            {usage.llm.map((m) => (
              <tr key={`llm-${m.processor}-${m.model}`} className="border-t border-border/50">
                <td className="px-4 py-2 font-medium">{m.model || "—"}</td>
                <td className="px-4 py-2 text-muted-foreground">{/QAAnalysis/.test(m.processor) ? "Post-call analysis" : "LLM"}</td>
                <td className="px-4 py-2 text-right tabular-nums">{n(m.prompt)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">{n(m.cached)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{n(m.completion)}</td>
                <td className="px-4 py-2 text-right text-muted-foreground">—</td>
              </tr>
            ))}
            {usage.tts.map((m) => (
              <tr key={`tts-${m.processor}-${m.model}`} className="border-t border-border/50">
                <td className="px-4 py-2 font-medium">{m.model || "—"}</td>
                <td className="px-4 py-2 text-muted-foreground">Voice</td>
                <td className="px-4 py-2 text-right text-muted-foreground">—</td>
                <td className="px-4 py-2 text-right text-muted-foreground">—</td>
                <td className="px-4 py-2 text-right text-muted-foreground">—</td>
                <td className="px-4 py-2 text-right tabular-nums">{n(m.characters)}</td>
              </tr>
            ))}
            <tr className="border-t border-border/70 bg-muted/20 font-medium">
              <td className="px-4 py-2" colSpan={2}>Total</td>
              <td className="px-4 py-2 text-right tabular-nums">{n(prompt)}</td>
              <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">{n(cached)}</td>
              <td className="px-4 py-2 text-right tabular-nums">{n(completion)}</td>
              <td className="px-4 py-2 text-right tabular-nums">{n(characters)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
