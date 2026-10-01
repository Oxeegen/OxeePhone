"use client";

import { formatDistanceToNow } from "date-fns";
import {
  ArrowLeft,
  Bot,
  Braces,
  FileCode2,
  GitBranch,
  History,
  KeyRound,
  Loader2,
  Pencil,
  Phone,
  Rocket,
  RotateCcw,
  Sparkles,
  Trash2,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { WorkflowVersionDiffDialog } from "@/app/workflow/[workflowId]/components/WorkflowVersionDiffDialog";
import { client } from "@/client/client.gen";
import {
  getWorkflowApiV1WorkflowFetchWorkflowIdGet,
  getWorkflowVersionsApiV1WorkflowWorkflowIdVersionsGet,
  publishWorkflowApiV1WorkflowWorkflowIdPublishPost,
} from "@/client/sdk.gen";
import type { WorkflowVersionResponse } from "@/client/types.gen";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { ChangeCard } from "./DiffViews";
import {
  type AiSummary,
  countsLabel,
  originLabel,
  personLabel,
  summaryLanguage,
  type VersionDiff,
  type VersionItem,
} from "./model";

const PAGE = 30;

const STATUS_STYLE: Record<string, string> = {
  draft: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  published: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  archived: "border-border bg-muted text-muted-foreground",
};


const ORIGIN_ICON: Record<string, typeof Pencil> = {
  editor: Pencil,
  api: KeyRound,
  mcp: Bot,
  restore: RotateCcw,
  fix: Wrench,
};


const ago = (iso: string | null | undefined) =>
  iso ? formatDistanceToNow(new Date(iso), { addSuffix: true }) : "";

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize", STATUS_STYLE[status])}>
      {status}
    </span>
  );
}

function OriginChip({ v }: { v: VersionItem | VersionDiff["target"] }) {
  const label = originLabel(v);
  if (!label) return null;
  const Icon = ORIGIN_ICON[v.origin ?? ""] ?? GitBranch;
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-border px-1.5 py-0.5 text-[11px]">
      <Icon className="h-3 w-3" /> {label}
    </span>
  );
}

