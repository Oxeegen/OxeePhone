"use client";

import { ExternalLink, Loader2, MessagesSquare } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { client } from "@/client/client.gen";
import { getWorkflowRunApiV1WorkflowWorkflowIdRunsRunIdGet } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

import { activeMessageId, buildTimeline, type CallRun, recordingAnchor } from "./model";
import { RecordingPlayer, type RecordingPlayerHandle } from "./RecordingPlayer";
import { buildRouting, type RoutingGraphs, transitionToolCallIds } from "./routing";
import { TranscriptTab } from "./TranscriptTab";

// A call's Transcript tab (with its recording, when there is one) in a
// dialog, for pages listing calls (test executions).

function TranscriptBody({ workflowId, runId, agentName }: { workflowId: number; runId: number; agentName: string }) {
  const [run, setRun] = useState<CallRun | null>(null);
  const [graphs, setGraphs] = useState<RoutingGraphs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [agentOnset, setAgentOnset] = useState<number | null>(null);
  const player = useRef<RecordingPlayerHandle>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [runResponse, routing] = await Promise.all([
        getWorkflowRunApiV1WorkflowWorkflowIdRunsRunIdGet({ path: { workflow_id: workflowId, run_id: runId } }),
        client.get<{ 200: RoutingGraphs }, unknown>({ url: `/api/v1/oxee/runs/${runId}/routing` }),
      ]);
      if (cancelled) return;
      setGraphs(routing.error ? null : ((routing.data as RoutingGraphs) ?? null));
      if (runResponse.error || !runResponse.data) setError("This call could not be loaded.");
      else setRun(runResponse.data as unknown as CallRun);
    })();
    return () => {
      cancelled = true;
    };
  }, [workflowId, runId]);

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
  const activeId = useMemo(() => activeMessageId(timeline, time), [timeline, time]);
  const seek = useCallback((seconds: number) => player.current?.seek(seconds), []);
  const onAgentOnset = useCallback((seconds: number | null) => setAgentOnset(seconds), []);

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!run) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading the call…
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {run.recording_url && (
        <RecordingPlayer
          ref={player}
          mixedKey={run.recording_url ?? null}
          userKey={run.user_recording_url ?? null}
          agentKey={run.bot_recording_url ?? null}
          onTime={setTime}
          onAgentOnset={onAgentOnset}
        />
      )}
      <TranscriptTab items={timeline} agentName={agentName} activeId={activeId} onSeek={seek} />
    </div>
  );
}

export function TranscriptButton({
  workflowId,
  runId,
  agentName,
  title,
}: {
  workflowId: number;
  runId: number;
  agentName: string;
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button type="button" variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={() => setOpen(true)}>
        <MessagesSquare className="h-3.5 w-3.5" /> Transcript
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="flex max-h-[90vh] flex-col gap-3 sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="truncate pr-6">{title ?? `Call #${runId}`}</DialogTitle>
            <DialogDescription className="flex items-center gap-2">
              Agent side of the call (#{runId}).
              <Link href={`/workflow/${workflowId}/run/${runId}`} className="inline-flex items-center gap-1 underline underline-offset-2">
                Open the call <ExternalLink className="h-3 w-3" />
              </Link>
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">{open && <TranscriptBody workflowId={workflowId} runId={runId} agentName={agentName} />}</div>
        </DialogContent>
      </Dialog>
    </>
  );
}
