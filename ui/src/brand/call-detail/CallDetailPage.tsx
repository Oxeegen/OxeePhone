"use client";

import { ArrowLeft, Clock, Copy, FileText, Gauge, GitBranch, List, MessagesSquare, Phone, ScrollText, Sparkles } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { getWorkflowApiV1WorkflowFetchWorkflowIdGet, getWorkflowRunApiV1WorkflowWorkflowIdRunsRunIdGet } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/lib/auth";
import { getSignedUrl } from "@/lib/files";

import { AnalysisTab } from "./AnalysisTab";
import { EventsTab } from "./EventsTab";
import { LatencyTab } from "./LatencyTab";
import {
  activeMessageId,
  buildTimeline,
  type CallRun,
  eventRows,
  latencyTurns,
  recordingAnchor,
  usageSummary,
  voiceFluency,
} from "./model";
import { RecordingPlayer, type RecordingPlayerHandle } from "./RecordingPlayer";
import { buildRouting, type RoutingGraphs, transitionToolCallIds } from "./routing";
import { RoutingTab } from "./RoutingTab";
import { TranscriptTab } from "./TranscriptTab";
import { UsageTab } from "./UsageTab";

// VAPI-style call detail: header, two-lane recording player, and tabs
// (Transcript synced with playback, Latency, Events, Analysis, Usage).

function callTypeLabel(run: CallRun): string {
  const mode = (run.mode ?? "").toLowerCase();
  if (mode.includes("text")) return "Text chat";
  if (mode.includes("webrtc") || mode.includes("web")) return "Web call";
  const direction = run.call_type ? `${run.call_type[0].toUpperCase()}${run.call_type.slice(1)} ` : "";
  return `${direction}phone call`;
}

function CopyId({ label, value }: { label: string; value: string }) {
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 font-mono text-xs hover:text-foreground"
      title={`Copy ${label}`}
      onClick={() => {
        void navigator.clipboard.writeText(value);
        toast.success(`${label} copied`);
      }}
    >
      {value} <Copy className="h-3 w-3" />
    </button>
  );
}

