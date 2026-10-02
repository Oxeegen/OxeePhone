"use client";

import { CheckCircle2, CircleDashed, CircleSlash, Info, Loader2, MinusCircle, XCircle } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";

import { client } from "@/client/client.gen";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { type ExecutionStatus, type SettingsResponse, STATUS_LABEL, type Verdict, VERDICT_META } from "./model";

export const API = "/api/v1/oxee/tests";

export function useTestSettings() {
  const auth = useAuth();
  const [data, setData] = useState<SettingsResponse | null>(null);
  const reload = useCallback(async () => {
    const response = await client.get<{ 200: SettingsResponse }, unknown>({ url: `${API}/settings` });
    if (response.data) setData(response.data as SettingsResponse);
  }, []);
  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    void reload();
  }, [auth.loading, auth.isAuthenticated, reload]);
  return { data, reload };
}

/** Min / max on one track: two native range inputs stacked. */
export function RangeSlider({
  min,
  max,
  step = 1,
  value,
  onChange,
  format = String,
  label,
}: {
  min: number;
  max: number;
  step?: number;
  value: [number, number];
  onChange: (value: [number, number]) => void;
  format?: (v: number) => string;
  label: string;
}) {
  const [lo, hi] = value;
  const at = (v: number) => ((v - min) / (max - min)) * 100;
  const thumb =
    "pointer-events-none absolute inset-0 h-5 w-full appearance-none bg-transparent [&::-moz-range-thumb]:pointer-events-auto [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:cursor-pointer [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-[var(--cta)] [&::-moz-range-thumb]:bg-background [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-[var(--cta)] [&::-webkit-slider-thumb]:bg-background";
  return (
    <div className="relative h-5">
      <div className="absolute top-1/2 h-1.5 w-full -translate-y-1/2 rounded-full bg-muted" />
      <div
        className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-[var(--cta)]"
        style={{ left: `${at(lo)}%`, width: `${Math.max(at(hi) - at(lo), 0)}%` }}
      />
      <input
        type="range"
        aria-label={`${label} minimum`}
        aria-valuetext={format(lo)}
        min={min}
        max={max}
        step={step}
        value={lo}
        onChange={(e) => onChange([Math.min(Number(e.target.value), hi), hi])}
        className={cn(thumb, lo === max && "z-10")}
      />
      <input
        type="range"
        aria-label={`${label} maximum`}
        aria-valuetext={format(hi)}
        min={min}
        max={max}
        step={step}
        value={hi}
        onChange={(e) => onChange([lo, Math.max(Number(e.target.value), lo)])}
        className={thumb}
      />
    </div>
  );
}

const VERDICT_ICON: Record<Verdict, typeof CheckCircle2> = { pass: CheckCircle2, partial: MinusCircle, fail: XCircle };

export function VerdictBadge({ verdict, compact = false }: { verdict: Verdict | null | undefined; compact?: boolean }) {
  if (!verdict) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" title="The judge did not answer">
        <CircleDashed className="h-3.5 w-3.5" /> {compact ? "" : "Not judged"}
      </span>
    );
  }
  const meta = VERDICT_META[verdict];
  const Icon = VERDICT_ICON[verdict];
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium", meta.className)}>
      <Icon className="h-3.5 w-3.5" /> {meta.label}
    </span>
  );
}

export function ExecutionStatusBadge({ status, progress }: { status: ExecutionStatus; progress?: { total: number; finished: number } }) {
  const running = status === "queued" || status === "running";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
        status === "failed" || status === "interrupted" ? "border-red-500/40 text-red-700 dark:text-red-300" : "border-border text-muted-foreground",
      )}
    >
      {running ? <Loader2 className="h-3 w-3 animate-spin" /> : status === "cancelled" ? <CircleSlash className="h-3 w-3" /> : null}
      {STATUS_LABEL[status]}
      {running && progress ? ` ${progress.finished}/${progress.total}` : ""}
    </span>
  );
}

/** Pass / partial / fail split of a set of calls (status colours + labels). */
export function VerdictSplit({ verdicts, className }: { verdicts: Record<Verdict, number> | null | undefined; className?: string }) {
  const total = verdicts ? verdicts.pass + verdicts.partial + verdicts.fail : 0;
  if (!verdicts || !total) return <span className="text-xs text-muted-foreground">—</span>;
  const parts: Array<[Verdict, string]> = [
    ["pass", "bg-emerald-500"],
    ["partial", "bg-amber-400"],
    ["fail", "bg-red-500"],
  ];
  return (
    <div className={cn("space-y-1", className)}>
      <div className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full" title={parts.map(([k]) => `${VERDICT_META[k].label}: ${verdicts[k]}`).join(" · ")}>
        {parts.map(([k, color]) =>
          verdicts[k] ? <div key={k} className={cn("h-2", color)} style={{ width: `${(verdicts[k] / total) * 100}%` }} /> : null,
        )}
      </div>
      <p className="flex flex-wrap gap-x-2 text-[11px] text-muted-foreground">
        {parts.map(([k]) => (
          <span key={k}>
            {VERDICT_META[k].label} {verdicts[k]}
          </span>
        ))}
      </p>
    </div>
  );
}

export function Tile({ label, value, hint, help }: { label: string; value: ReactNode; hint?: ReactNode; help?: string }) {
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
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="text-[11px] text-muted-foreground">{hint}</div>}
    </Card>
  );
}

export function Section({ title, subtitle, children, actions }: { title: string; subtitle?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h3 className="text-lg font-semibold">{title}</h3>
          {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** Row with an inline magnitude bar (one hue); the value stays in text ink. */
export function MeterRow({ label, sub, value, max, display }: { label: ReactNode; sub?: ReactNode; value: number; max: number; display: string }) {
  return (
    <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_4.5rem] items-center gap-3 py-1.5 text-sm" title={`${typeof label === "string" ? label : ""} ${display}`}>
      <div className="min-w-0">
        <div className="line-clamp-2">{label}</div>
        {sub && <div className="truncate text-[11px] text-muted-foreground">{sub}</div>}
      </div>
      <div className="h-2 rounded-full bg-muted">
        <div className="h-2 rounded-full bg-[var(--viz-series-1)]" style={{ width: `${max ? Math.max(value > 0 ? 3 : 0, (value / max) * 100) : 0}%` }} />
      </div>
      <span className="text-right tabular-nums">{display}</span>
    </div>
  );
}

export function LevelChips({ levels, speed }: { levels: Record<string, number>; speed?: number | null }) {
  const keys = ["vocabulary", "mood", "clarity", "complexity", "depth", "impatience", "dictation", "traps"];
  const short: Record<string, string> = {
    vocabulary: "Voc",
    mood: "Mood",
    clarity: "Clar",
    complexity: "Cplx",
    depth: "Depth",
    impatience: "Imp",
    dictation: "Dict",
    traps: "Trap",
  };
  return (
    <span className="inline-flex flex-wrap gap-1">
      {keys
        .filter((k) => levels?.[k] !== undefined)
        .map((k) => (
          <span key={k} className="rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-muted-foreground" title={k}>
            {short[k]} {levels[k]}
          </span>
        ))}
      {speed ? (
        <span className="rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-muted-foreground" title="Voice speed">
          ×{speed.toFixed(2)}
        </span>
      ) : null}
    </span>
  );
}
