"use client";

import { format } from "date-fns";
import { Info } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { STAGE_META } from "@/brand/call-detail/LatencyTab";
import { type Stage, STAGES } from "@/brand/call-detail/model";
import { client } from "@/client/client.gen";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

// Reporting insights (OxeePhone): latency, consumption, conversation quality,
// tools and routing over 1 / 7 / 30 days ending on the page's date. Data from
// GET /api/v1/oxee/reports/insights.

interface Insights {
  period: { start: string; end: string; days: number; timezone: string };
  calls: { total: number; completed: number; with_errors: number; avg_duration_secs: number | null; total_minutes: number; avg_turns: number | null; truncated: boolean };
  latency: {
    turns: number;
    avg_ms: number | null;
    p50_ms: number | null;
    p90_ms: number | null;
    perceived_p50_ms?: number | null;
    slow_share: number | null;
    slow_threshold_ms: number;
    greeting_avg_ms: number | null;
    llm_first_token_avg_ms: number | null;
    stages: Record<Stage, number>;
  };
  conversation: { agent_messages: number; interrupted: number; interruption_rate: number | null; end_reasons: Array<{ reason: string; count: number }> };
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    cached_tokens: number;
    cache_hit_rate: number | null;
    tokens_per_call: number | null;
    tts_characters: number;
    caller_speech_minutes: number;
    agent_speech_minutes: number;
    models: Array<{ model: string; calls: number; prompt: number; completion: number; cached: number }>;
  };
  tools: Array<{ name: string; calls: number; errors: number; avg_ms: number | null }>;
  routing: {
    pathways: Array<{ workflow: string; from: string; to: string; count: number }>;
    nodes: Array<{ workflow: string; name: string; visits: number }>;
  };
  daily: Array<{ date: string; calls: number; avg_latency_ms: number | null; p90_latency_ms: number | null; prompt_tokens: number; completion_tokens: number }>;
}

const PERIODS = [
  { days: 1, label: "Day" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
] as const;

const n = (v: number) => v.toLocaleString();
const ms = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${n(Math.round(v))} ms`);
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(v < 0.1 ? 1 : 0)}%`);
const compact = (v: number) => Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(v);
const END_REASONS: Record<string, string> = {
  end_call: "Agent ended the call",
  user_hangup: "Caller hung up",
  user_idle_max_duration_exceeded: "Caller silent too long",
  call_duration_exceeded: "Max duration reached",
  pipeline_error: "Pipeline error",
  transfer_call: "Transferred (phone)",
  transfer_agent: "Handed off to another agent",
  voicemail_detected: "Voicemail",
  system_cancelled: "Cancelled by the system",
};

function Tile({ label, value, hint, help }: { label: string; value: string; hint?: ReactNode; help?: string }) {
  return (
    <Card className="gap-1 p-4">
      <p className="flex items-center gap-1 text-xs text-muted-foreground">
        {label}
        {help && (
          <span title={help}>
            <Info className="h-3 w-3" />
          </span>
        )}
      </p>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </Card>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-lg font-semibold">{title}</h3>
        {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

/** Table row with an inline magnitude bar (one hue), value in text ink. */
function BarRow({ label, sub, value, max }: { label: string; sub?: string; value: number; max: number }) {
  return (
    <div className="grid grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)_3rem] items-center gap-3 py-1.5 text-sm">
      <div className="min-w-0">
        <p className="truncate" title={label}>{label}</p>
        {sub && <p className="truncate text-[11px] text-muted-foreground">{sub}</p>}
      </div>
      <div className="h-2 rounded-full bg-muted">
        <div className="h-2 rounded-full bg-[var(--viz-series-1)]" style={{ width: `${max ? Math.max(3, (value / max) * 100) : 0}%` }} />
      </div>
      <span className="text-right tabular-nums">{n(value)}</span>
    </div>
  );
}

function ChartTooltip({ active, payload, label, unit }: { active?: boolean; payload?: Array<{ name: string; value: number; color: string }>; label?: string; unit: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="text-muted-foreground">{p.name}</span>
          <span className="ml-auto pl-3 font-medium tabular-nums">{p.value === null ? "—" : `${n(Math.round(p.value))}${unit}`}</span>
        </p>
      ))}
    </div>
  );
}

