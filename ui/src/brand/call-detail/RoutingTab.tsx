"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  type Edge,
  Handle,
  MarkerType,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
} from "@xyflow/react";
import { ArrowRight, Flag, GitBranch, MessageSquareQuote, PhoneForwarded, PlayCircle, Quote } from "lucide-react";
import { useMemo } from "react";

import { cn } from "@/lib/utils";

import { formatOffset } from "./model";
import type { RoutingGraph, RoutingModel, RoutingStep } from "./routing";

const VIOLET = "#8E80FF";

const NODE_TYPE_LABEL: Record<string, string> = {
  startCall: "Start",
  agentNode: "Agent",
  endCall: "End",
  globalNode: "Global",
};

type RouteNodeData = { name: string; type: string; order: number[]; visited: boolean };

function RouteNode({ data }: NodeProps<Node<RouteNodeData>>) {
  return (
    <div
      className={cn(
        "min-w-40 rounded-lg border bg-card px-3 py-2 text-left shadow-sm",
        data.visited ? "border-[#8E80FF] ring-2 ring-[#8E80FF]/25" : "border-border opacity-55",
      )}
    >
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5 !border-0 !bg-muted-foreground/50" />
      <div className="flex items-center gap-1.5">
        <span className="rounded bg-muted px-1 py-0.5 text-[9px] uppercase tracking-wide text-muted-foreground">
          {NODE_TYPE_LABEL[data.type] ?? data.type}
        </span>
        {data.order.map((n) => (
          <span key={n} className="flex h-4 min-w-4 items-center justify-center rounded-full bg-[#8E80FF] px-1 text-[10px] font-semibold text-white">
            {n}
          </span>
        ))}
      </div>
      <p className="mt-1 text-sm font-medium">{data.name}</p>
      <Handle type="source" position={Position.Bottom} className="!h-1.5 !w-1.5 !border-0 !bg-muted-foreground/50" />
    </div>
  );
}

const nodeTypes = { route: RouteNode };

function AgentGraph({ graph, steps }: { graph: RoutingGraph; steps: RoutingStep[] }) {
  const { nodes, edges } = useMemo(() => {
    const order = new Map<string, number[]>();
    steps.forEach((s, i) => order.set(s.nodeId, [...(order.get(s.nodeId) ?? []), i + 1]));
    const taken = new Set(steps.map((s) => s.edge?.id).filter(Boolean) as string[]);
    const flowNodes: Node<RouteNodeData>[] = graph.nodes
      .filter((n) => n.type !== "globalNode" || order.has(n.id))
      .map((n) => ({
        id: n.id,
        type: "route",
        position: n.position,
        data: { name: n.name, type: n.type, order: order.get(n.id) ?? [], visited: order.has(n.id) },
        draggable: false,
        selectable: false,
      }));
    const flowEdges: Edge[] = graph.edges.map((e) => {
      const isTaken = taken.has(e.id);
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        animated: isTaken,
        markerEnd: { type: MarkerType.ArrowClosed, color: isTaken ? VIOLET : "#71717a" },
        style: { stroke: isTaken ? VIOLET : "#71717a", strokeWidth: isTaken ? 2.5 : 1, opacity: isTaken ? 1 : 0.5, strokeDasharray: isTaken ? undefined : "4 4" },
        labelStyle: { fontSize: 11, fill: isTaken ? VIOLET : "#a1a1aa", fontWeight: isTaken ? 600 : 400 },
        labelBgStyle: { fill: "var(--card)" },
      };
    });
    return { nodes: flowNodes, edges: flowEdges };
  }, [graph, steps]);

  return (
    <div className="h-[440px] overflow-hidden rounded-xl border border-border/70 bg-muted/10">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        panOnScroll
        proOptions={{ hideAttribution: true }}
        colorMode="system"
      >
        <Background gap={20} size={1} />
      </ReactFlow>
    </div>
  );
}

