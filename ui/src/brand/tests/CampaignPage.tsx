"use client";

import { format } from "date-fns";
import { ArrowLeft, FlaskConical, GitCompare, Loader2, Play, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { busy, type Campaign, DIMENSION_ORDER, ms, pct, rangeLabel, TOOLS_MODE_LABEL, versionLabel } from "./model";
import { RunDialog } from "./RunDialog";
import { ScenarioCard } from "./ScenarioCard";
import { API, ExecutionStatusBadge, useTestSettings, VerdictSplit } from "./ui";

export function CampaignPage({ campaignId }: { campaignId: string }) {
  const auth = useAuth();
  const router = useRouter();
  const settings = useTestSettings();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [missing, setMissing] = useState(false);
  const [view, setView] = useState<"executions" | "scenarios">("executions");
  const [runOpen, setRunOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [more, setMore] = useState(5);

  const load = useCallback(async () => {
    const response = await client.get<{ 200: Campaign }, unknown>({ url: `${API}/campaigns/${campaignId}` });
    if (response.error) {
      setMissing(true);
      return;
    }
    const data = response.data as Campaign;
    setCampaign(data);
    setView((v) => (v === "executions" && data.executions.length === 0 ? "scenarios" : v));
  }, [campaignId]);

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    void load();
  }, [auth.loading, auth.isAuthenticated, load]);

  const active = campaign && (campaign.status === "generating" || campaign.executions.some((e) => busy(e.status)));
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [active, load]);

  if (missing) return <div className="container mx-auto p-6 text-sm text-muted-foreground">Test campaign not found.</div>;
  if (!campaign || !settings.data) {
    return (
      <div className="container mx-auto flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const dims = settings.data.dimensions;
  const scenarios = campaign.scenarios.filter((s) => {
    const q = query.trim().toLowerCase();
    return !q || `${s.title} ${s.intent} ${s.persona.name} ${s.goal}`.toLowerCase().includes(q);
  });
  const toggle = (id: string) =>
    setSelected((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list.slice(-1), id]));

  return (
    <div className="container mx-auto space-y-6 p-6">
      <Link href="/test-campaigns" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Test campaigns
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="flex items-center gap-2 text-3xl font-bold">
            <FlaskConical className="h-7 w-7 text-[var(--cta)]" /> {campaign.name}
          </h1>
          <p className="text-sm text-muted-foreground">
            <Link href={`/workflow/${campaign.workflow_id}`} className="hover:underline">{campaign.workflow_name}</Link> · {campaign.language} · tools:{" "}
            {TOOLS_MODE_LABEL[campaign.tools_mode].toLowerCase()} · calls up to {Math.round(campaign.max_duration_seconds / 60)} min
          </p>
          <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {DIMENSION_ORDER.filter((k) => campaign.ranges[k]).map((k) => (
              <span key={k}>
                {dims[k]?.label ?? k} <span className="font-mono">{rangeLabel(campaign.ranges[k])}</span>
              </span>
            ))}
            <span>
              Speed <span className="font-mono">×{campaign.speed[0]}–{campaign.speed[1]}</span>
            </span>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => setRunOpen(true)}
            disabled={campaign.status === "generating" || !campaign.scenarios.some((s) => s.enabled)}
            className="gap-2 bg-[var(--cta)] text-[var(--cta-foreground)] hover:opacity-90"
          >
            <Play className="h-4 w-4" /> {campaign.executions.length ? "Replay" : "Play"}
          </Button>
          <Button
            variant="outline"
            className="gap-2 text-destructive"
            onClick={async () => {
              if (!window.confirm(`Delete the campaign “${campaign.name}” and its ${campaign.executions.length} execution(s)? The calls stay in the run history.`)) return;
              const response = await client.delete({ url: `${API}/campaigns/${campaign.id}` });
              if (response.error) toast.error(detailFromError(response.error, "Could not delete"));
              else router.push("/test-campaigns");
            }}
          >
            <Trash2 className="h-4 w-4" /> Delete
          </Button>
        </div>
      </div>

      {campaign.status === "generating" && (
        <Card className="flex-row items-center gap-3 p-4 text-sm">
          <Loader2 className="h-4 w-4 animate-spin text-[var(--cta)]" />
          The analysis model is writing the scenarios: {campaign.generation?.done ?? 0}/{campaign.generation?.total ?? campaign.count}…
        </Card>
      )}
      {campaign.generation?.error && campaign.status !== "generating" && (
        <Card className="p-4 text-sm text-amber-800 dark:text-amber-300">Scenario writing: {campaign.generation.error}</Card>
      )}

      <div className="flex gap-1 border-b border-border">
        {(["executions", "scenarios"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setView(v)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm",
              view === v ? "border-[var(--cta)] font-medium" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {v === "executions" ? `Executions (${campaign.executions.length})` : `Scenarios (${campaign.scenarios.length})`}
          </button>
        ))}
      </div>

      {view === "executions" ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            Tick two executions to compare them (e.g. the published version, then a draft).
            <Button
              size="sm"
              variant="outline"
              className="ml-auto gap-1.5"
              disabled={selected.length !== 2}
              onClick={() => {
                const [a, b] = [...selected].sort(
                  (x, y) =>
                    new Date(campaign.executions.find((e) => e.id === x)!.created_at).getTime() -
                    new Date(campaign.executions.find((e) => e.id === y)!.created_at).getTime(),
                );
                router.push(`/test-campaigns/compare?a=${a}&b=${b}`);
              }}
            >
              <GitCompare className="h-4 w-4" /> Compare
            </Button>
          </div>
          {campaign.executions.length === 0 ? (
            <Card className="p-8 text-center text-sm text-muted-foreground">Not played yet. Check the scenarios, then press Play.</Card>
          ) : (
            <Card className="overflow-x-auto p-0">
              <table className="w-full min-w-[820px] text-sm">
                <thead className="border-b border-border text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="w-10 px-4 py-2" />
                    <th className="px-4 py-2 font-medium">Date</th>
                    <th className="px-4 py-2 font-medium">Version</th>
                    <th className="px-4 py-2 font-medium">Channel</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium">Results</th>
                    <th className="px-4 py-2 font-medium">Pass rate</th>
                    <th className="px-4 py-2 font-medium">Latency p50</th>
                  </tr>
                </thead>
                <tbody>
                  {campaign.executions.map((e) => (
                    <tr key={e.id} className="border-b border-border last:border-0 hover:bg-muted/30">
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          aria-label="Select for comparison"
                          checked={selected.includes(e.id)}
                          onChange={() => toggle(e.id)}
                          disabled={e.status !== "done" && e.status !== "cancelled"}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <Link href={`/test-campaigns/${campaign.id}/executions/${e.id}`} className="font-medium hover:underline">
                          {format(new Date(e.created_at), "MMM d, HH:mm")}
                        </Link>
                        <p className="text-[11px] text-muted-foreground">{e.created_by?.email ?? ""}</p>
                      </td>
                      <td className="px-4 py-3">{versionLabel(e)}</td>
                      <td className="px-4 py-3 capitalize">
                        {e.channel}
                        <span className="block text-[11px] normal-case text-muted-foreground">
                          {e.passes > 1 ? `${e.passes} plays · ` : ""}
                          {e.personas === "fresh" ? "new callers" : "same callers"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <ExecutionStatusBadge status={e.status} progress={e.progress} />
                        {e.error && <p className="mt-1 max-w-[220px] truncate text-[11px] text-destructive" title={e.error}>{e.error}</p>}
                      </td>
                      <td className="w-52 px-4 py-3"><VerdictSplit verdicts={e.verdicts} /></td>
                      <td className="px-4 py-3 font-semibold tabular-nums">{pct(e.pass_rate)}</td>
                      <td className="px-4 py-3 tabular-nums">{e.channel === "phone" ? ms(e.latency_p50_ms) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search" className="w-64 pl-8" />
            </div>
            <span className="text-xs text-muted-foreground">
              {campaign.scenarios.filter((s) => s.enabled).length} enabled of {campaign.scenarios.length}
            </span>
            <div className="ml-auto flex items-center gap-2">
              <Input type="number" min={1} max={50} value={more} onChange={(e) => setMore(Math.max(1, Math.min(50, Number(e.target.value) || 1)))} className="w-20" />
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={campaign.status === "generating"}
                onClick={async () => {
                  const response = await client.post({ url: `${API}/campaigns/${campaign.id}/generate`, body: { count: more }, headers: { "Content-Type": "application/json" } });
                  if (response.error) toast.error(detailFromError(response.error, "Could not write more scenarios"));
                  else void load();
                }}
              >
                <Plus className="h-4 w-4" /> Write more
              </Button>
            </div>
          </div>
          {scenarios.map((s) => (
            <ScenarioCard
              key={s.id}
              index={campaign.scenarios.indexOf(s) + 1}
              campaignId={campaign.id}
              scenario={s}
              dimensions={dims}
              voices={settings.data!.settings.voices}
              onChanged={() => void load()}
            />
          ))}
        </div>
      )}

      <RunDialog
        campaign={campaign}
        open={runOpen}
        onOpenChange={setRunOpen}
        concurrencyDefault={settings.data.settings.concurrency}
        onStarted={(id) => router.push(`/test-campaigns/${campaign.id}/executions/${id}`)}
      />
    </div>
  );
}
