"use client";

import { format } from "date-fns";
import { ArrowDownRight, ArrowUpRight, FlaskConical, Loader2, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/lib/auth";

import { busy, type CampaignSummary, pct, versionLabel } from "./model";
import { TestSettingsDialog } from "./TestSettingsDialog";
import { API, ExecutionStatusBadge, useTestSettings, VerdictSplit } from "./ui";

// Manage › Test campaigns: scenarios played by a simulated caller against an
// agent, replayed on each version to compare (api/brand/test_*.py).

function Trend({ last, previous }: { last: CampaignSummary["last_done"]; previous: CampaignSummary["previous_done"] }) {
  if (!last || !previous || last.score === null || previous.score === null) return null;
  const delta = last.score - previous.score;
  if (Math.abs(delta) < 0.005) return <span className="text-xs text-muted-foreground">= previous</span>;
  const Icon = delta > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={delta > 0 ? "inline-flex items-center gap-0.5 text-xs text-emerald-700 dark:text-emerald-300" : "inline-flex items-center gap-0.5 text-xs text-red-700 dark:text-red-300"}>
      <Icon className="h-3.5 w-3.5" />
      {delta > 0 ? "+" : "−"}
      {Math.abs(delta * 100).toFixed(0)} pts vs {versionLabel(previous)}
    </span>
  );
}

export function TestCampaignsPage() {
  const auth = useAuth();
  const [items, setItems] = useState<CampaignSummary[] | null>(null);
  const settings = useTestSettings();

  const load = useCallback(async () => {
    const response = await client.get<{ 200: CampaignSummary[] }, unknown>({ url: `${API}/campaigns` });
    setItems((response.data as CampaignSummary[]) ?? []);
  }, []);

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    void load();
  }, [auth.loading, auth.isAuthenticated, load]);

  const active = (items ?? []).some((c) => c.status === "generating" || busy(c.last_execution?.status));
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => void load(), 4000);
    return () => clearInterval(timer);
  }, [active, load]);

  return (
    <div className="container mx-auto space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="flex items-center gap-2 text-3xl font-bold">
            <FlaskConical className="h-7 w-7 text-[var(--cta)]" /> Test campaigns
          </h1>
          <p className="max-w-3xl text-muted-foreground">
            Scenarios written from your agent&apos;s configuration and played by simulated callers, each with its own
            persona, voice and number. Replay a campaign on a draft to compare it with the published version before
            publishing.
          </p>
        </div>
        <div className="flex gap-2">
          <TestSettingsDialog data={settings.data} onSaved={() => void settings.reload()} />
          <Button asChild className="gap-2 bg-[var(--cta)] text-[var(--cta-foreground)] hover:opacity-90">
            <Link href="/test-campaigns/new">
              <Plus className="h-4 w-4" /> New campaign
            </Link>
          </Button>
        </div>
      </div>

      {items === null ? (
        <Card className="flex-row items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </Card>
      ) : items.length === 0 ? (
        <Card className="items-center gap-3 p-10 text-center">
          <FlaskConical className="h-8 w-8 text-muted-foreground" />
          <p className="font-medium">No test campaign yet</p>
          <p className="max-w-md text-sm text-muted-foreground">
            Pick an agent, set how hard the callers should be, and the analysis model writes the scenarios. Fill the
            test settings first (voices, caller numbers, tester telephony) for phone executions.
          </p>
          <Button asChild className="gap-2">
            <Link href="/test-campaigns/new">
              <Plus className="h-4 w-4" /> New campaign
            </Link>
          </Button>
        </Card>
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full min-w-[820px] text-sm">
            <thead className="border-b border-border text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Campaign</th>
                <th className="px-4 py-2 font-medium">Agent</th>
                <th className="px-4 py-2 font-medium">Scenarios</th>
                <th className="px-4 py-2 font-medium">Executions</th>
                <th className="px-4 py-2 font-medium">Last result</th>
                <th className="px-4 py-2 font-medium">Pass rate</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => {
                const last = c.last_execution;
                const done = c.last_done;
                return (
                  <tr key={c.id} className="border-b border-border last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-3">
                      <Link href={`/test-campaigns/${c.id}`} className="font-medium hover:underline">
                        {c.name}
                      </Link>
                      <p className="text-xs text-muted-foreground">{format(new Date(c.created_at), "MMM d, yyyy")}</p>
                    </td>
                    <td className="px-4 py-3">{c.workflow_name}</td>
                    <td className="px-4 py-3 tabular-nums">
                      {c.status === "generating" ? (
                        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                          <Loader2 className="h-3 w-3 animate-spin" /> Writing {c.generation?.done ?? 0}/{c.generation?.total ?? c.count}
                        </span>
                      ) : c.status === "failed" ? (
                        <span className="text-xs text-destructive">Generation failed</span>
                      ) : (
                        c.scenarios
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className="tabular-nums">{c.executions}</span>
                      {last && busy(last.status) && (
                        <span className="ml-2"><ExecutionStatusBadge status={last.status} progress={last.progress} /></span>
                      )}
                    </td>
                    <td className="w-56 px-4 py-3">
                      {done ? (
                        <div className="space-y-1">
                          <VerdictSplit verdicts={done.verdicts} />
                          <p className="text-[11px] text-muted-foreground">
                            {versionLabel(done)} · {done.channel} · {format(new Date(done.created_at), "MMM d, HH:mm")}
                          </p>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">Not played yet</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-semibold tabular-nums">{pct(done?.pass_rate)}</p>
                      <Trend last={done} previous={c.previous_done} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