export function CallDetailPage() {
  const params = useParams();
  const auth = useAuth();
  const workflowId = Number(params.workflowId);
  const runId = Number(params.runId);
  const [run, setRun] = useState<CallRun | null>(null);
  const [agentName, setAgentName] = useState("Agent");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [agentOnset, setAgentOnset] = useState<number | null>(null);
  const [graphs, setGraphs] = useState<RoutingGraphs | null>(null);
  const [graphsLoading, setGraphsLoading] = useState(true);
  const player = useRef<RecordingPlayerHandle>(null);

  useEffect(() => {
    if (!auth.loading && !auth.isAuthenticated) auth.redirectToLogin();
  }, [auth]);

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      const [runResponse, workflowResponse] = await Promise.all([
        getWorkflowRunApiV1WorkflowWorkflowIdRunsRunIdGet({ path: { workflow_id: workflowId, run_id: runId } }),
        getWorkflowApiV1WorkflowFetchWorkflowIdGet({ path: { workflow_id: workflowId } }),
      ]);
      if (cancelled) return;
      const routing = await client.get<{ 200: RoutingGraphs }, unknown>({ url: `/api/v1/oxee/runs/${runId}/routing` });
      if (cancelled) return;
      setGraphs(routing.error ? null : ((routing.data as RoutingGraphs) ?? null));
      setGraphsLoading(false);
      if (runResponse.error || !runResponse.data) {
        setError("This call could not be loaded.");
      } else {
        setRun(runResponse.data as unknown as CallRun);
        setAgentName(workflowResponse.data?.name ?? "Agent");
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [auth.loading, auth.isAuthenticated, workflowId, runId]);

  const anchor = useMemo(() => (run ? recordingAnchor(run, agentOnset) : null), [run, agentOnset]);
  const routing = useMemo(() => (run ? buildRouting(run, graphs, anchor) : null), [run, graphs, anchor]);
  const timeline = useMemo(() => {
    if (!run) return [];
    const pathwayByNodeItem = new Map(
      (routing?.steps ?? []).filter((s) => s.edge && s.cause === "condition").map((s) => [s.id.replace("step-", "node-"), s.edge!.label]),
    );
    return buildTimeline(run, anchor, {
      hiddenToolCallIds: routing ? transitionToolCallIds(run, routing) : undefined,
      pathwayByNodeItem,
    });
  }, [run, anchor, routing]);
  const turns = useMemo(() => (run ? latencyTurns(run) : []), [run]);
  const voice = useMemo(() => (run ? voiceFluency(run) : null), [run]);
  const rows = useMemo(() => (run ? eventRows(run, anchor) : []), [run, anchor]);
  const usage = useMemo(() => (run ? usageSummary(run, timeline) : null), [run, timeline]);
  const activeId = useMemo(() => activeMessageId(timeline, time), [timeline, time]);
  const seek = useCallback((seconds: number) => player.current?.seek(seconds), []);
  const onAgentOnset = useCallback((seconds: number | null) => setAgentOnset(seconds), []);

  const downloadTranscript = async () => {
    const url = await getSignedUrl(run?.transcript_url ?? null, false);
    if (url) window.open(url, "_blank");
  };

  if (loading) return <div className="p-8 text-sm text-muted-foreground">Loading call…</div>;
  if (error || !run) return <div className="p-8 text-sm text-destructive">{error ?? "Call not found."}</div>;

  const gathered = run.gathered_context ?? {};
  const disposition = (gathered.mapped_call_disposition ?? gathered.call_disposition) as string | undefined;
  const created = run.created_at ? new Date(run.created_at) : null;
  const isText = (run.mode ?? "").toLowerCase().includes("text");

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6">
      <header className="space-y-2">
        <Link href={`/workflow/${workflowId}/runs`} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-3 w-3" /> Calls
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1.5">
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <Phone className="h-5 w-5 text-[var(--cta)]" />
              {created ? created.toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : `Call #${run.id}`}
              <span className="font-normal text-muted-foreground">· {callTypeLabel(run)}</span>
            </h1>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>Call ID: <CopyId label="Call ID" value={String(run.id)} /></span>
              <span>
                Agent:{" "}
                <Link href={`/workflow/${workflowId}`} className="font-medium text-[var(--cta)] hover:underline">{agentName}</Link>
              </span>
              <span>Ended: <span className="text-foreground">{disposition || (run.is_completed ? "completed" : "in progress")}</span></span>
            </div>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="flex items-center gap-1 text-muted-foreground">
              <Clock className="h-4 w-4" /> {usage?.callSeconds ? `${Math.round(usage.callSeconds)}s` : "—"}
            </span>
            {run.transcript_url && (
              <Button type="button" variant="outline" size="sm" className="gap-2" onClick={() => void downloadTranscript()}>
                <FileText className="h-4 w-4" /> Transcript
              </Button>
            )}
          </div>
        </div>
      </header>

      {!run.is_completed && !isText && (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm">
          This call is still in progress; the recording and full details appear once it ends.
        </p>
      )}

      {!isText && run.is_completed && (
        <RecordingPlayer
          ref={player}
          mixedKey={run.recording_url ?? null}
          userKey={run.user_recording_url ?? null}
          agentKey={run.bot_recording_url ?? null}
          onTime={setTime}
          onAgentOnset={onAgentOnset}
        />
      )}

      <Tabs defaultValue="transcript" className="gap-4">
        <TabsList className="h-auto flex-wrap justify-start">
          <TabsTrigger value="transcript" className="gap-1.5"><MessagesSquare className="h-4 w-4" /> Transcript</TabsTrigger>
          <TabsTrigger value="routing" className="gap-1.5"><GitBranch className="h-4 w-4" /> Routing</TabsTrigger>
          <TabsTrigger value="latency" className="gap-1.5"><Gauge className="h-4 w-4" /> Latency</TabsTrigger>
          <TabsTrigger value="events" className="gap-1.5"><List className="h-4 w-4" /> Events</TabsTrigger>
          <TabsTrigger value="analysis" className="gap-1.5"><Sparkles className="h-4 w-4" /> Analysis</TabsTrigger>
          <TabsTrigger value="usage" className="gap-1.5"><ScrollText className="h-4 w-4" /> Usage</TabsTrigger>
        </TabsList>
        <TabsContent value="transcript">
          <TranscriptTab items={timeline} agentName={agentName} activeId={activeId} onSeek={seek} />
        </TabsContent>
        <TabsContent value="routing">
          <RoutingTab model={routing} onSeek={seek} loading={graphsLoading} />
        </TabsContent>
        <TabsContent value="latency">
          <LatencyTab turns={turns} voice={voice} />
        </TabsContent>
        <TabsContent value="events">
          <EventsTab rows={rows} runId={run.id} onSeek={seek} />
        </TabsContent>
        <TabsContent value="analysis">
          <AnalysisTab run={run} />
        </TabsContent>
        <TabsContent value="usage">{usage && <UsageTab usage={usage} />}</TabsContent>
      </Tabs>

      {anchor && anchor.source !== "marker" && !isText && (
        <p className="text-[11px] text-muted-foreground">
          Transcript positions are estimated for this call (recorded before OxeePhone call insights).
        </p>
      )}
    </div>
  );
}
