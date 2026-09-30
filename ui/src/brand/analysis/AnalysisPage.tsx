"use client";

import { format } from "date-fns";
import {
  AlertOctagon,
  AlertTriangle,
  Bot,
  Info,
  Lightbulb,
  Loader2,
  Play,
  Ruler,
  SearchCheck,
  Trash2,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { getPreferencesApiV1OrganizationsPreferencesGet, getWorkflowOptionsApiV1OrganizationsReportsWorkflowsGet } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { FixControls, requestFixes, useReportFixes } from "../fixes/FixPanel";
import { fixability, fixForFinding } from "../fixes/model";
import { ThresholdsPanel } from "./ThresholdsPanel";

// Analysis: run a review of recorded calls (rules + the org's analysis model)
// and list what to fix in the agents' configuration.

type Severity = "critical" | "warning" | "info";

interface Finding {
  id: string;
  source: "rule" | "model";
  rule: string | null;
  severity: Severity;
  category: string;
  title: string;
  detail: string;
  recommendation: string | null;
  agent: string | null;
  node: string | null;
  calls: number[];
  metrics: Record<string, unknown>;
  /** Rule text before the model rewrote it in the report language. */
  original?: { title: string; detail: string };
}

interface ReportSummary {
  id: string;
  status: "running" | "reviewing" | "done" | "failed";
  created_at: string;
  finished_at: string | null;
  params: { date: string; days: number; timezone: string; workflow_id: number | null };
  calls_analyzed: number | null;
  model: string | null;
  error: string | null;
  counts: Partial<Record<Severity, number>>;
}

interface Report extends ReportSummary {
  summary: string | null;
  findings: Finding[];
  model_error: string | null;
  call_links?: Record<string, number>;
  thresholds?: { values: Record<string, number>; source: "builtin" | "model" | "custom"; model: string | null };
}

// Status palette (reserved, always with icon + label).
const SEVERITY: Record<Severity, { label: string; color: string; icon: typeof AlertOctagon }> = {
  critical: { label: "Critical", color: "#d03b3b", icon: AlertOctagon },
  warning: { label: "Warning", color: "#fab219", icon: AlertTriangle },
  info: { label: "Info", color: "#3987e5", icon: Info },
};

const PERIODS = [
  { days: 1, label: "Today" },
  { days: 7, label: "Last 7 days" },
  { days: 30, label: "Last 30 days" },
];

function SeverityBadge({ severity, count }: { severity: Severity; count?: number }) {
  const meta = SEVERITY[severity];
  const Icon = meta.icon;
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-border px-1.5 py-0.5 text-[11px] font-medium">
      <Icon className="h-3 w-3" style={{ color: meta.color }} />
      {count !== undefined ? count : meta.label}
    </span>
  );
}

function FindingCard({ finding, links, children }: { finding: Finding; links: Record<string, number>; children?: React.ReactNode }) {
  const meta = SEVERITY[finding.severity];
  const Icon = meta.icon;
  return (
    <Card className="gap-2 border-l-4 p-4" style={{ borderLeftColor: meta.color }}>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1 font-medium text-foreground">
          <Icon className="h-3.5 w-3.5" style={{ color: meta.color }} /> {meta.label}
        </span>
        <span className="rounded bg-muted px-1.5 py-0.5 capitalize">{finding.category}</span>
        <span className="inline-flex items-center gap-1" title={finding.source === "rule" ? "Computed from the recorded data" : "Found by the analysis model"}>
          {finding.source === "rule" ? <Ruler className="h-3 w-3" /> : <Bot className="h-3 w-3" />}
          {finding.source === "rule" ? "Rule" : "Model"}
        </span>
        {finding.agent && <span>· {finding.agent}</span>}
        {finding.node && <span>· node “{finding.node}”</span>}
      </div>
      <h3 className="font-semibold" title={finding.original ? `Rule: ${finding.original.title}` : undefined}>{finding.title}</h3>
      <p className="text-sm text-muted-foreground">{finding.detail}</p>
      {finding.recommendation && (
        <p className="flex items-start gap-2 rounded-md bg-muted/60 p-2.5 text-sm">
          <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-[var(--cta)]" />
          <span>{finding.recommendation}</span>
        </p>
      )}
      {finding.calls.length > 0 && (
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          Examples:
          {finding.calls.map((id) =>
            links[String(id)] ? (
              <Link key={id} href={`/workflow/${links[String(id)]}/run/${id}`} className="rounded border border-border px-1.5 py-0.5 font-mono hover:bg-muted">
                #{id}
              </Link>
            ) : (
              <span key={id} className="font-mono">#{id}</span>
            ),
          )}
        </p>
      )}
      {children}
    </Card>
  );
}

