"use client";

import { AlertTriangle, ChevronRight, GitBranch, Timer, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { formatOffset, type TimelineItem, type TimelineMessage, type TimelineToolCall } from "./model";

const clock = (epochMs: number | null) =>
  epochMs === null
    ? ""
    : new Date(epochMs).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function Json({ value }: { value: unknown }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/60 p-2 font-mono text-[11px] leading-relaxed">
      {text}
    </pre>
  );
}

function ToolCall({ item }: { item: TimelineToolCall }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mx-auto w-full max-w-xl rounded-lg border border-border/70 bg-card/60 text-sm">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-3 py-2 text-left">
        <Wrench className="h-3.5 w-3.5 text-[var(--cta)]" />
        <span className="font-mono text-xs font-semibold">{item.name}</span>
        <span className={cn("rounded px-1.5 py-0.5 text-[10px] uppercase", item.status === "completed" ? "bg-emerald-500/15 text-emerald-500" : "bg-amber-500/15 text-amber-500")}>
          {item.status}
        </span>
        {item.durationMs !== null && <span className="text-xs text-muted-foreground">{Math.round(item.durationMs)} ms</span>}
        <span className="ml-auto text-[11px] text-muted-foreground">{formatOffset(item.start)}</span>
        <ChevronRight className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <div className="grid gap-2 border-t border-border/60 px-3 py-2 sm:grid-cols-2">
          <div className="space-y-1">
            <p className="text-[11px] font-medium uppercase text-muted-foreground">Arguments</p>
            <Json value={item.args ?? {}} />
          </div>
          <div className="space-y-1">
            <p className="text-[11px] font-medium uppercase text-muted-foreground">Result</p>
            <Json value={item.result ?? "(no result)"} />
          </div>
        </div>
      )}
    </div>
  );
}

function Message({
  item,
  agentName,
  active,
  onSeek,
}: {
  item: TimelineMessage;
  agentName: string;
  active: boolean;
  onSeek: (seconds: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active]);
  const agent = item.role === "agent";
  return (
    <div ref={ref} className={cn("flex flex-col gap-1", agent ? "items-start" : "items-end")}>
      <button
        type="button"
        disabled={item.start === null}
        onClick={() => item.start !== null && onSeek(item.start)}
        title={item.start !== null ? "Play from here" : undefined}
        className={cn(
          "max-w-[78%] rounded-xl border px-4 py-2.5 text-left transition-colors",
          agent ? "border-transparent bg-muted/70" : "border-transparent bg-muted",
          active && (agent ? "border-[#8E80FF] bg-[#8E80FF]/15" : "border-[#F5B83D] bg-[#F5B83D]/15"),
          item.start !== null && "cursor-pointer hover:border-border",
        )}
      >
        <span className={cn("block text-xs font-semibold", agent ? "text-[#8E80FF]" : "text-[#E0A42A] dark:text-[#F5B83D]")}>
          {agent ? agentName : "Caller"}
        </span>
        <span className="block text-sm leading-relaxed">{item.text}</span>
      </button>
      <div className="flex items-center gap-2 px-1 text-[11px] text-muted-foreground">
        <span>
          {clock(item.startMs)} {item.start !== null && <span className="tabular-nums">({formatOffset(item.start)})</span>}
        </span>
        {item.interrupted && (
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-600 dark:text-amber-400">interrupted</span>
        )}
        {item.latencySecs !== undefined && item.latencySecs > 0 && (
          <span className="flex items-center gap-1" title="From the caller falling silent to the agent speaking">
            <Timer className="h-3 w-3" /> {Math.round(item.latencySecs * 1000)} ms
          </span>
        )}
      </div>
    </div>
  );
}

export function TranscriptTab({
  items,
  agentName,
  activeId,
  onSeek,
}: {
  items: TimelineItem[];
  agentName: string;
  activeId: string | null;
  onSeek: (seconds: number) => void;
}) {
  if (!items.length) return <p className="py-10 text-center text-sm text-muted-foreground">No transcript for this call.</p>;
  return (
    <div className="space-y-4 py-2">
      {items.map((item) => {
        if (item.kind === "message") {
          return <Message key={item.id} item={item} agentName={agentName} active={item.id === activeId} onSeek={onSeek} />;
        }
        if (item.kind === "tool") return <ToolCall key={item.id} item={item} />;
        if (item.kind === "node") {
          return (
            <div key={item.id} className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <div className="h-px flex-1 bg-border" />
              <GitBranch className="h-3 w-3" />
              <span>{item.previous ? `${item.previous} → ${item.name}` : item.name}</span>
              <span className="tabular-nums">{formatOffset(item.start)}</span>
              <div className="h-px flex-1 bg-border" />
            </div>
          );
        }
        return (
          <div key={item.id} className="mx-auto flex max-w-xl items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{item.fatal ? "Fatal error: " : ""}{item.text}</span>
          </div>
        );
      })}
    </div>
  );
}