function StepCard({ step, index, onSeek }: { step: RoutingStep; index: number; onSeek: (s: number) => void }) {
  const icon =
    step.cause === "start" ? <PlayCircle className="h-4 w-4" /> : step.cause === "handoff" ? <PhoneForwarded className="h-4 w-4" /> : <GitBranch className="h-4 w-4" />;
  return (
    <li className="relative flex gap-3">
      <div className="flex flex-col items-center">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#8E80FF]/15 text-[#8E80FF]">{icon}</span>
        <span className="mt-1 w-px flex-1 bg-border" />
      </div>
      <div className="mb-4 min-w-0 flex-1 space-y-2 rounded-xl border border-border/70 p-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[#8E80FF] px-1 text-[11px] font-semibold text-white">{index + 1}</span>
          {step.fromNodeName && (
            <>
              <span className="text-muted-foreground">{step.fromNodeName}</span>
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
            </>
          )}
          <span className="font-semibold">{step.nodeName}</span>
          {step.durationSecs !== null && (
            <span className="text-xs text-muted-foreground">· {step.durationSecs.toFixed(1)} s in this node</span>
          )}
          {step.offset !== null && (
            <button type="button" onClick={() => onSeek(Math.max(0, step.offset ?? 0))} className="ml-auto font-mono text-xs text-muted-foreground hover:text-foreground hover:underline" title="Play from here">
              {formatOffset(step.offset)}
            </button>
          )}
        </div>

        {step.cause === "start" && <p className="text-sm text-muted-foreground">The call starts here.</p>}
        {step.cause === "handoff" && (
          <p className="text-sm text-muted-foreground">
            Handed off to this agent{step.handoffLabel ? <> by the tool <span className="font-mono">{step.handoffLabel}</span></> : null}.
          </p>
        )}
        {(step.cause === "condition" || step.cause === "unmatched") && (
          <div className="space-y-2 text-sm">
            {step.edge ? (
              <div className="rounded-lg bg-muted/50 p-2.5">
                <p className="text-[11px] font-medium uppercase text-muted-foreground">
                  Pathway “{step.edge.label}” · condition
                </p>
                <p className="mt-0.5">{step.edge.condition}</p>
              </div>
            ) : (
              <p className="text-muted-foreground">Pathway not found in the agent graph.</p>
            )}
            <p className="text-xs text-muted-foreground">
              {step.cause === "condition" ? (
                <>The LLM judged this condition met and called <span className="font-mono">{step.toolName}</span>.</>
              ) : (
                <>No matching decision was recorded for this move.</>
              )}
            </p>
            {step.trigger && (
              <p className="flex items-start gap-1.5 text-xs">
                <MessageSquareQuote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#E0A42A]" />
                <span><span className="text-muted-foreground">Caller had just said:</span> “{step.trigger}”</span>
              </p>
            )}
            {step.edge?.transition_speech && (
              <p className="flex items-start gap-1.5 text-xs">
                <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#8E80FF]" />
                <span><span className="text-muted-foreground">Transition speech:</span> “{step.edge.transition_speech}”</span>
              </p>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

export function RoutingTab({ model, onSeek, loading }: { model: RoutingModel | null; onSeek: (s: number) => void; loading: boolean }) {
  if (loading) return <p className="py-10 text-center text-sm text-muted-foreground">Loading routing…</p>;
  if (!model || !model.steps.length) {
    return <p className="py-10 text-center text-sm text-muted-foreground">No routing recorded for this call.</p>;
  }
  const byVisit = model.visits.map((visit, i) => ({ visit, steps: model.steps.filter((s) => s.visitIndex === i) }));
  return (
    <div className="space-y-6 py-2">
      {byVisit.map(({ visit, steps }, i) => {
        const graph = visit.definitionId !== null ? model.graphsByDefinition.get(visit.definitionId) : undefined;
        return (
          <section key={visit.visitId} className="space-y-3">
            {model.visits.length > 1 && (
              <h3 className="flex items-center gap-2 font-semibold">
                <span className="rounded bg-muted px-1.5 py-0.5 text-xs">Agent {i + 1}</span>
                {visit.workflowName || graph?.workflow_name}
                {visit.exitReason && <span className="text-xs font-normal text-muted-foreground">· exit: {visit.exitReason.replace(/_/g, " ")}</span>}
              </h3>
            )}
            {graph ? <AgentGraph graph={graph} steps={steps} /> : null}
            <ol>
              {steps.map((step) => (
                <StepCard key={step.id} step={step} index={model.steps.indexOf(step)} onSeek={onSeek} />
              ))}
            </ol>
          </section>
        );
      })}
      <div className="flex items-start gap-3 rounded-xl border border-border/70 p-4">
        <Flag className="mt-0.5 h-4 w-4 text-[var(--cta)]" />
        <div className="space-y-1 text-sm">
          <p className="font-semibold">How the call ended</p>
          <p>{model.ending.description}.</p>
          <p className="text-xs text-muted-foreground">
            Status: {model.ending.status || "—"}
            {model.ending.disposition && model.ending.disposition !== model.ending.status ? ` · disposition: ${model.ending.disposition}` : ""}
            {model.ending.endCallReason ? ` · reason given: ${model.ending.endCallReason}` : ""}
          </p>
        </div>
      </div>
    </div>
  );
}
