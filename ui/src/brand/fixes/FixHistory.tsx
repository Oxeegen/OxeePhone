"use client";

import { ChevronDown, Wrench } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { FixControls, useReportFixes } from "./FixPanel";
import { type Fix, FOLLOW_UP_LABEL, STATUS_LABEL } from "./model";

// Analysis › Fixes: every automatic fix, newest first, with its state from
// proposal to follow-up on real calls.

const STATUS_STYLE: Partial<Record<Fix["status"], string>> = {
  published: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  rolled_back: "border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300",
  tested: "border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  applied: "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300",
  failed: "border-rose-500/40 text-rose-700 dark:text-rose-300",
};

export function FixHistory({ language }: { language: string }) {
  const { fixes, reload } = useReportFixes("*");
  const [openId, setOpenId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("all");
  const shown = fixes.filter((f) => status === "all" || f.status === status);
  const statuses = Array.from(new Set(fixes.map((f) => f.status)));

  if (!fixes.length) {
    return (
      <Card className="p-6 text-center text-sm text-muted-foreground">
        No automatic fix yet. Open an analysis report and use “Propose a fix” on a finding.
      </Card>
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {["all", ...statuses].map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatus(s)}
            className={cn(
              "rounded-md border px-2 py-1 text-xs",
              status === s ? "border-foreground/30 bg-muted font-semibold" : "border-border text-muted-foreground hover:bg-muted/60",
            )}
          >
            {s === "all" ? `All (${fixes.length})` : `${STATUS_LABEL[s as Fix["status"]]} (${fixes.filter((f) => f.status === s).length})`}
          </button>
        ))}
      </div>
      {shown.map((f) => (
        <Card key={f.id} className="gap-2 p-3">
          <button type="button" onClick={() => setOpenId((id) => (id === f.id ? null : f.id))} className="flex w-full flex-wrap items-center gap-2 text-left text-sm">
            <Wrench className="h-4 w-4 text-[var(--cta)]" />
            <span className="text-xs text-muted-foreground">{new Date(f.created_at).toLocaleString()}</span>
            <span className="font-medium">{f.finding.title}</span>
            <span className="text-xs text-muted-foreground">· {f.workflow_name ?? f.finding.agent ?? "?"}</span>
            <span className={cn("rounded-full border border-border px-2 py-0.5 text-[11px]", STATUS_STYLE[f.status])}>{STATUS_LABEL[f.status]}</span>
            {f.draft_version_number && f.workflow_id && (
              <Link href={`/workflow/${f.workflow_id}/versions`} onClick={(e) => e.stopPropagation()} className="text-xs underline-offset-2 hover:underline">
                v{f.draft_version_number}
              </Link>
            )}
            {f.simulation?.verdict && <span className="text-[11px] text-muted-foreground">test: {f.simulation.verdict}</span>}
            {f.follow_up && <span className="text-[11px] text-muted-foreground">follow-up: {FOLLOW_UP_LABEL[f.follow_up.status]}</span>}
            <ChevronDown className={cn("ml-auto h-4 w-4 text-muted-foreground transition-transform", openId === f.id && "rotate-180")} />
          </button>
          {openId === f.id && (
            <FixControls
              finding={{ id: f.finding.id, rule: f.finding.rule, category: "" }}
              fix={f}
              reportId={f.report_id}
              language={language}
              onChanged={() => void reload()}
              defaultOpen
            />
          )}
        </Card>
      ))}
    </div>
  );
}
