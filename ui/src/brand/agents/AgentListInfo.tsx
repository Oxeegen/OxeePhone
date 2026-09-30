"use client";

import { formatDistanceToNow } from "date-fns";
import { History } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { client } from "@/client/client.gen";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/dateTime";

// Agent list: last run and published version of each agent
// (GET /api/v1/oxee/workflows/list-info).

export interface AgentInfo {
  last_run_at?: string | null;
  /** Runs without the fix simulations (upstream's total counts them). */
  runs?: number | null;
  published_version?: number | null;
  published_at?: string | null;
  draft_version?: number | null;
}

/** One request for the whole list, shared by every table on the page. */
let shared: Promise<Record<string, AgentInfo>> | null = null;

export function useAgentListInfo(enabled: boolean): Record<string, AgentInfo> {
  const auth = useAuth();
  const [info, setInfo] = useState<Record<string, AgentInfo>>({});
  const started = useRef(false);

  useEffect(() => {
    if (!enabled || auth.loading || !auth.isAuthenticated || started.current) return;
    started.current = true;
    shared ??= client
      .get<{ 200: Record<string, AgentInfo> }, unknown>({ url: "/api/v1/oxee/workflows/list-info" })
      .then((r) => (r.data as Record<string, AgentInfo>) ?? {})
      .finally(() => setTimeout(() => (shared = null), 5000));
    void shared.then(setInfo);
  }, [enabled, auth.loading, auth.isAuthenticated]);

  return info;
}

export function LastRunCell({ info, timezone }: { info?: AgentInfo; timezone: string }) {
  if (!info?.last_run_at) return <span className="text-muted-foreground">—</span>;
  return (
    <span title={formatDistanceToNow(new Date(info.last_run_at), { addSuffix: true })}>
      {formatDateTime(info.last_run_at, timezone)}
    </span>
  );
}

export function PublishedVersionCell({ workflowId, info }: { workflowId: number; info?: AgentInfo }) {
  const label = info?.published_version ? `v${info.published_version}` : "Not published";
  return (
    <div className="flex items-center justify-center gap-1.5">
      <Link
        href={`/workflow/${workflowId}/versions`}
        title="Open the versions of this agent"
        className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-sm font-medium hover:bg-muted"
      >
        <History className="h-3.5 w-3.5 text-muted-foreground" /> {label}
      </Link>
      {info?.draft_version ? (
        <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[11px] text-amber-700 dark:text-amber-300" title="Unpublished draft">
          draft v{info.draft_version}
        </span>
      ) : null}
    </div>
  );
}
