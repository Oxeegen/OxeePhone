"use client";

import { Download, Search } from "lucide-react";
import { Fragment, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { type EventCategory, type EventRow, formatOffset } from "./model";

const CATEGORY_STYLE: Record<EventCategory, string> = {
  transcript: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  agent: "bg-[#8E80FF]/15 text-[#6D5BFF] dark:text-[#A89DFF]",
  tool: "bg-pink-500/15 text-pink-600 dark:text-pink-400",
  node: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  latency: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
  error: "bg-destructive/15 text-destructive",
  system: "bg-muted text-muted-foreground",
};

const time = (epochMs: number | null) =>
  epochMs === null
    ? ""
    : new Date(epochMs).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", fractionalSecondDigits: 3 });

export function EventsTab({ rows, runId, onSeek }: { rows: EventRow[]; runId: number; onSeek: (seconds: number) => void }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<EventCategory | "all">("all");
  const [open, setOpen] = useState<Set<number>>(new Set());

  const categories = useMemo(() => Array.from(new Set(rows.map((r) => r.category))), [rows]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter(
      (r) =>
        (category === "all" || r.category === category) &&
        (!q || `${r.label} ${r.summary} ${r.node ?? ""} ${JSON.stringify(r.raw.payload)}`.toLowerCase().includes(q)),
    );
  }, [rows, query, category]);

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(rows.map((r) => r.raw), null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `call-${runId}-events.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const toggle = (index: number) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  return (
    <div className="space-y-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8" placeholder="Search events" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="flex flex-wrap gap-1">
          {(["all", ...categories] as const).map((c) => (
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
        <span className="text-sm text-muted-foreground">{filtered.length} events</span>
        <Button type="button" variant="outline" size="sm" className="gap-2" onClick={exportJson}>
          <Download className="h-4 w-4" /> Export
        </Button>
      </div>
      <div className="overflow-x-auto rounded-xl border border-border/70">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Time</th>
              <th className="px-3 py-2 text-left font-medium">Call</th>
              <th className="px-3 py-2 text-left font-medium">Category</th>
              <th className="px-3 py-2 text-left font-medium">Event</th>
              <th className="px-3 py-2 text-left font-medium">Node</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <Fragment key={r.index}>
                <tr className="cursor-pointer border-t border-border/50 align-top hover:bg-muted/30" onClick={() => toggle(r.index)}>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-muted-foreground">{time(r.timeMs)}</td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">
                    {r.offset !== null ? (
                      <button
                        type="button"
                        className="underline-offset-2 hover:underline"
                        title="Play from here"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSeek(Math.max(0, r.offset ?? 0));
                        }}
                      >
                        {formatOffset(r.offset)}
                      </button>
                    ) : null}
                  </td>
                  <td className="px-3 py-2">
                    <span className={cn("rounded px-1.5 py-0.5 text-[11px] capitalize", CATEGORY_STYLE[r.category])}>{r.category}</span>
                  </td>
                  <td className="px-3 py-2">
                    <p className="font-medium">{r.label}</p>
                    {r.summary && <p className="line-clamp-2 text-xs text-muted-foreground">{r.summary}</p>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">{r.node ?? ""}</td>
                </tr>
                {open.has(r.index) && (
                  <tr className="border-t border-border/30 bg-muted/20">
                    <td colSpan={5} className="px-3 py-2">
                      <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
                        {JSON.stringify(r.raw, null, 2)}
                      </pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
