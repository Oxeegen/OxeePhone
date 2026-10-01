// Agent routing model: the path a call took through the agent graph(s), and
// why each move happened.
//
// Each out-edge of a node is exposed to the LLM as a tool named after the edge
// label and described by its condition; the LLM calls it when it judges the
// condition met. Logs record the node transition and, a few ms apart, that
// tool call — matching the tool name against the previous node's out-edges
// recovers the edge (label + condition). Handoffs to another agent come from
// gathered_context.agent_visits / agent_transfers.

import { type CallRun, events, type FeedbackEvent, type RecordingAnchor } from "./model";

export interface RoutingNode {
  id: string;
  type: string;
  name: string;
  position: { x: number; y: number };
}

export interface RoutingEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  condition: string;
  tool_name: string;
  transition_speech: string | null;
}

export interface RoutingGraph {
  definition_id: number;
  workflow_id: number;
  workflow_name: string;
  nodes: RoutingNode[];
  edges: RoutingEdge[];
}

export interface RoutingGraphs {
  primary_definition_id: number | null;
  graphs: RoutingGraph[];
}

export interface AgentVisit {
  visitId: string;
  workflowId: number | null;
  workflowName: string;
  definitionId: number | null;
  enteredMs: number | null;
  exitedMs: number | null;
  exitReason: string;
}

export type TransitionCause = "start" | "condition" | "handoff" | "unmatched";

export interface RoutingStep {
  id: string;
  visitIndex: number;
  definitionId: number | null;
  nodeId: string;
  nodeName: string;
  nodeType: string;
  fromNodeId: string | null;
  fromNodeName: string | null;
  cause: TransitionCause;
  edge: RoutingEdge | null;
  toolName: string | null;
  /** Caller's last words before the decision. */
  trigger: string | null;
  atMs: number | null;
  offset: number | null;
  /** Time spent in this node (until the next step or the end of the call). */
  durationSecs: number | null;
  handoffLabel?: string;
}

export interface CallEnding {
  status: string;
  disposition: string;
  endNode: string | null;
  endCallReason: string | null;
  description: string;
}

export interface RoutingModel {
  visits: AgentVisit[];
  steps: RoutingStep[];
  ending: CallEnding;
  graphsByDefinition: Map<number, RoutingGraph>;
}

const str = (v: unknown) => (typeof v === "string" ? v : "");
const ms = (iso?: string | null) => {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
};
/** Transition tool call and node-transition event are logged within ms. */
const MATCH_WINDOW_MS = 5000;

function visitsOf(run: CallRun, primary: number | null, graphs: RoutingGraph[]): AgentVisit[] {
  const raw = (run.gathered_context?.agent_visits as Array<Record<string, unknown>> | undefined) ?? [];
  const visits = raw.map((v, i) => ({
    visitId: str(v.visit_id) || `visit-${i}`,
    workflowId: typeof v.workflow_id === "number" ? v.workflow_id : null,
    workflowName: str(v.workflow_name),
    definitionId: typeof v.definition_id === "number" ? v.definition_id : null,
    enteredMs: typeof v.entered_at === "number" ? v.entered_at * 1000 : null,
    exitedMs: typeof v.exited_at === "number" ? v.exited_at * 1000 : null,
    exitReason: str(v.exit_reason),
  }));
  if (visits.length) return visits;
  const graph = graphs.find((g) => g.definition_id === primary) ?? graphs[0];
  return [
    {
      visitId: "visit-0",
      workflowId: graph?.workflow_id ?? null,
      workflowName: graph?.workflow_name ?? "",
      definitionId: graph?.definition_id ?? primary,
      enteredMs: null,
      exitedMs: null,
      exitReason: "",
    },
  ];
}

function visitIndexAt(visits: AgentVisit[], t: number | null): number {
  if (t === null || visits.length < 2) return 0;
  let index = 0;
  visits.forEach((v, i) => {
    if (v.enteredMs !== null && t >= v.enteredMs - 1000) index = i;
  });
  return index;
}

function lastUserWords(all: FeedbackEvent[], beforeMs: number | null): string | null {
  if (beforeMs === null) return null;
  let text: string | null = null;
  for (const e of all) {
    const t = ms(e.timestamp);
    if (e.type !== "rtf-user-transcription" || t === null || t > beforeMs + 1500) continue;
    if (e.payload.final === false) continue;
    const words = str(e.payload.text).trim();
    if (words) text = words;
  }
  return text;
}

const ENDING_TEXT: Record<string, string> = {
  end_call: "The agent ended the call",
  user_hangup: "The caller hung up",
  user_idle_max_duration_exceeded: "Caller silent for too long",
  call_duration_exceeded: "Maximum call duration reached",
  pipeline_error: "Stopped on a pipeline error",
  transfer_call: "Transferred to a phone number",
  transfer_agent: "Handed off to another agent",
  voicemail_detected: "Voicemail detected",
};