function SummaryCard({
  diff,
  summary,
  busy,
  onGenerate,
}: {
  diff: VersionDiff;
  summary: AiSummary | null;
  busy: boolean;
  onGenerate: () => void;
}) {
  return (
    <div className="space-y-4">
      <Card className="gap-3 p-4">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-[var(--cta)]" />
          <span className="font-medium">Summary by the analysis model</span>
          {summary?.model && <span className="text-xs text-muted-foreground">· {summary.model} · {ago(summary.at)}</span>}
          <Button size="sm" variant="outline" className="ml-auto h-7 gap-1.5 text-xs" disabled={busy || !diff.base} onClick={onGenerate}>
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
            {summary ? "Regenerate" : "Summarize"}
          </Button>
        </div>
        {!diff.base ? (
          <p className="text-sm text-muted-foreground">First version: nothing to compare with.</p>
        ) : summary ? (
          <div className="space-y-3">
            <p className="text-sm font-medium">{summary.headline}</p>
            {summary.points.length > 0 && (
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {summary.points.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            )}
            {summary.risks.length > 0 && (
              <div className="space-y-1 rounded-md bg-amber-500/10 p-2.5">
                <p className="flex items-center gap-1.5 text-xs font-medium text-amber-800 dark:text-amber-300">
                  <TriangleAlert className="h-3.5 w-3.5" /> To check in the next calls
                </p>
                <ul className="list-disc space-y-0.5 pl-5 text-sm">
                  {summary.risks.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            A plain-language summary of these changes and what to watch after publishing. Uses the model set in Models ›
            Analysis.
          </p>
        )}
      </Card>
      <Card className="gap-2 p-4">
        <p className="font-medium">Changes</p>
        {diff.bullets.length ? (
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {diff.bullets.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            Identical to v{diff.base?.version_number}
            {diff.target.origin === "restore" ? " (restored version)" : ""}.
          </p>
        )}
      </Card>
    </div>
  );
}

type Confirm =
  | { kind: "restore"; version: VersionItem; draft: VersionItem | undefined }
  | { kind: "publish"; version: VersionItem }
  | { kind: "discard"; version: VersionItem };

export function VersionsPage({ workflowId }: { workflowId: number }) {
  const auth = useAuth();
  const [name, setName] = useState<string>("");
  const [items, setItems] = useState<VersionItem[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [baseId, setBaseId] = useState<number | null>(null);
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [acting, setActing] = useState(false);
  const [jsonPair, setJsonPair] = useState<[WorkflowVersionResponse, WorkflowVersionResponse] | null>(null);
  const loadedOnce = useRef(false);

  const load = useCallback(
    async (offset = 0) => {
      const response = await client.get<{ 200: { items: VersionItem[]; has_more: boolean } }, unknown>({
        url: `/api/v1/oxee/workflows/${workflowId}/versions`,
        query: { limit: PAGE, offset },
      });
      if (response.error) {
        toast.error(detailFromError(response.error, "Could not load the versions"));
        return [];
      }
      const data = response.data as { items: VersionItem[]; has_more: boolean };
      setItems((prev) => (offset ? [...prev, ...data.items] : data.items));
      setHasMore(data.has_more);
      return data.items;
    },
    [workflowId],
  );

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated || loadedOnce.current) return;
    loadedOnce.current = true;
    (async () => {
      const [wf, list] = await Promise.all([
        getWorkflowApiV1WorkflowFetchWorkflowIdGet({ path: { workflow_id: workflowId } }),
        load(),
      ]);
      setName(wf.data?.name ?? `Agent ${workflowId}`);
      setSelectedId(list[0]?.id ?? null);
      setLoading(false);
    })();
  }, [auth.loading, auth.isAuthenticated, load, workflowId]);

  useEffect(() => {
    if (selectedId == null) return;
    let cancelled = false;
    setDiffLoading(true);
    (async () => {
      const response = await client.get<{ 200: VersionDiff }, unknown>({
        url: `/api/v1/oxee/workflows/${workflowId}/versions/${selectedId}/diff`,
        query: baseId != null ? { base: baseId } : undefined,
      });
      if (cancelled) return;
      setDiffLoading(false);
      if (response.error) {
        toast.error(detailFromError(response.error, "Could not compare the versions"));
        return;
      }
      setDiff(response.data as VersionDiff);
    })();
    return () => {
      cancelled = true;
    };
  }, [workflowId, selectedId, baseId]);

  const selected = items.find((v) => v.id === selectedId);
  const draft = items.find((v) => v.status === "draft");
  const baseOptions = useMemo(() => items.filter((v) => v.id !== selectedId), [items, selectedId]);

  const select = (id: number) => {
    setSelectedId(id);
    setBaseId(null);
  };

  const summarize = async () => {
    if (!diff) return;
    setSummaryBusy(true);
    const response = await client.post<{ 200: AiSummary }, unknown>({
      url: `/api/v1/oxee/workflows/${workflowId}/versions/${diff.target.id}/summary`,
      body: { base: diff.base?.id ?? null, language: summaryLanguage(navigator.language) },
      headers: { "Content-Type": "application/json" },
    });
    setSummaryBusy(false);
    if (response.error) {
      toast.error(detailFromError(response.error, "The model could not summarize this version"));
      return;
    }
    const summary = response.data as AiSummary;
    setDiff((d) => (d ? { ...d, ai_summary: summary } : d));
    if (baseId == null) setItems((list) => list.map((v) => (v.id === diff.target.id ? { ...v, ai_summary: summary } : v)));
  };

  const publish = async () => {
    const response = await publishWorkflowApiV1WorkflowWorkflowIdPublishPost({ path: { workflow_id: workflowId } });
    if (response.error) {
      toast.error(detailFromError(response.error, "The draft could not be published"));
      return false;
    }
    return true;
  };

  const runConfirmed = async (andPublish = false) => {
    if (!confirm) return;
    setActing(true);
    try {
      if (confirm.kind === "restore") {
        const response = await client.post<{ 200: { id: number; version_number: number } }, unknown>({
          url: `/api/v1/oxee/workflows/${workflowId}/versions/${confirm.version.id}/restore`,
          body: { replace_draft: Boolean(confirm.draft) },
          headers: { "Content-Type": "application/json" },
        });
        if (response.error) {
          toast.error(detailFromError(response.error, "Could not restore this version"));
          return;
        }
        const restored = response.data as { id: number; version_number: number };
        if (andPublish && (await publish())) {
          toast.success(`v${confirm.version.version_number} restored and published as v${restored.version_number}`);
        } else if (!andPublish) {
          toast.success(`v${confirm.version.version_number} restored as draft v${restored.version_number}`);
        }
        await load();
        select(restored.id);
      } else if (confirm.kind === "publish") {
        if (await publish()) {
          toast.success(`v${confirm.version.version_number} published`);
          await load();
        }
      } else {
        const response = await client.delete<{ 200: unknown }, unknown>({ url: `/api/v1/oxee/workflows/${workflowId}/draft` });
        if (response.error) {
          toast.error(detailFromError(response.error, "Could not discard the draft"));
          return;
        }
        toast.success(`Draft v${confirm.version.version_number} discarded`);
        const list = await load();
        select(list[0]?.id ?? 0);
      }
    } finally {
      setActing(false);
      setConfirm(null);
    }
  };

  const openJson = async () => {
    if (!diff?.base) return;
    const response = await getWorkflowVersionsApiV1WorkflowWorkflowIdVersionsGet({ path: { workflow_id: workflowId } });
    const all = response.data ?? [];
    const a = all.find((v) => v.id === diff.base?.id);
    const b = all.find((v) => v.id === diff.target.id);
    if (a && b) setJsonPair([a, b]);
  };

  return (
    <div className="container mx-auto space-y-6 p-6">
      <div className="space-y-1">
        <Link href={`/workflow/${workflowId}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> Back to the agent
        </Link>
        <h1 className="flex items-center gap-2 text-3xl font-bold">
          <History className="h-7 w-7 text-[var(--cta)]" /> Versions
          {name && <span className="text-muted-foreground">· {name}</span>}
        </h1>
        <p className="text-muted-foreground">
          Every saved version of the agent — graph, prompts, transitions and settings (speaking plan included) — with who
          made it and how, what changed, and a way back. Restoring creates a draft: the published version keeps
          answering calls until you publish.
        </p>
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
          <div className="space-y-2">
            {items.map((v) => {
              const who = personLabel(v.last_edited_by ?? v.created_by);
              return (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => select(v.id)}
                  className={cn(
                    "w-full space-y-1.5 rounded-lg border p-3 text-left transition-colors",
                    v.id === selectedId ? "border-[var(--cta)] bg-[var(--cta)]/5" : "border-border hover:bg-muted/50",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">v{v.version_number}</span>
                    <StatusBadge status={v.status} />
                    <span className="ml-auto text-xs tabular-nums text-muted-foreground" title="added / removed / changed since the previous version">
                      {countsLabel(v.counts)}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    <OriginChip v={v} />
                    <span>{ago(v.last_edited_at ?? v.published_at ?? v.created_at)}</span>
                    {who && <span className="truncate">· {who}</span>}
                  </div>
                  <p className="line-clamp-2 text-xs">
                    {v.ai_summary?.headline ?? v.bullets.slice(0, 2).join(" · ") ?? ""}
                    {!v.ai_summary && !v.bullets.length && <span className="text-muted-foreground">No functional change</span>}
                  </p>
                  {v.calls ? (
                    <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
                      <Phone className="h-3 w-3" /> {v.calls} call{v.calls > 1 ? "s" : ""}
                    </p>
                  ) : null}
                </button>
              );
            })}
            {hasMore && (
              <Button variant="ghost" className="w-full" onClick={() => void load(items.length)}>
                Load more
              </Button>
            )}
          </div>

          <div className="min-w-0 space-y-4">
            {selected && diff && diff.target.id === selected.id ? (
              <>
                <Card className="gap-3 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xl font-semibold">v{selected.version_number}</span>
                    <StatusBadge status={selected.status} />
                    <OriginChip v={selected} />
                    <div className="ml-auto flex flex-wrap gap-2">
                      {selected.status === "draft" ? (
                        <>
                          <Button size="sm" className="gap-1.5" onClick={() => setConfirm({ kind: "publish", version: selected })}>
                            <Rocket className="h-4 w-4" /> Publish
                          </Button>
                          <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setConfirm({ kind: "discard", version: selected })}>
                            <Trash2 className="h-4 w-4" /> Discard draft
                          </Button>
                        </>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          className="gap-1.5"
                          onClick={() => setConfirm({ kind: "restore", version: selected, draft })}
                        >
                          <RotateCcw className="h-4 w-4" /> Restore
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" className="gap-1.5" asChild>
                        <Link href={`/workflow/${workflowId}`}>
                          <FileCode2 className="h-4 w-4" /> Open in editor
                        </Link>
                      </Button>
                    </div>
                  </div>
                  <div className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                    <p>
                      <span className="text-muted-foreground">Created </span>
                      {ago(selected.created_at)}
                      {personLabel(selected.created_by) && <> by {personLabel(selected.created_by)}</>}
                    </p>
                    {selected.edit_count > 1 && (
                      <p>
                        <span className="text-muted-foreground">Last edit </span>
                        {ago(selected.last_edited_at)} by {personLabel(selected.last_edited_by) ?? "—"} ({selected.edit_count} saves)
                      </p>
                    )}
                    {selected.published_at && (
                      <p>
                        <span className="text-muted-foreground">Published </span>
                        {ago(selected.published_at)}
                        {personLabel(selected.published_by) && <> by {personLabel(selected.published_by)}</>}
                      </p>
                    )}
                    <p>
                      <span className="text-muted-foreground">Calls on this version </span>
                      {selected.calls ?? 0}
                    </p>
                    {selected.note && <p className="sm:col-span-2 text-muted-foreground">{selected.note}</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3 text-sm">
                    <span className="text-muted-foreground">Compared with</span>
                    <Select value={baseId == null ? "previous" : String(baseId)} onValueChange={(v) => setBaseId(v === "previous" ? null : Number(v))}>
                      <SelectTrigger className="h-8 w-56">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="previous">
                          Previous version{selected.base_version_number ? ` (v${selected.base_version_number})` : ""}
                        </SelectItem>
                        {baseOptions.map((v) => (
                          <SelectItem key={v.id} value={String(v.id)}>
                            v{v.version_number} · {v.status}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {diffLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
                    <span className="tabular-nums text-muted-foreground">{countsLabel(diff.counts)}</span>
                    {diff.base && (
                      <Button size="sm" variant="ghost" className="ml-auto h-7 gap-1.5 text-xs" onClick={() => void openJson()}>
                        <Braces className="h-3.5 w-3.5" /> Raw JSON diff
                      </Button>
                    )}
                  </div>
                </Card>

                <Tabs defaultValue="summary">
                  <TabsList>
                    <TabsTrigger value="summary">Summary</TabsTrigger>
                    <TabsTrigger value="details">Detailed changes ({diff.changes.length})</TabsTrigger>
                  </TabsList>
                  <TabsContent value="summary" className="mt-4">
                    <SummaryCard diff={diff} summary={diff.ai_summary} busy={summaryBusy} onGenerate={() => void summarize()} />
                  </TabsContent>
                  <TabsContent value="details" className="mt-4 space-y-3">
                    {diff.changes.length ? (
                      diff.changes.map((c) => <ChangeCard key={`${c.scope}:${c.id}`} change={c} />)
                    ) : (
                      <p className="text-sm text-muted-foreground">No functional change.</p>
                    )}
                  </TabsContent>
                </Tabs>
              </>
            ) : (
              <div className="flex justify-center py-16">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            )}
          </div>
        </div>
      )}

      <AlertDialog open={confirm !== null} onOpenChange={(open) => !open && !acting && setConfirm(null)}>
        <AlertDialogContent>
          {confirm?.kind === "restore" && (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle>Restore v{confirm.version.version_number}?</AlertDialogTitle>
                <AlertDialogDescription>
                  A new draft is created with the graph, settings and variables of v{confirm.version.version_number}.
                  {confirm.draft
                    ? ` The current draft v${confirm.draft.version_number} and its unpublished changes will be discarded.`
                    : ""}{" "}
                  Tools and knowledge base documents are not versioned and stay as they are.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={acting}>Cancel</AlertDialogCancel>
                <Button variant="outline" disabled={acting} onClick={() => void runConfirmed(false)}>
                  {acting && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />} Restore as draft
                </Button>
                <AlertDialogAction disabled={acting} onClick={(e) => { e.preventDefault(); void runConfirmed(true); }}>
                  Restore and publish
                </AlertDialogAction>
              </AlertDialogFooter>
            </>
          )}
          {confirm?.kind === "publish" && (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle>Publish v{confirm.version.version_number}?</AlertDialogTitle>
                <AlertDialogDescription>
                  New calls will use this version. The currently published one is archived and can be restored later.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={acting}>Cancel</AlertDialogCancel>
                <AlertDialogAction disabled={acting} onClick={(e) => { e.preventDefault(); void runConfirmed(); }}>
                  Publish
                </AlertDialogAction>
              </AlertDialogFooter>
            </>
          )}
          {confirm?.kind === "discard" && (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle>Discard draft v{confirm.version.version_number}?</AlertDialogTitle>
                <AlertDialogDescription>
                  Its unpublished changes are lost. The published version is not affected.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={acting}>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  disabled={acting}
                  className="bg-destructive text-white hover:bg-destructive/90"
                  onClick={(e) => { e.preventDefault(); void runConfirmed(); }}
                >
                  Discard
                </AlertDialogAction>
              </AlertDialogFooter>
            </>
          )}
        </AlertDialogContent>
      </AlertDialog>

      {jsonPair && (
        <WorkflowVersionDiffDialog
          open
          onOpenChange={(open) => !open && setJsonPair(null)}
          previousVersion={jsonPair[0]}
          selectedVersion={jsonPair[1]}
        />
      )}
    </div>
  );
}