export function AnalysisPage() {
  const auth = useAuth();
  const [workflows, setWorkflows] = useState<Array<{ id: number; name: string }>>([]);
  const [timezone, setTimezone] = useState("UTC");
  const [workflow, setWorkflow] = useState("all");
  const [days, setDays] = useState(7);
  const [language, setLanguage] = useState("French");
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [starting, setStarting] = useState(false);
  const [category, setCategory] = useState("all");

  const loadReports = useCallback(async () => {
    const response = await client.get<{ 200: ReportSummary[] }, unknown>({ url: "/api/v1/oxee/analysis/reports" });
    const list = (response.data as ReportSummary[]) ?? [];
    setReports(list);
    return list;
  }, []);

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    (async () => {
      const [wf, prefs, list] = await Promise.all([
        getWorkflowOptionsApiV1OrganizationsReportsWorkflowsGet(),
        getPreferencesApiV1OrganizationsPreferencesGet(),
        loadReports(),
      ]);
      setWorkflows((wf.data as Array<{ id: number; name: string }>) ?? []);
      if (prefs.data?.timezone) setTimezone(prefs.data.timezone);
      if (list.length) setSelectedId((id) => id ?? list[0].id);
    })();
  }, [auth.loading, auth.isAuthenticated, loadReports]);

  // Load the selected report; poll while it runs.
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      const response = await client.get<{ 200: Report }, unknown>({ url: `/api/v1/oxee/analysis/reports/${selectedId}` });
      if (cancelled || !response.data) return;
      const data = response.data as Report;
      setReport(data);
      if (data.status === "running" || data.status === "reviewing") timer = setTimeout(load, 2500);
      else void loadReports();
    };
    void load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [selectedId, loadReports]);

  const start = async () => {
    setStarting(true);
    const response = await client.post<{ 200: ReportSummary }, unknown>({
      url: "/api/v1/oxee/analysis/reports",
      body: {
        date: format(new Date(), "yyyy-MM-dd"),
        timezone,
        days,
        workflow_id: workflow === "all" ? null : Number(workflow),
        language,
      },
      headers: { "Content-Type": "application/json" },
    });
    setStarting(false);
    if (response.error) {
      toast.error(detailFromError(response.error, "Could not start the analysis"));
      return;
    }
    const created = response.data as ReportSummary;
    await loadReports();
    setCategory("all");
    setSelectedId(created.id);
  };

  const remove = async (id: string) => {
    await client.delete({ url: `/api/v1/oxee/analysis/reports/${id}` });
    const list = await loadReports();
    if (id === selectedId) {
      setReport(null);
      setSelectedId(list[0]?.id ?? null);
    }
  };

  const agentName = (id: number | null) => (id === null ? "All agents" : workflows.find((w) => w.id === id)?.name ?? `Agent ${id}`);
  const periodLabel = (d: number) => PERIODS.find((p) => p.days === d)?.label ?? `${d} days`;
  const categories = useMemo(() => Array.from(new Set((report?.findings ?? []).map((f) => f.category))), [report]);
  const findings = (report?.findings ?? []).filter((f) => category === "all" || f.category === category);
  const { fixes, reload: reloadFixes } = useReportFixes(report?.status === "done" ? report.id : null);
  const [fixingAll, setFixingAll] = useState(false);
  const fixableLeft = (report?.findings ?? []).filter((f) => {
    const current = fixForFinding(fixes, f.id);
    return fixability(f).fixable && (!current || ["discarded", "failed"].includes(current.status));
  }).length;
  const running = report?.status === "running" || report?.status === "reviewing";

  return (
    <div className="container mx-auto space-y-6 p-6">
      <div className="space-y-1">
        <h1 className="flex items-center gap-2 text-3xl font-bold">
          <SearchCheck className="h-7 w-7 text-[var(--cta)]" /> Analysis
        </h1>
        <p className="text-muted-foreground">
          Review recorded calls to find what to fix in your agents: latency, silences, stalled nodes, routing loops,
          misrouting, tool errors. Rules compute the facts; the analysis model (Models › Analysis) reviews them with the
          transcripts and recommends changes.
        </p>
      </div>

      <Card className="flex flex-wrap items-end gap-4 p-4">
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">Agent</p>
          <Select value={workflow} onValueChange={setWorkflow}>
            <SelectTrigger className="w-[220px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All agents</SelectItem>
              {workflows.map((w) => (
                <SelectItem key={w.id} value={String(w.id)}>{w.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">Calls</p>
          <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
            <SelectTrigger className="w-[160px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {PERIODS.map((p) => (
                <SelectItem key={p.days} value={String(p.days)}>{p.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">Report language</p>
          <Select value={language} onValueChange={setLanguage}>
            <SelectTrigger className="w-[140px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="French">Français</SelectItem>
              <SelectItem value="English">English</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button onClick={() => void start()} disabled={starting} className="gap-2 bg-[var(--cta)] text-[var(--cta-foreground)] hover:opacity-90">
          {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Run analysis
        </Button>
        <p className="ml-auto text-xs text-muted-foreground">Timezone: {timezone}</p>
      </Card>

      <ThresholdsPanel timezone={timezone} language={language} />

      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="space-y-2">
          <p className="text-sm font-medium">History</p>
          {reports.length === 0 && <p className="text-sm text-muted-foreground">No analysis yet.</p>}
          {reports.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setSelectedId(r.id)}
              className={cn(
                "w-full space-y-1 rounded-lg border p-3 text-left text-sm transition-colors",
                r.id === selectedId ? "border-[var(--cta)] bg-muted/50" : "border-border hover:bg-muted/30",
              )}
            >
              <p className="font-medium">{format(new Date(r.created_at), "MMM d, HH:mm")}</p>
              <p className="text-xs text-muted-foreground">{agentName(r.params.workflow_id)} · {periodLabel(r.params.days)}</p>
              <div className="flex flex-wrap items-center gap-1">
                {r.status === "running" || r.status === "reviewing" ? (
                  <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" /> Running</span>
                ) : r.status === "failed" ? (
                  <span className="text-xs text-destructive">Failed</span>
                ) : (
                  (["critical", "warning", "info"] as Severity[]).map((s) =>
                    r.counts[s] ? <SeverityBadge key={s} severity={s} count={r.counts[s]} /> : null,
                  )
                )}
              </div>
            </button>
          ))}
        </aside>

        <main className="min-w-0 space-y-4">
          {!report && <Card className="p-8 text-center text-sm text-muted-foreground">Run an analysis to see its findings here.</Card>}
          {report && (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold">
                    {agentName(report.params.workflow_id)} · {periodLabel(report.params.days)}
                  </h2>
                  <p className="text-xs text-muted-foreground">
                    {report.calls_analyzed ?? "…"} calls analyzed
                    {report.model ? ` · reviewed by ${report.model}` : ""}
                    {report.finished_at ? ` · ${format(new Date(report.finished_at), "MMM d, HH:mm")}` : ""}
                    {report.thresholds
                      ? ` · thresholds: ${report.thresholds.source === "model" ? `proposed by ${report.thresholds.model ?? "the model"}` : report.thresholds.source === "custom" ? "custom" : "built-in"}`
                      : ""}
                  </p>
                </div>
                {report.status === "done" && fixableLeft > 0 && (
                  <Button
                    size="sm"
                    className="gap-2"
                    disabled={fixingAll}
                    onClick={async () => {
                      setFixingAll(true);
                      const created = await requestFixes(report.id, language);
                      setFixingAll(false);
                      if (created) {
                        toast.success(`${created.length} fix${created.length > 1 ? "es" : ""} requested — the analysis model is preparing them`);
                        void reloadFixes();
                      }
                    }}
                  >
                    {fixingAll ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4" />} Fix all ({fixableLeft})
                  </Button>
                )}
                <Button variant="outline" size="sm" className="gap-2" onClick={() => void remove(report.id)}>
                  <Trash2 className="h-4 w-4" /> Delete
                </Button>
              </div>

              {running && (
                <Card className="flex-row items-center gap-3 p-4 text-sm">
                  <Loader2 className="h-4 w-4 animate-spin text-[var(--cta)]" />
                  {report.status === "running"
                    ? "Reading the calls and applying the rules…"
                    : `Rules done (${report.findings.length} findings). The analysis model is reviewing the transcripts…`}
                </Card>
              )}
              {report.status === "failed" && <Card className="p-4 text-sm text-destructive">Analysis failed: {report.error}</Card>}
              {report.model_error && (
                <Card className="p-4 text-sm">
                  <span className="font-medium">Model review unavailable:</span> {report.model_error}. The rule findings below are complete.
                </Card>
              )}
              {report.summary && (
                <Card className="gap-2 p-4">
                  <p className="flex items-center gap-2 text-sm font-medium"><Bot className="h-4 w-4 text-[var(--cta)]" /> Summary</p>
                  <p className="text-sm leading-relaxed">{report.summary}</p>
                </Card>
              )}

              {report.findings.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                  {(["critical", "warning", "info"] as Severity[]).map((s) => {
                    const n = report.findings.filter((f) => f.severity === s).length;
                    return n ? <SeverityBadge key={s} severity={s} count={n} /> : null;
                  })}
                  <span className="mx-1 h-4 w-px bg-border" />
                  {["all", ...categories].map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setCategory(c)}
                      className={cn(
                        "rounded-md border px-2 py-1 text-xs capitalize",
                        category === c ? "border-foreground/30 bg-muted font-semibold" : "border-border text-muted-foreground hover:bg-muted/60",
                      )}
                    >
                      {c}
                    </button>
                  ))}
                </div>
              )}
              {report.status === "done" && report.findings.length === 0 && (
                <Card className="p-6 text-center text-sm text-muted-foreground">No problem found in these calls.</Card>
              )}
              <div className="space-y-3">
                {findings.map((f) => (
                  <FindingCard key={f.id} finding={f} links={report.call_links ?? {}}>
                    {report.status === "done" && (
                      <FixControls
                        finding={f}
                        fix={fixForFinding(fixes, f.id)}
                        reportId={report.id}
                        language={language}
                        onChanged={() => void reloadFixes()}
                      />
                    )}
                  </FindingCard>
                ))}
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
