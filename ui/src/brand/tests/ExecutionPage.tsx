"use client";

import { format } from "date-fns";
import { AlertTriangle, ArrowLeft, Check, ChevronDown, ExternalLink, FlaskConical, Loader2, Square, Wrench, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { FixControls, useReportFixes } from "../fixes/FixPanel";
import { fixForFinding } from "../fixes/model";
import {
  busy,
  DIMENSION_ORDER,
  type Execution,
  ms,
  pct,
  postValue,
  seconds,
  type Technical,
  type TestCall,
  TOOLS_MODE_LABEL,
  type Verdict,
  versionLabel,
} from "./model";
import { API, ExecutionStatusBadge, LevelChips, MeterRow, ScoreBadge, Section, techStatus, Tile, useTestSettings, VerdictBadge, VerdictSplit } from "./ui";

const STAGE_LABEL: Record<string, string> = {
  endpointing: "Endpointing",
  transcriber: "Transcriber",
  llm: "LLM",
  tools: "Tools",
  sentence: "First sentence",
  voice: "Voice",
  transport: "Transport",
  other: "Other",
};
const SCORE_LABEL: Record<string, string> = {
  understanding: "Understanding",
  accuracy: "Accuracy",
  concision: "Concision",
  tone: "Tone",
  resolution: "Resolution",
};

/** Settings × levels: pass rate per cell, one hue whose strength follows it. */
function LevelGrid({ report, dims, phone }: { report: NonNullable<Execution["report"]>; dims: Record<string, { label: string; levels: Record<string, string> }>; phone: boolean }) {
  const speed = Object.entries(report.by_dimension.speed ?? {});
  return (
    <Card className="overflow-x-auto p-4">
      <table className="w-full min-w-[420px] border-separate border-spacing-[2px] text-xs">
        <thead>
          <tr className="text-muted-foreground">
            <th className="text-left font-medium" />
            {[1, 2, 3, 4, 5].map((l) => (
              <th key={l} className="w-[15%] text-center font-medium">{l}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {DIMENSION_ORDER.map((k) => (
            <tr key={k}>
              <td className="pr-2 text-muted-foreground">{dims[k]?.label ?? k}</td>
              {[1, 2, 3, 4, 5].map((l) => {
                const cell = report.by_dimension[k]?.[String(l)];
                const rate = cell?.pass_rate ?? null;
                return (
                  <td
                    key={l}
                    title={cell ? `${dims[k]?.levels[String(l)] ?? ""}: ${pct(rate)} of ${cell.calls} call${cell.calls === 1 ? "" : "s"}` : "Not played"}
                    className="relative h-9 overflow-hidden rounded text-center tabular-nums"
                  >
                    {cell ? (
                      <>
                        <span
                          className="absolute inset-0"
                          style={{ background: `color-mix(in srgb, var(--cta) ${Math.round(10 + 75 * (rate ?? 0))}%, transparent)` }}
                        />
                        <span className={cn("relative font-medium", (rate ?? 0) >= 0.6 && "text-[var(--cta-foreground)]")}>{pct(rate)}</span>
                        <span className={cn("relative block text-[10px]", (rate ?? 0) >= 0.6 ? "text-[var(--cta-foreground)]/80" : "text-muted-foreground")}>
                          {cell.calls}
                        </span>
                      </>
                    ) : (
                      <span className="text-muted-foreground/50">·</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {phone && speed.length > 1 && (
        <p className="pt-3 text-xs text-muted-foreground">
          Voice speed: {speed.map(([b, v]) => `${b} ${pct(v.pass_rate)} (${v.calls})`).join(" · ")}
        </p>
      )}
      <p className="pt-2 text-[11px] text-muted-foreground">Each cell: pass rate and number of calls. Hover a cell for the level.</p>
    </Card>
  );
}

const POST_LABEL: Record<string, string> = {
  reply: "Reply",
  greeting: "Greeting",
  endpointing: "End of turn",
  transcriber: "Transcriber",
  llm: "LLM",
  voice: "Voice",
  tools: "Tools",
  turn_taking: "Turn-taking",
  reliability: "Reliability",
};

/** Technical report: every post graded against the analysis thresholds. */
function TechnicalReport({ technical, phone }: { technical: Technical; phone: boolean }) {
  return (
    <Section
      title="Technical report"
      subtitle={
        <>
          Measured on the agent side of the calls ({technical.replies} replies) and graded 1–5 against the{" "}
          <Link href="/analysis" className="underline underline-offset-2">Analysis thresholds</Link>: ≤ ½ threshold 5 · ≤ ¾ 4 · ≤
          threshold 3 · ≤ critical 2 · above 1; a p90 above the critical level costs a point.
          {phone ? "" : " Text executions have no timing: only tools and reliability are graded."}
        </>
      }
      actions={<ScoreBadge score={technical.score} status={technical.status} />}
    >
      <Card className="overflow-x-auto p-0">
        <table className="w-full min-w-[860px] text-sm">
          <thead className="border-b border-border text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-2 font-medium">Post</th>
              <th className="px-4 py-2 text-right font-medium">Median</th>
              <th className="px-4 py-2 text-right font-medium">p90</th>
              <th className="px-4 py-2 text-right font-medium">Max</th>
              <th className="px-4 py-2 text-right font-medium">Threshold</th>
              <th className="px-4 py-2 text-right font-medium">Over</th>
              <th className="px-4 py-2 font-medium">Share of the reply</th>
              <th className="px-4 py-2 font-medium">Score</th>
            </tr>
          </thead>
          <tbody>
            {technical.posts.map((p) => (
              <tr key={p.key} className="border-b border-border last:border-0">
                <td className="px-4 py-2.5">
                  <p className="font-medium">{p.label}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {p.help}
                    {p.model ? ` · ${p.model}` : ""}
                    {p.key === "tools" && p.calls ? ` · ${p.calls} calls, ${pct(p.failure_rate)} failed` : ""}
                    {p.key === "turn_taking" ? ` · ${p.interruptions ?? 0} interruptions` : ""}
                    {p.key === "reliability" ? ` · ${p.failed_calls ?? 0} of ${p.samples} calls` : ""}
                  </p>
                </td>
                <td className="px-4 py-2.5 text-right font-medium tabular-nums">{postValue(p.unit, p.p50)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">{p.p90 != null ? postValue(p.unit, p.p90) : "—"}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">{p.max != null ? postValue(p.unit, p.max) : "—"}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">{p.threshold != null ? postValue(p.unit, p.threshold) : "—"}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted-foreground">{p.over_rate != null ? pct(p.over_rate) : "—"}</td>
                <td className="w-40 px-4 py-2.5">
                  {p.share != null ? (
                    <div className="flex items-center gap-2" title={`${pct(p.share)} of the median reply time`}>
                      <div className="h-2 flex-1 rounded-full bg-muted">
                        <div className="h-2 rounded-full bg-[var(--viz-series-1)]" style={{ width: `${Math.min(100, p.share * 100)}%` }} />
                      </div>
                      <span className="w-10 text-right text-xs tabular-nums">{pct(p.share)}</span>
                    </div>
                  ) : null}
                </td>
                <td className="px-4 py-2.5"><ScoreBadge score={p.score} status={p.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {technical.info_stages.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Rest of the reply time (median, not graded):{" "}
          {technical.info_stages.map((x) => `${x.label} ${ms(x.p50)} (${pct(x.share)})`).join(" · ")}
        </p>
      )}
      {technical.worst_calls.some((c) => c.score < 4) && (
        <p className="text-xs text-muted-foreground">
          Weakest calls:{" "}
          {technical.worst_calls
            .filter((c) => c.score < 4)
            .map((c) => `#${c.index} ${c.title} (${c.score.toFixed(1)}/5${c.weakest ? `, ${c.weakest}` : ""})`)
            .join(" · ")}
        </p>
      )}
    </Section>
  );
}

function CallRow({ execution, call, fixReport, fixes, onFixChanged }: {
  execution: Execution;
  call: TestCall;
  fixReport: string;
  fixes: ReturnType<typeof useReportFixes>["fixes"];
  onFixChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const s = call.scenario;
  const j = call.judge;
  const m = call.metrics;
  const findingId = `test-${execution.id}-${call.index}`;
  const fix = fixForFinding(fixes, findingId);
  const running = call.status === "running" || call.status === "judging";

  return (
    <div className="rounded-lg border border-border">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full flex-wrap items-center gap-3 p-3 text-left">
        <span className="w-8 text-right font-mono text-xs text-muted-foreground">{call.index}</span>
        <span className="w-20">
          {running ? (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> {call.status === "judging" ? "Judging" : "In call"}</span>
          ) : call.status === "error" ? (
            <span className="inline-flex items-center gap-1 text-xs text-red-700 dark:text-red-300"><AlertTriangle className="h-3.5 w-3.5" /> Error</span>
          ) : call.status === "done" ? (
            <VerdictBadge verdict={call.verdict} />
          ) : (
            <span className="text-xs text-muted-foreground capitalize">{call.status}</span>
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{s.title}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {s.persona.name}
            {execution.passes > 1 ? ` · play ${call.pass}` : ""}
            {j?.summary ? ` · ${j.summary}` : call.error ? ` · ${call.error}` : ""}
          </span>
        </span>
        <LevelChips levels={s.levels} speed={execution.channel === "phone" ? s.speed : null} />
        {execution.channel === "phone" && call.technical?.score != null && (
          <span title={call.technical.weakest ? `Technical score · weakest: ${call.technical.weakest}` : "Technical score"}>
            <ScoreBadge score={call.technical.score} status={call.technical.status} compact />
          </span>
        )}
        <span className="w-16 text-right text-xs tabular-nums text-muted-foreground">{seconds(m?.duration_seconds)}</span>
        <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-4 border-t border-border p-4 text-sm">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {call.agent_run_id && (
              <Link href={`/workflow/${execution.workflow_id}/run/${call.agent_run_id}`} className="inline-flex items-center gap-1 text-foreground hover:underline">
                Agent side #{call.agent_run_id} <ExternalLink className="h-3 w-3" />
              </Link>
            )}
            {call.caller_run_id && <span>Caller side #{call.caller_run_id}</span>}
            {s.voice && <span>Voice {s.voice.id}</span>}
            {s.caller_number && <span>From {s.caller_number}</span>}
            {m && <span>Ended: {m.end_status || "?"}{m.end_node ? ` in “${m.end_node}”` : ""}</span>}
            {m && execution.channel === "phone" && <span>Latency p50 {ms(m.latency.p50_ms)} · {m.interruptions} interruption{m.interruptions === 1 ? "" : "s"}</span>}
          </div>
          <p><span className="text-muted-foreground">Goal:</span> {s.goal}</p>

          {j && (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground">Criteria · goal {j.goal_reached ? "reached" : "not reached"}</p>
                {j.criteria.map((c, i) => (
                  <p key={i} className="flex items-start gap-1.5">
                    {c.pass ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /> : <X className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />}
                    <span>
                      {c.text}
                      {c.evidence && <span className="block text-xs text-muted-foreground">{c.evidence}</span>}
                    </span>
                  </p>
                ))}
                {j.forbidden.map((f, i) => (
                  <p key={`f${i}`} className="flex items-start gap-1.5">
                    {f.violated ? <X className="mt-0.5 h-4 w-4 shrink-0 text-red-600" /> : <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />}
                    <span>
                      Never: {f.text}
                      {f.violated && f.evidence && <span className="block text-xs text-muted-foreground">{f.evidence}</span>}
                    </span>
                  </p>
                ))}
                {(call.checks ?? []).map((c, i) => (
                  <p key={`c${i}`} className="flex items-start gap-1.5" title="Checked from the call data">
                    {c.pass ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /> : <X className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />}
                    <span>
                      {c.label}
                      <span className="block text-xs text-muted-foreground">{c.detail}</span>
                    </span>
                  </p>
                ))}
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Scores</p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(j.scores).map(([k, v]) => (
                    <span key={k} className="rounded-md border border-border px-2 py-1 text-xs">
                      {SCORE_LABEL[k] ?? k} <span className="font-semibold tabular-nums">{v}</span>/5
                    </span>
                  ))}
                </div>
                {call.technical && Object.keys(call.technical.posts).length > 0 && (
                  <>
                    <p className="text-xs font-medium text-muted-foreground">Technical</p>
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(call.technical.posts).map(([k, v]) => (
                        <span key={k} className="inline-flex items-center gap-1 text-xs">
                          {POST_LABEL[k] ?? k} <ScoreBadge score={v} status={techStatus(v)} compact />
                        </span>
                      ))}
                    </div>
                  </>
                )}
                {j.issues.length > 0 && (
                  <>
                    <p className="text-xs font-medium text-muted-foreground">To improve{j.failure_node ? ` (node “${j.failure_node}”)` : ""}</p>
                    <ul className="list-disc space-y-1 pl-5 text-sm">{j.issues.map((x, i) => <li key={i}>{x}</li>)}</ul>
                  </>
                )}
                {j.scenario_issue && (
                  <p className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
                    <span className="font-medium">The scenario may be at fault:</span> {j.scenario_issue} Edit it in the campaign&apos;s
                    Scenarios tab.
                  </p>
                )}
                {j.error && <p className="text-xs text-amber-700 dark:text-amber-300">Judge: {j.error}</p>}
              </div>
            </div>
          )}

          {(call.verdict === "fail" || call.verdict === "partial") && call.agent_run_id && (
            fix ? (
              <FixControls finding={{ id: findingId, rule: null, category: "test" }} fix={fix} reportId={fixReport} language={execution.language} onChanged={onFixChanged} defaultOpen />
            ) : (
              <Button
                size="sm"
                variant="outline"
                className="gap-1.5"
                disabled={asking}
                onClick={async () => {
                  setAsking(true);
                  const response = await client.post({
                    url: `${API}/executions/${execution.id}/calls/${call.index}/fix`,
                    body: { language: execution.language },
                    headers: { "Content-Type": "application/json" },
                  });
                  setAsking(false);
                  if (response.error) toast.error(detailFromError(response.error, "Could not ask for a fix"));
                  else onFixChanged();
                }}
              >
                {asking ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4" />} Propose a fix
              </Button>
            )
          )}
        </div>
      )}
    </div>
  );
}

export function ExecutionPage({ campaignId, executionId }: { campaignId: string; executionId: string }) {
  const auth = useAuth();
  const settings = useTestSettings();
  const [execution, setExecution] = useState<Execution | null>(null);
  const [missing, setMissing] = useState(false);
  const [filter, setFilter] = useState<"all" | Verdict | "error">("all");
  const fixReport = `test:${executionId}`;
  const { fixes, reload: reloadFixes } = useReportFixes(fixReport);

  const load = useCallback(async () => {
    const response = await client.get<{ 200: Execution }, unknown>({ url: `${API}/executions/${executionId}` });
    if (response.error) setMissing(true);
    else setExecution(response.data as Execution);
  }, [executionId]);

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    void load();
  }, [auth.loading, auth.isAuthenticated, load]);

  const running = busy(execution?.status);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [running, load]);

  const calls = useMemo(
    () =>
      (execution?.calls ?? []).filter((c) =>
        filter === "all" ? true : filter === "error" ? c.status === "error" : c.verdict === filter,
      ),
    [execution, filter],
  );

  if (missing) return <div className="container mx-auto p-6 text-sm text-muted-foreground">Execution not found.</div>;
  if (!execution) {
    return (
      <div className="container mx-auto flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const r = execution.report;
  const dims = settings.data?.dimensions ?? {};
  const finished = execution.calls.filter((c) => ["done", "error", "cancelled"].includes(c.status)).length;
  const phone = execution.channel === "phone";

  return (
    <div className="container mx-auto space-y-6 p-6">
      <Link href={`/test-campaigns/${campaignId}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> {execution.campaign_name}
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="flex flex-wrap items-center gap-2 text-2xl font-bold">
            <FlaskConical className="h-6 w-6 text-[var(--cta)]" /> {execution.workflow_name} {versionLabel(execution)}
            <ExecutionStatusBadge status={execution.status} progress={{ total: execution.calls.length, finished }} />
          </h1>
          <p className="text-sm text-muted-foreground">
            {format(new Date(execution.created_at), "MMM d, yyyy HH:mm")} · {phone ? `phone (${execution.phone?.destination})` : "text"} ·{" "}
            {execution.calls.length} calls{execution.passes > 1 ? ` (${execution.passes} plays per scenario)` : ""} ·{" "}
            {execution.personas === "fresh" ? "new callers" : "same callers"} · tools {TOOLS_MODE_LABEL[execution.tools_mode].toLowerCase()}
            {execution.created_by?.email ? ` · ${execution.created_by.email}` : ""}
          </p>
          {execution.error && <p className="text-sm text-destructive">{execution.error}</p>}
        </div>
        {running && (
          <Button
            variant="outline"
            className="gap-2"
            onClick={async () => {
              const response = await client.post({ url: `${API}/executions/${execution.id}/cancel`, body: {}, headers: { "Content-Type": "application/json" } });
              if (response.error) toast.error(detailFromError(response.error, "Could not cancel"));
              else {
                toast.success("No new call will start; calls in progress finish first");
                void load();
              }
            }}
          >
            <Square className="h-4 w-4" /> Stop
          </Button>
        )}
      </div>

      {running && (
        <Card className="space-y-2 p-4">
          <div className="flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin text-[var(--cta)]" />
            {execution.status === "queued" ? "Waiting for another execution to finish…" : `${finished} of ${execution.calls.length} calls played and judged…`}
          </div>
          <div className="h-1.5 rounded-full bg-muted">
            <div className="h-1.5 rounded-full bg-[var(--cta)] transition-all" style={{ width: `${(finished / Math.max(1, execution.calls.length)) * 100}%` }} />
          </div>
        </Card>
      )}

      {r && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Tile label="Pass rate" value={pct(r.pass_rate)} hint={<VerdictSplit verdicts={r.verdicts} />} help="Calls whose goal was reached with every criterion and check passed, out of the judged calls." />
            <Tile label="Goal reached" value={pct(r.goal_rate)} hint={`score ${pct(r.score)} (pass + ½ partial)`} />
            <Tile
              label="Quality score"
              value={r.quality_score != null ? `${r.quality_score.toFixed(2)}/5` : "—"}
              hint="answers, mean of the judge's scores"
              help="Understanding, accuracy, concision, tone and resolution, scored 1-5 by the judge on every call."
            />
            <Tile
              label="Technical score"
              value={r.technical?.score != null ? `${r.technical.score.toFixed(2)}/5` : "—"}
              hint={r.technical?.status ? <ScoreBadge score={r.technical.score} status={r.technical.status} /> : phone ? "" : "text: tools and reliability only"}
              help="Latency post by post, tools, turn-taking and reliability, graded 1-5 against the thresholds of Analysis › Thresholds."
            />
            <Tile
              label="Graph coverage"
              value={pct(r.coverage.nodes_rate)}
              hint={`${r.coverage.nodes_visited}/${r.coverage.nodes_total} nodes · ${r.coverage.edges_used}/${r.coverage.edges_total} transitions`}
            />
          </div>
          {r.technical && <TechnicalReport technical={r.technical} phone={phone} />}
          {(r.scenario_issues?.length ?? 0) > 0 && (
            <Card className="gap-1 border-amber-500/40 p-4 text-sm">
              <p className="font-medium">Scenarios to review ({r.scenario_issues!.length})</p>
              <p className="text-xs text-muted-foreground">The judge thinks these calls failed because of the scenario, not the agent.</p>
              <ul className="list-disc space-y-0.5 pl-5 text-xs">
                {r.scenario_issues!.map((x) => (
                  <li key={x.index}>
                    <span className="font-medium">#{x.index} {x.title}</span>: {x.issue}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {(r.errors > 0 || r.played > r.judged) && (
            <p className="text-xs text-amber-700 dark:text-amber-300">
              {r.errors > 0 ? `${r.errors} call(s) failed to play. ` : ""}
              {r.played > r.judged ? `${r.played - r.judged} call(s) not judged (the judge did not answer).` : ""}
            </p>
          )}

          <div className="grid gap-6 lg:grid-cols-2">
            <Section title="Scenarios" subtitle="Worst first. Unstable: different results over the plays.">
              <Card className="divide-y divide-border p-0">
                {r.by_scenario.map((s) => (
                  <div key={s.scenario_id} className="flex items-center gap-3 px-4 py-2 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="truncate">{s.title}</p>
                      <LevelChips levels={s.levels} />
                    </div>
                    {s.unstable && <span className="rounded border border-amber-500/40 px-1.5 py-0.5 text-[10px] text-amber-800 dark:text-amber-300">unstable</span>}
                    <span className="w-24"><VerdictSplit verdicts={{ pass: s.pass, partial: s.partial, fail: s.fail }} /></span>
                  </div>
                ))}
              </Card>
            </Section>

            <Section title="Pass rate by caller setting" subtitle="Where the agent starts failing as callers get harder (1 easy → 5 hard).">
              <LevelGrid report={r} dims={dims} phone={phone} />
            </Section>

            <Section title="What fails">
              <Card className="space-y-3 p-4 text-sm">
                {r.criteria_failures.length === 0 && r.checks_failed.length === 0 ? (
                  <p className="text-muted-foreground">No failed criterion.</p>
                ) : (
                  <>
                    {r.criteria_failures.map((c) => (
                      <MeterRow key={c.text} label={c.text} value={c.count} max={r.judged} display={`${c.count}`} />
                    ))}
                    {r.checks_failed.map((c) => (
                      <MeterRow key={c.label} label={c.label} sub="checked from the call data" value={c.count} max={r.judged} display={`${c.count}`} />
                    ))}
                  </>
                )}
                {Object.keys(r.failure_nodes).length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    Where it goes wrong:{" "}
                    {Object.entries(r.failure_nodes).map(([n, c]) => `${n} (${c})`).join(", ")}
                  </p>
                )}
              </Card>
            </Section>

            <Section title="Quality scores" subtitle="Average of the judge's 1–5 scores.">
              <Card className="p-4">
                {Object.entries(r.scores).map(([k, v]) => (
                  <MeterRow key={k} label={SCORE_LABEL[k] ?? k} value={v} max={5} display={`${v.toFixed(2)}`} />
                ))}
              </Card>
            </Section>

            {phone && (
              <Section title="Latency" subtitle={`${r.latency.turns} agent replies · ${pct(r.latency.slow_turns_rate)} over 2 s · ${r.interruptions.per_call ?? "—"} interruptions per call`}>
                <Card className="p-4">
                  {Object.entries(r.latency.stages_p50_ms)
                    .filter(([, v]) => v !== null)
                    .map(([k, v]) => (
                      <MeterRow
                        key={k}
                        label={STAGE_LABEL[k] ?? k}
                        value={v ?? 0}
                        max={Math.max(...Object.values(r.latency.stages_p50_ms).map((x) => x ?? 0), 1)}
                        display={ms(v)}
                      />
                    ))}
                  <p className="pt-2 text-[11px] text-muted-foreground">Median per stage over every reply of the agent.</p>
                </Card>
              </Section>
            )}

            <Section title="Coverage of the agent" subtitle="Calls that went through each node.">
              <Card className="space-y-2 p-4 text-sm">
                {Object.entries(r.coverage.node_visits)
                  .sort((a, b) => b[1] - a[1])
                  .map(([n, c]) => (
                    <MeterRow key={n} label={n} value={c} max={r.played} display={`${c}`} />
                  ))}
                {r.coverage.nodes_never_visited.length > 0 && (
                  <p className="text-xs text-amber-800 dark:text-amber-300">Never reached: {r.coverage.nodes_never_visited.join(", ")}</p>
                )}
                {r.coverage.edges_never_used.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    Transitions never taken: {r.coverage.edges_never_used.map((e) => `${e.from} → ${e.to}${e.label ? ` (${e.label})` : ""}`).join(" · ")}
                  </p>
                )}
              </Card>
            </Section>

            {r.tools.calls > 0 && (
              <Section title="Tools" subtitle={`${r.tools.calls} calls · ${pct(r.tools.failure_rate)} failed`}>
                <Card className="p-4">
                  {Object.entries(r.tools.by_tool).map(([name, t]) => (
                    <MeterRow key={name} label={name} sub={`${t.failed} failed · ${ms(t.avg_ms)} avg`} value={t.calls} max={r.tools.calls} display={`${t.calls}`} />
                  ))}
                </Card>
              </Section>
            )}
          </div>
        </>
      )}

      <Section
        title="Calls"
        actions={
          <div className="flex gap-1 text-xs">
            {(["all", "fail", "partial", "pass", "error"] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={cn("rounded-md border px-2 py-1 capitalize", filter === f ? "border-[var(--cta)] bg-[var(--cta)]/5" : "border-border text-muted-foreground")}
              >
                {f}
              </button>
            ))}
          </div>
        }
      >
        <div className="space-y-2">
          {calls.map((c) => (
            <CallRow key={c.index} execution={execution} call={c} fixReport={fixReport} fixes={fixes} onFixChanged={() => {
              void reloadFixes();
              void load();
            }} />
          ))}
          {calls.length === 0 && <p className="text-sm text-muted-foreground">No call.</p>}
        </div>
      </Section>
    </div>
  );
}
