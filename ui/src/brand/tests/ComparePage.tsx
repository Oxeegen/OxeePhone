"use client";

import { format } from "date-fns";
import { ArrowDownRight, ArrowLeft, ArrowUpRight, GitCompare, Loader2, Minus } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { client } from "@/client/client.gen";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { ChangeCard } from "../versions/DiffViews";
import { type Comparison, type Execution, formatDelta, formatIndicator, type Headline, postValue, versionLabel } from "./model";
import { API, Section, VerdictSplit } from "./ui";

const CHANGE_META: Record<Comparison["scenarios"][number]["change"], { label: string; className: string }> = {
  regressed: { label: "Regressed", className: "border-red-500/40 text-red-700 dark:text-red-300" },
  improved: { label: "Improved", className: "border-emerald-500/40 text-emerald-700 dark:text-emerald-300" },
  same: { label: "Same", className: "border-border text-muted-foreground" },
  new: { label: "New", className: "border-border text-muted-foreground" },
  removed: { label: "Not played", className: "border-border text-muted-foreground" },
  unknown: { label: "Not judged", className: "border-border text-muted-foreground" },
};

function HeadlineCard({ title, subtitle, headline }: { title: string; subtitle: string; headline: Headline }) {
  const trend = (d: number | null) =>
    d === null || d === 0
      ? "text-muted-foreground"
      : d > 0
        ? "text-emerald-700 dark:text-emerald-300"
        : "text-red-700 dark:text-red-300";
  const sign = (d: number | null, digits = 2) => (d === null ? "" : d === 0 ? "=" : `${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(digits)}`);
  const score = (v: number | null) => (v === null ? "—" : v.toFixed(2));
  return (
    <Card className="gap-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">{title}</h3>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-semibold tabular-nums">
            <span className="text-muted-foreground">{score(headline.a)}</span> → {score(headline.b)}
          </p>
          <p className={cn("inline-flex items-center gap-1 text-sm font-medium tabular-nums", trend(headline.delta))}>
            {headline.delta ? (headline.delta > 0 ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />) : null}
            {sign(headline.delta)}
            {headline.delta ? <span className="sr-only">{headline.delta > 0 ? "better" : "worse"}</span> : null}
          </p>
        </div>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th className="py-1 font-medium" />
            <th className="py-1 text-right font-medium">A</th>
            <th className="py-1 text-right font-medium">B</th>
            <th className="py-1 text-right font-medium">Change</th>
          </tr>
        </thead>
        <tbody>
          {headline.rows
            .filter((r) => r.a !== null || r.b !== null)
            .map((r) => (
              <tr key={r.key} className="border-t border-border">
                <td className="py-1.5">{r.label}</td>
                <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                  {r.a ?? "—"}
                  {r.unit && r.a_value != null ? <span className="block text-[11px]">{postValue(r.unit, r.a_value)}</span> : null}
                </td>
                <td className="py-1.5 text-right font-medium tabular-nums">
                  {r.b ?? "—"}
                  {r.unit && r.b_value != null ? <span className="block text-[11px] font-normal text-muted-foreground">{postValue(r.unit, r.b_value)}</span> : null}
                </td>
                <td className={cn("py-1.5 text-right tabular-nums", trend(r.delta))}>{sign(r.delta, r.unit ? 0 : 2)}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </Card>
  );
}

function Side({ label, e }: { label: string; e: Partial<Execution> }) {
  return (
    <Card className="gap-1 p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <Link href={`/test-campaigns/${e.campaign_id}/executions/${e.id}`} className="text-lg font-semibold hover:underline">
        {e.version_number !== undefined ? versionLabel(e as Execution) : "?"}
      </Link>
      <p className="text-xs text-muted-foreground">
        {e.created_at ? format(new Date(e.created_at), "MMM d, HH:mm") : ""} · {e.channel}
        {e.passes && e.passes > 1 ? ` · ${e.passes} plays` : ""} · {e.personas === "fresh" ? "new callers" : "same callers"}
      </p>
    </Card>
  );
}

export function ComparePage({ a, b }: { a: string; b: string }) {
  const auth = useAuth();
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    void client.get<{ 200: Comparison }, unknown>({ url: `${API}/compare`, query: { a, b } }).then((r) => {
      if (r.error) setError(true);
      else setData(r.data as Comparison);
    });
  }, [auth.loading, auth.isAuthenticated, a, b]);

  if (error) return <div className="container mx-auto p-6 text-sm text-muted-foreground">These executions could not be compared.</div>;
  if (!data) {
    return (
      <div className="container mx-auto flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Comparing…
      </div>
    );
  }

  const sameVersion = data.a.definition_id === data.b.definition_id;
  const otherChannel = data.a.channel !== data.b.channel;
  return (
    <div className="container mx-auto w-full space-y-6 p-6 [contain:inline-size]">
      <Link href={`/test-campaigns/${data.b.campaign_id}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> {data.b.campaign_name}
      </Link>
      <h1 className="flex items-center gap-2 text-2xl font-bold">
        <GitCompare className="h-6 w-6 text-[var(--cta)]" /> Compare executions · {data.b.workflow_name}
      </h1>
      <div className="grid gap-3 md:grid-cols-2 [&>*]:min-w-0">
        <Side label="A (before)" e={data.a} />
        <Side label="B (after)" e={data.b} />
      </div>
      {(otherChannel || data.a.campaign_id !== data.b.campaign_id) && (
        <p className="text-sm text-amber-800 dark:text-amber-300">
          {otherChannel ? "The two executions used different channels (phone / text): latency and interruptions are not comparable. " : ""}
          {data.a.campaign_id !== data.b.campaign_id ? "They come from different campaigns: only common scenarios are compared." : ""}
        </p>
      )}

      {data.headline && (
        <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
          <HeadlineCard
            title="Quality score"
            subtitle="Answers: mean of the judge's 1–5 scores."
            headline={data.headline.quality}
          />
          <HeadlineCard
            title="Technical score"
            subtitle="Latency post by post, tools, turn-taking, reliability (1–5 against the Analysis thresholds)."
            headline={data.headline.technical}
          />
        </div>
      )}

      <Section title="Indicators" subtitle="B against A. Green: better, red: worse.">
        <Card className="overflow-x-auto p-0">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="border-b border-border text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Indicator</th>
                <th className="px-4 py-2 text-right font-medium">A</th>
                <th className="px-4 py-2 text-right font-medium">B</th>
                <th className="px-4 py-2 text-right font-medium">Change</th>
              </tr>
            </thead>
            <tbody>
              {data.indicators
                .filter((i) => i.a !== null || i.b !== null)
                .map((i) => {
                  const Icon = i.delta && i.delta > 0 ? ArrowUpRight : i.delta && i.delta < 0 ? ArrowDownRight : Minus;
                  return (
                    <tr key={i.key} className="border-b border-border last:border-0">
                      <td className="px-4 py-2">{i.label}</td>
                      <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">{formatIndicator(i.kind, i.a)}</td>
                      <td className="px-4 py-2 text-right font-medium tabular-nums">{formatIndicator(i.kind, i.b)}</td>
                      <td
                        className={cn(
                          "px-4 py-2 text-right tabular-nums",
                          i.trend === "better" ? "text-emerald-700 dark:text-emerald-300" : i.trend === "worse" ? "text-red-700 dark:text-red-300" : "text-muted-foreground",
                        )}
                      >
                        <span className="inline-flex items-center gap-1">
                          {i.delta ? <Icon className="h-3.5 w-3.5" /> : null}
                          {formatDelta(i.kind, i.delta)}
                          {i.trend === "better" ? <span className="sr-only">better</span> : i.trend === "worse" ? <span className="sr-only">worse</span> : null}
                        </span>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </Card>
      </Section>

      <Section
        title="Scenarios"
        subtitle={Object.entries(data.changes)
          .map(([k, n]) => `${n} ${CHANGE_META[k as keyof typeof CHANGE_META]?.label.toLowerCase() ?? k}`)
          .join(" · ")}
      >
        <Card className="divide-y divide-border p-0">
          {data.scenarios.map((s) => (
            <div key={s.scenario_id} className="grid grid-cols-[minmax(0,1fr)_7rem_7rem_6rem] items-center gap-3 px-4 py-2 text-sm">
              <span className="truncate">{s.title}</span>
              <span>{s.a ? <VerdictSplit verdicts={{ pass: s.a.pass, partial: s.a.partial, fail: s.a.fail }} /> : "—"}</span>
              <span>{s.b ? <VerdictSplit verdicts={{ pass: s.b.pass, partial: s.b.partial, fail: s.b.fail }} /> : "—"}</span>
              <span className={cn("justify-self-end rounded-md border px-1.5 py-0.5 text-[11px] font-medium", CHANGE_META[s.change].className)}>
                {CHANGE_META[s.change].label}
              </span>
            </div>
          ))}
        </Card>
      </Section>

      {(data.coverage.nodes_gained.length > 0 || data.coverage.nodes_lost.length > 0) && (
        <Section title="Coverage">
          <Card className="space-y-1 p-4 text-sm">
            {data.coverage.nodes_gained.length > 0 && <p>Now reached: {data.coverage.nodes_gained.join(", ")}</p>}
            {data.coverage.nodes_lost.length > 0 && <p className="text-amber-800 dark:text-amber-300">No longer reached: {data.coverage.nodes_lost.join(", ")}</p>}
          </Card>
        </Section>
      )}

      <Section
        title="What changed in the agent"
        subtitle={sameVersion ? "Same version on both sides: the differences come from the callers and the models." : `Configuration diff from ${versionLabel(data.a as Execution)} to ${versionLabel(data.b as Execution)}.`}
      >
        {!sameVersion &&
          (data.version_diff ? (
            data.version_diff.changes.length ? (
              <div className="space-y-2">
                {data.version_diff.changes.map((c) => (
                  <ChangeCard key={`${c.scope}:${c.id}`} change={c} />
                ))}
              </div>
            ) : (
              <Card className="p-4 text-sm text-muted-foreground">{data.version_diff.bullets[0] ?? "No configuration change."}</Card>
            )
          ) : (
            <Card className="p-4 text-sm text-muted-foreground">
              {data.version_unavailable
                ? "One of the versions tested no longer exists (a discarded draft): no configuration diff."
                : "Different agents: no configuration diff."}
            </Card>
          ))}
      </Section>
    </div>
  );
}