export function buildRouting(run: CallRun, data: RoutingGraphs | null, anchor: RecordingAnchor | null): RoutingModel {
  const graphs = data?.graphs ?? [];
  const graphsByDefinition = new Map(graphs.map((g) => [g.definition_id, g]));
  const visits = visitsOf(run, data?.primary_definition_id ?? null, graphs);
  const all = events(run);
  const toolStarts = all.filter((e) => e.type === "rtf-function-call-start");
  const usedToolCalls = new Set<string>();

  const steps: RoutingStep[] = [];
  let lastVisit = -1;
  for (const [index, e] of all.entries()) {
    if (e.type !== "rtf-node-transition") continue;
    const atMs = ms(e.timestamp);
    const visitIndex = visitIndexAt(visits, atMs);
    const visit = visits[visitIndex];
    const graph = visit.definitionId !== null ? graphsByDefinition.get(visit.definitionId) : undefined;
    const nodeId = str(e.payload.node_id) || str(e.node_id);
    const node = graph?.nodes.find((n) => n.id === nodeId);
    const fromNodeId = str(e.payload.previous_node_id) || null;

    let cause: TransitionCause = fromNodeId ? "unmatched" : "start";
    let edge: RoutingEdge | null = null;
    let toolName: string | null = null;
    let handoffLabel: string | undefined;
    if (fromNodeId && graph) {
      const outEdges = graph.edges.filter((ed) => ed.source === fromNodeId);
      const candidates = toolStarts
        .filter((c) => !usedToolCalls.has(str(c.payload.tool_call_id)))
        .map((c) => ({ c, edge: outEdges.find((ed) => ed.tool_name && ed.tool_name === str(c.payload.function_name)) }))
        .filter((x) => x.edge && atMs !== null && Math.abs((ms(x.c.timestamp) ?? 0) - atMs) <= MATCH_WINDOW_MS)
        .sort((a, b) => Math.abs((ms(a.c.timestamp) ?? 0) - (atMs ?? 0)) - Math.abs((ms(b.c.timestamp) ?? 0) - (atMs ?? 0)));
      const match = candidates[0];
      if (match?.edge) {
        edge = match.edge;
        toolName = str(match.c.payload.function_name);
        usedToolCalls.add(str(match.c.payload.tool_call_id));
        cause = "condition";
      } else {
        edge = outEdges.find((ed) => ed.target === nodeId) ?? null;
      }
    } else if (!fromNodeId && visitIndex > 0 && visitIndex !== lastVisit) {
      cause = "handoff";
      const transfers = (run.gathered_context?.agent_transfers as Array<Record<string, unknown>> | undefined) ?? [];
      const transfer = transfers.find((t) => t.destination_workflow_id === visit.workflowId);
      handoffLabel = str(transfer?.destination_label) || undefined;
    }
    lastVisit = visitIndex;
    steps.push({
      id: `step-${index}`,
      visitIndex,
      definitionId: visit.definitionId,
      nodeId,
      nodeName: str(e.payload.node_name) || node?.name || nodeId,
      nodeType: node?.type ?? "",
      fromNodeId,
      fromNodeName: str(e.payload.previous_node_name) || null,
      cause,
      edge,
      toolName,
      trigger: cause === "condition" || cause === "unmatched" ? lastUserWords(all, atMs) : null,
      atMs,
      offset: atMs !== null && anchor ? (atMs - anchor.epochMs) / 1000 : null,
      durationSecs: null,
      handoffLabel,
    });
  }

  const callEndMs =
    visits.at(-1)?.exitedMs ??
    all.reduce<number | null>((max, e) => {
      const t = ms(e.timestamp);
      return t !== null && (max === null || t > max) ? t : max;
    }, null);
  steps.forEach((s, i) => {
    const next = steps[i + 1]?.atMs ?? callEndMs;
    s.durationSecs = s.atMs !== null && next !== null ? Math.max(0, (next - s.atMs) / 1000) : null;
  });

  const gathered = run.gathered_context ?? {};
  const status = str(gathered.call_status);
  const disposition = str(gathered.mapped_call_disposition) || str(gathered.call_disposition);
  const endStep = [...steps].reverse().find((s) => s.nodeType === "endCall") ?? null;
  const endCallTool = [...toolStarts].reverse().find((e) => str(e.payload.function_name).includes("end_call"));
  const endCallReason = endCallTool ? str((endCallTool.payload.arguments as Record<string, unknown> | undefined)?.reason) || null : null;
  let description = ENDING_TEXT[status] ?? (status ? status.replace(/_/g, " ") : "Call ended");
  if (status === "end_call" && endStep) description = `Reached the end node “${endStep.nodeName}”`;
  return {
    visits,
    steps,
    ending: { status, disposition, endNode: endStep?.nodeName ?? null, endCallReason, description },
    graphsByDefinition,
  };
}

/** Tool calls that are node transitions (hidden from the transcript's tool cards). */
export function transitionToolCallIds(run: CallRun, model: RoutingModel): Set<string> {
  const names = new Set<string>();
  for (const graph of model.graphsByDefinition.values()) {
    for (const edge of graph.edges) if (edge.tool_name) names.add(edge.tool_name);
  }
  return new Set(
    events(run)
      .filter((e) => e.type === "rtf-function-call-start" && names.has(str(e.payload.function_name)))
      .map((e) => str(e.payload.tool_call_id)),
  );
}