const axisTick = { fontSize: 11, fill: "var(--muted-foreground)" };
// Legend text stays in text ink; only the marker carries the series colour.
const legendText = (value: string) => <span className="text-muted-foreground">{value}</span>;

export function CallInsights({ date, timezone, workflowId }: { date: Date; timezone: string; workflowId?: number }) {
  const auth = useAuth();
  const [days, setDays] = useState<1 | 7 | 30>(7);
  const [data, setData] = useState<Insights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      const response = await client.get<{ 200: Insights }, unknown>({
        url: "/api/v1/oxee/reports/insights",
        query: { date: format(date, "yyyy-MM-dd"), timezone, days, ...(workflowId ? { workflow_id: workflowId } : {}) },
      });
      if (cancelled) return;
      if (response.error) setError(detailFromError(response.error, "Could not load insights"));
      else setData(response.data as Insights);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [auth.loading, auth.isAuthenticated, date, timezone, days, workflowId]);

  const header = (
    <div className="flex flex-wrap items-end justify-between gap-3 border-t border-border pt-6">
      <div>
        <h2 className="text-2xl font-bold">Insights</h2>
        <p className="text-sm text-muted-foreground">
          {data ? `${data.period.start === data.period.end ? data.period.end : `${data.period.start} → ${data.period.end}`} · ${data.period.timezone}` : "Latency, consumption and conversation quality"}
        </p>
      </div>
      <div className="flex overflow-hidden rounded-md border border-border text-sm" role="tablist" aria-label="Period">
        {PERIODS.map((p) => (
          <button
            key={p.days}
            type="button"
            role="tab"
            aria-selected={days === p.days}
            onClick={() => setDays(p.days)}
            className={cn("px-3 py-1.5", days === p.days ? "bg-muted font-semibold" : "text-muted-foreground hover:bg-muted/60")}
          >
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );

  if (loading) {
    return (
      <div className="space-y-4">
        {header}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-[96px]" />
          ))}
        </div>
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="space-y-4">
        {header}
        <Card className="p-6 text-center text-sm text-destructive">{error ?? "No data"}</Card>
      </div>
    );
  }
  if (!data.calls.total) {
    return (
      <div className="space-y-4">
        {header}
        <Card className="p-6 text-center text-sm text-muted-foreground">No calls in this period.</Card>
      </div>
    );
  }

  const { calls, latency, conversation, usage, tools, routing } = data;
  const stages = STAGES.filter((s) => latency.stages[s] > 0);
  // The end-of-turn wait is a setting: listed, but not part of the reply bar.
  const counted = stages.filter((s) => s !== "endpointing");
  const stageTotal = counted.reduce((sum, s) => sum + latency.stages[s], 0) || 1;
  const trend = data.daily.map((d) => ({ ...d, label: format(new Date(`${d.date}T12:00:00`), "MMM d") }));
  const showTrends = data.period.days > 1 && trend.length > 1;
  const endMax = Math.max(0, ...conversation.end_reasons.map((r) => r.count));
  const pathMax = Math.max(0, ...routing.pathways.map((p) => p.count));
  const nodeMax = Math.max(0, ...routing.nodes.map((p) => p.visits));
  const multiAgent = new Set([...routing.pathways.map((p) => p.workflow), ...routing.nodes.map((p) => p.workflow)]).size > 1;

  return (
    <div className="space-y-8">
      {header}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile label="Calls" value={n(calls.total)} hint={`${n(calls.completed)} completed · ${calls.total_minutes} min`} />
        <Tile
          label="Reply time (median)"
          value={ms(latency.p50_ms)}
          hint={`avg ${ms(latency.avg_ms)} · p90 ${ms(latency.p90_ms)}${latency.perceived_p50_ms != null ? ` · heard ${ms(latency.perceived_p50_ms)}` : ""}`}
          help="From the end of the caller's turn to the agent speaking, per reply. The end-of-turn wait, a setting of the agent, is not counted; 'heard' includes it."
        />
        <Tile
          label="Slow replies"
          value={pct(latency.slow_share)}
          hint={`over ${n(latency.slow_threshold_ms / 1000)} s · ${n(latency.turns)} replies measured`}
        />
        <Tile
          label="Interruptions"
          value={pct(conversation.interruption_rate)}
          hint={`${n(conversation.interrupted)} of ${n(conversation.agent_messages)} agent messages`}
          help="Agent messages the caller cut off."
        />
        <Tile label="LLM tokens" value={compact(usage.prompt_tokens + usage.completion_tokens)} hint={`${usage.tokens_per_call !== null ? n(usage.tokens_per_call) : "—"} per call`} />
        <Tile
          label="Prompt cache hit rate"
          value={pct(usage.cache_hit_rate)}
          hint={`${compact(usage.cached_tokens)} of ${compact(usage.prompt_tokens)} input tokens`}
          help="Share of input tokens served from the model server's prompt cache."
        />
        <Tile label="Avg call duration" value={calls.avg_duration_secs !== null ? `${Math.round(calls.avg_duration_secs)} s` : "—"} hint={calls.avg_turns !== null ? `${calls.avg_turns} caller turns per call` : undefined} />
        <Tile label="Calls with errors" value={n(calls.with_errors)} hint={calls.total ? `${pct(calls.with_errors / calls.total)} of calls` : undefined} />
      </div>
      {calls.truncated && <p className="text-xs text-muted-foreground">Computed on the 5,000 most recent calls of the period.</p>}

      <Section title="Latency" subtitle="Where the reply time goes, from the end of the caller's turn to the agent speaking (average per reply). The end-of-turn wait is a setting of the agent, shown apart.">
        <Card className="space-y-4 p-4">
          <div className="flex h-4 w-full gap-[2px] overflow-hidden rounded-full" role="img" aria-label="Average latency by stage">
            {counted.map((s) => (
              <div
                key={s}
                title={`${STAGE_META[s].label}: ${ms(latency.stages[s])}`}
                style={{ width: `${(latency.stages[s] / stageTotal) * 100}%`, background: STAGE_META[s].color }}
              />
            ))}
          </div>
          <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
            {stages.map((s) => (
              <div key={s} className={`flex items-center gap-2 text-sm ${s === "endpointing" ? "opacity-60" : ""}`} title={STAGE_META[s].help}>
                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: STAGE_META[s].color }} />
                <span className="text-muted-foreground">{STAGE_META[s].label}</span>
                <span className="ml-auto font-medium tabular-nums">{ms(latency.stages[s])}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            LLM first token: {ms(latency.llm_first_token_avg_ms)} on average (the LLM stage also covers streaming until the first sentence). Greeting: {ms(latency.greeting_avg_ms)} after the call connects.
          </p>
        </Card>
        {showTrends && (
          <Card className="p-4">
            <p className="mb-2 text-sm font-medium">Response latency per day</p>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trend} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
                  <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={false} />
                  <YAxis tick={axisTick} tickLine={false} axisLine={false} width={48} tickFormatter={(v: number) => `${(v / 1000).toFixed(1)}s`} />
                  <Tooltip content={<ChartTooltip unit=" ms" />} cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} formatter={legendText} />
                  <Line name="Average" dataKey="avg_latency_ms" stroke="var(--viz-series-1)" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} connectNulls />
                  <Line name="p90" dataKey="p90_latency_ms" stroke="var(--viz-series-2)" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
        )}
      </Section>

      <Section title="Consumption" subtitle="What the calls used on the model endpoints — to size the inference servers.">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Tile label="Input tokens" value={compact(usage.prompt_tokens)} hint={`${compact(usage.cached_tokens)} cached`} />
          <Tile label="Output tokens" value={compact(usage.completion_tokens)} />
          <Tile label="Speech transcribed" value={`${usage.caller_speech_minutes} min`} hint="Caller speech" />
          <Tile label="Speech synthesized" value={`${usage.agent_speech_minutes} min`} hint={`${compact(usage.tts_characters)} characters`} />
        </div>
        {showTrends && (
          <Card className="p-4">
            <p className="mb-2 text-sm font-medium">LLM tokens per day</p>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={trend} margin={{ top: 8, right: 16, left: 0, bottom: 0 }} barCategoryGap="30%">
                  <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
                  <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={false} />
                  <YAxis tick={axisTick} tickLine={false} axisLine={false} width={48} tickFormatter={(v: number) => compact(v)} />
                  <Tooltip content={<ChartTooltip unit="" />} cursor={{ fill: "var(--muted)", opacity: 0.4 }} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} formatter={legendText} />
                  <Bar name="Input" dataKey="prompt_tokens" stackId="t" fill="var(--viz-series-1)" stroke="var(--card)" strokeWidth={2} />
                  <Bar name="Output" dataKey="completion_tokens" stackId="t" fill="var(--viz-series-2)" stroke="var(--card)" strokeWidth={2} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        )}
        <Card className="overflow-hidden p-0">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Model</th>
                <th className="px-4 py-2 text-right font-medium">Calls</th>
                <th className="px-4 py-2 text-right font-medium">Input</th>
                <th className="px-4 py-2 text-right font-medium">Cached</th>
                <th className="px-4 py-2 text-right font-medium">Output</th>
              </tr>
            </thead>
            <tbody>
              {usage.models.map((m) => (
                <tr key={m.model} className="border-t border-border/50">
                  <td className="px-4 py-2 font-medium">{m.model}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{n(m.calls)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{n(m.prompt)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">{n(m.cached)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{n(m.completion)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </Section>

      <div className="grid gap-8 lg:grid-cols-2">
        <Section title="Tools" subtitle="Business tools called by the agents (routing excluded).">
          <Card className="overflow-hidden p-0">
            {tools.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">No tool calls.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-muted/40 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium">Tool</th>
                    <th className="px-4 py-2 text-right font-medium">Calls</th>
                    <th className="px-4 py-2 text-right font-medium">Errors</th>
                    <th className="px-4 py-2 text-right font-medium">Avg time</th>
                  </tr>
                </thead>
                <tbody>
                  {tools.map((t) => (
                    <tr key={t.name} className="border-t border-border/50">
                      <td className="px-4 py-2 font-mono text-xs">{t.name}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{n(t.calls)}</td>
                      <td className={cn("px-4 py-2 text-right tabular-nums", t.errors > 0 && "font-medium text-destructive")}>
                        {n(t.errors)}
                        {t.errors > 0 && ` (${pct(t.errors / t.calls)})`}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">{ms(t.avg_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </Section>

        <Section title="How calls ended">
          <Card className="px-4 py-2">
            {conversation.end_reasons.length === 0 ? (
              <p className="py-2 text-sm text-muted-foreground">No end status recorded.</p>
            ) : (
              conversation.end_reasons.map((r) => (
                <BarRow key={r.reason} label={END_REASONS[r.reason] ?? r.reason.replace(/_/g, " ")} value={r.count} max={endMax} />
              ))
            )}
          </Card>
        </Section>

        <Section title="Pathways taken" subtitle="Most frequent moves between nodes.">
          <Card className="px-4 py-2">
            {routing.pathways.length === 0 ? (
              <p className="py-2 text-sm text-muted-foreground">No node transitions.</p>
            ) : (
              routing.pathways.map((p) => (
                <BarRow key={`${p.workflow}-${p.from}-${p.to}`} label={`${p.from} → ${p.to}`} sub={multiAgent ? p.workflow : undefined} value={p.count} max={pathMax} />
              ))
            )}
          </Card>
        </Section>

        <Section title="Nodes visited" subtitle="Where conversations spend their turns.">
          <Card className="px-4 py-2">
            {routing.nodes.map((p) => (
              <BarRow key={`${p.workflow}-${p.name}`} label={p.name} sub={multiAgent ? p.workflow : undefined} value={p.visits} max={nodeMax} />
            ))}
          </Card>
        </Section>
      </div>
    </div>
  );
}
