"use client";

import {
  Bot,
  Check,
  ChevronDown,
  ExternalLink,
  FlaskConical,
  Loader2,
  RefreshCw,
  Rocket,
  Trash2,
  TriangleAlert,
  Undo2,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { ChangeCard } from "@/brand/versions/DiffViews";
import { client } from "@/client/client.gen";
import { publishWorkflowApiV1WorkflowWorkflowIdPublishPost } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import {
  BUSY,
  type Fix,
  fixability,
  FOLLOW_UP_LABEL,
  type FollowUp,
  type Replay,
  type SimulationCase,
  STATUS_LABEL,
  stepIndex,
  STEPS,
} from "./model";

// Automatic fixes on the Analysis page: one card per finding
// (proposal → draft → simulation → publish). See api/brand/fixes.py.

/** Fixes of a report ("*" for all of them), polled while one is busy. */
export function useReportFixes(reportId: string | null) {
  const auth = useAuth();
  const [fixes, setFixes] = useState<Fix[]>([]);

  const reload = useCallback(async () => {
    if (!reportId) return;
    const response = await client.get<{ 200: Fix[] }, unknown>({
      url: "/api/v1/oxee/fixes",
      query: reportId === "*" ? undefined : { report_id: reportId },
    });
    if (response.data) setFixes(response.data as Fix[]);
  }, [reportId]);

  useEffect(() => {
    setFixes([]);
    if (auth.loading || !auth.isAuthenticated || !reportId) return;
    void reload();
  }, [auth.loading, auth.isAuthenticated, reportId, reload]);

  const busy = fixes.some((f) => BUSY.includes(f.status));
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void reload(), 3000);
    return () => clearInterval(timer);
  }, [busy, reload]);

  return { fixes, reload };
}

export async function requestFixes(reportId: string, language: string, findingId?: string): Promise<Fix[] | null> {
  const response = await client.post<{ 200: Fix[] }, unknown>({
    url: "/api/v1/oxee/fixes",
    body: { report_id: reportId, finding_id: findingId ?? null, language },
    headers: { "Content-Type": "application/json" },
  });
  if (response.error) {
    toast.error(detailFromError(response.error, "Could not ask for a fix"));
    return null;
  }
  return response.data as Fix[];
}

function Stepper({ fix }: { fix: Fix }) {
  const current = stepIndex(fix.status);
  const done = (i: number) =>
    i < current || (i === current && (fix.status === "tested" || fix.status === "published" || fix.status === "applied"));
  return (
    <ol className="flex flex-wrap items-center gap-1 text-[11px]">
      {STEPS.map((step, i) => (
        <li key={step} className="flex items-center gap-1">
          {i > 0 && <span className="h-px w-4 bg-border" />}
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
              done(i) ? "border-emerald-500/40 text-emerald-700 dark:text-emerald-300" : i === current ? "border-[var(--cta)] text-foreground" : "border-border text-muted-foreground",
            )}
          >
            {done(i) && <Check className="h-3 w-3" />} {step}
          </span>
        </li>
      ))}
    </ol>
  );
}

function PathChips({ path, label }: { path: string[]; label: string }) {
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs">
      <span className="w-20 shrink-0 text-muted-foreground">{label}</span>
      {path.length ? (
        path.map((n, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <span className="text-muted-foreground">→</span>}
            <span className="rounded border border-border px-1.5 py-0.5">{n}</span>
          </span>
        ))
      ) : (
        <span className="text-muted-foreground">—</span>
      )}
    </div>
  );
}

const VERDICT_STYLE: Record<string, string> = {
  pass: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  improved: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  mixed: "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300",
  unchanged: "border-border bg-muted text-muted-foreground",
  inconclusive: "border-border bg-muted text-muted-foreground",
  fail: "border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300",
  regressed: "border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300",
};

const VERDICT_LABEL: Record<string, string> = {
  pass: "Fix works",
  mixed: "Partly works",
  fail: "Does not work",
  inconclusive: "Inconclusive",
  improved: "Improved",
  unchanged: "Unchanged",
  regressed: "Regressed",
};

function Verdict({ value }: { value?: string | null }) {
  if (!value) return null;
  return <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", VERDICT_STYLE[value])}>{VERDICT_LABEL[value] ?? value}</span>;
}

function Conversation({ replay, workflowId, title }: { replay: Replay | null; workflowId: number; title: string }) {
  if (!replay) return <p className="text-xs text-muted-foreground">No published version to compare with.</p>;
  return (
    <div className="min-w-0 space-y-1.5">
      <p className="flex items-center gap-2 text-xs font-medium">
        {title}
        <Link href={`/workflow/${workflowId}/run/${replay.run_id}`} className="inline-flex items-center gap-0.5 font-normal text-muted-foreground hover:text-foreground">
          run #{replay.run_id} <ExternalLink className="h-3 w-3" />
        </Link>
      </p>
      {replay.error && <p className="text-xs text-destructive">{replay.error}</p>}
      <div className="max-h-80 space-y-1 overflow-y-auto rounded-md border border-border/70 p-2 text-xs">
        {replay.transcript.map((m, i) =>
          m.role === "system" ? (
            <p key={i} className="text-center text-[11px] text-muted-foreground">{m.text}</p>
          ) : (
            <p key={i} className={cn("rounded px-2 py-1", m.role === "caller" ? "mr-6 bg-muted" : "ml-6 bg-[var(--cta)]/10")}>
              {m.text}
            </p>
          ),
        )}
      </div>
    </div>
  );
}

function CaseCard({ c, workflowId }: { c: SimulationCase; workflowId: number }) {
  const [open, setOpen] = useState(false);
  const m0 = c.baseline?.metrics;
  const m1 = c.candidate.metrics;
  const rows: Array<[string, keyof NonNullable<typeof m1>]> = [
    ["Steps", "steps"],
    ["Revisits", "revisits"],
    ["Back-and-forth", "ping_pong"],
    ["Max replies in a node", "max_replies_in_a_node"],
  ];
  return (
    <div className="space-y-2 rounded-lg border border-border/70 p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">Case {c.case}</span>
        <Link href={`/workflow/${workflowId}/run/${c.source_call}`} className="text-xs text-muted-foreground hover:text-foreground">
          from call #{c.source_call} · {c.caller_turns} caller turns
        </Link>
        <Verdict value={c.verdict} />
      </div>
      {c.notes && <p className="text-sm">{c.notes}</p>}
      <div className="space-y-1">
        <PathChips label="Real call" path={c.original_path} />
        <PathChips label="Published" path={c.baseline?.path ?? []} />
        <PathChips label="Draft" path={c.candidate.path} />
      </div>
      {m1 && (
        <table className="text-xs tabular-nums">
          <thead>
            <tr className="text-muted-foreground">
              <th className="pr-4 text-left font-normal" />
              <th className="pr-4 text-right font-normal">Published</th>
              <th className="text-right font-normal">Draft</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, key]) => (
              <tr key={key}>
                <td className="pr-4 text-muted-foreground">{label}</td>
                <td className="pr-4 text-right">{m0 ? m0[key] : "—"}</td>
                <td className={cn("text-right", m0 && m1[key] < m0[key] && "font-semibold text-emerald-700 dark:text-emerald-300", m0 && m1[key] > m0[key] && "font-semibold text-rose-700 dark:text-rose-300")}>
                  {m1[key]}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} /> Conversations
      </button>
      {open && (
        <div className="grid gap-3 md:grid-cols-2">
          <Conversation replay={c.baseline} workflowId={workflowId} title="Published version" />
          <Conversation replay={c.candidate} workflowId={workflowId} title="Draft with the fix" />
        </div>
      )}
    </div>
  );
}

const FOLLOW_UP_STYLE: Record<FollowUp["status"], string> = {
  fixed: VERDICT_STYLE.pass,
  still_present: VERDICT_STYLE.mixed,
  worse: VERDICT_STYLE.fail,
  waiting: VERDICT_STYLE.unchanged,
  manual: VERDICT_STYLE.unchanged,
};

function FollowUpSection({ fix, onChanged }: { fix: Fix; onChanged: () => void }) {
  const [busy, setBusy] = useState<"check" | "rollback" | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const f = fix.follow_up;

  const check = async () => {
    setBusy("check");
    const response = await client.post<{ 200: FollowUp }, unknown>({ url: `/api/v1/oxee/fixes/${fix.id}/follow-up` });
    setBusy(null);
    if (response.error) toast.error(detailFromError(response.error, "Could not check the calls"));
    onChanged();
  };

  const rollback = async (replaceDraft: boolean) => {
    setBusy("rollback");
    const response = await client.post<{ 200: Fix }, unknown>({
      url: `/api/v1/oxee/fixes/${fix.id}/rollback`,
      body: { replace_draft: replaceDraft },
      headers: { "Content-Type": "application/json" },
    });
    setBusy(null);
    if (response.error) {
      const status = (response as { response?: Response }).response?.status;
      const message = detailFromError(response.error, "The rollback failed");
      if (status === 409 && message.includes("replace_draft")) setConfirm(message);
      else toast.error(message);
      return;
    }
    setConfirm(null);
    toast.success(`Rolled back: v${(response.data as Fix).rolled_back_to} is published`);
    onChanged();
  };

  return (
    <div className="space-y-2 rounded-md border border-border/70 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">Follow-up on real calls</span>
        {f && (
          <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", FOLLOW_UP_STYLE[f.status])}>
            {FOLLOW_UP_LABEL[f.status]}
          </span>
        )}
        {f && <span className="text-[11px] text-muted-foreground">checked {new Date(f.checked_at).toLocaleString()}</span>}
      </div>
      {fix.status === "rolled_back" ? (
        <p className="text-sm">Rolled back: v{fix.rolled_back_to} put the previous version back in production.</p>
      ) : !f ? (
        <p className="text-sm text-muted-foreground">
          Once the new version has answered a few calls, check whether the problem is gone from them (same rules as the
          analysis, on the calls before and after the fix).
        </p>
      ) : f.status === "waiting" ? (
        <p className="text-sm text-muted-foreground">
          {f.calls_after} call{f.calls_after > 1 ? "s" : ""} on the fixed version so far; at least {f.min_calls} are needed.
        </p>
      ) : f.status === "manual" ? (
        <p className="text-sm text-muted-foreground">{f.note}</p>
      ) : (
        <p className="text-sm">
          {f.calls_after} call{f.calls_after > 1 ? "s" : ""} after the fix, {f.calls_before ?? 0} before.{" "}
          {f.status === "fixed"
            ? "The problem no longer shows."
            : f.after
              ? `Still observed after: “${f.after.title}” (${f.after.severity}${f.before ? `, before: ${f.before.severity}` : ""}).`
              : ""}
        </p>
      )}
      {confirm && (
        <div className="space-y-2 rounded-md border border-amber-500/40 p-2 text-sm">
          <p>{confirm}.</p>
          <div className="flex gap-2">
            <Button size="sm" variant="destructive" disabled={busy !== null} onClick={() => void rollback(true)}>Discard it and roll back</Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
          </div>
        </div>
      )}
      {fix.status === "published" && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" className="gap-1.5" disabled={busy !== null} onClick={() => void check()}>
            {busy === "check" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Check the calls
          </Button>
          <Button
            size="sm"
            variant={f && (f.status === "still_present" || f.status === "worse") ? "destructive" : "ghost"}
            className="gap-1.5"
            disabled={busy !== null}
            onClick={() => {
              if (window.confirm(`Put back v${fix.base_version_number ?? "?"} (the version before the fix) as a new published version? Every fix of v${fix.draft_version_number} is undone with it.`)) void rollback(false);
            }}
          >
            {busy === "rollback" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Undo2 className="h-4 w-4" />} Roll back
          </Button>
        </div>
      )}
    </div>
  );
}

export function FixControls({
  finding,
  fix,
  reportId,
  language,
  onChanged,
  prior,
  defaultOpen = false,
}: {
  finding: { id: string; rule: string | null; category: string };
  fix: Fix | undefined;
  reportId: string;
  language: string;
  onChanged: () => void;
  /** A fix of the same problem published from an earlier report. */
  prior?: Fix;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [detail, setDetail] = useState<Fix | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmReplace, setConfirmReplace] = useState<string | null>(null);
  const lastStatus = useRef<string | null>(null);

  const loadDetail = useCallback(async (id: string) => {
    const response = await client.get<{ 200: Fix }, unknown>({ url: `/api/v1/oxee/fixes/${id}` });
    if (response.data) setDetail(response.data as Fix);
  }, []);

  // Reload the detail when the fix moves on (polled by the page).
  useEffect(() => {
    if (!fix || !open) return;
    const key = `${fix.id}:${fix.status}:${fix.updated_at}`;
    if (lastStatus.current === key) return;
    lastStatus.current = key;
    void loadDetail(fix.id);
  }, [fix, open, loadDetail]);

  const call = async (label: string, url: string, body: object = {}) => {
    setBusy(label);
    const response = await client.post<{ 200: Fix }, unknown>({ url, body, headers: { "Content-Type": "application/json" } });
    setBusy(null);
    if (response.error) {
      const status = (response as { response?: Response }).response?.status;
      if (status === 409 && label === "apply") {
        setConfirmReplace(detailFromError(response.error, "A draft made by hand exists"));
        return false;
      }
      toast.error(detailFromError(response.error, "The action failed"));
      return false;
    }
    onChanged();
    if (fix) void loadDetail(fix.id);
    return true;
  };

  const publish = async () => {
    if (!fix?.workflow_id) return;
    setBusy("publish");
    const response = await publishWorkflowApiV1WorkflowWorkflowIdPublishPost({ path: { workflow_id: fix.workflow_id } });
    setBusy(null);
    if (response.error) {
      toast.error(detailFromError(response.error, "The draft could not be published"));
      return;
    }
    toast.success(`Draft v${fix.draft_version_number} published`);
    onChanged();
  };

  const priorNote = prior && (
    <p className="flex items-center gap-1.5 text-xs text-amber-800 dark:text-amber-300">
      <TriangleAlert className="h-3.5 w-3.5" />
      A fix for this was {prior.status === "rolled_back" ? "published then rolled back" : `published in v${prior.draft_version_number}`} on{" "}
      {new Date(prior.updated_at).toLocaleDateString()}, and the problem is still observed.
    </p>
  );

  if (!fix) {
    const fx = fixability(finding);
    if (!fx.fixable) {
      return <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Wrench className="h-3.5 w-3.5" /> Not fixable automatically: {fx.reason}</p>;
    }
    return (
      <div className="space-y-2">
        {priorNote}
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          disabled={busy !== null}
          onClick={async () => {
            setBusy("create");
            const created = await requestFixes(reportId, language, finding.id);
            setBusy(null);
            if (created) {
              setOpen(true);
              onChanged();
            }
          }}
        >
          {busy === "create" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4" />} Propose a fix
        </Button>
      </div>
    );
  }

  const d = detail && detail.id === fix.id ? { ...detail, ...fix, preview: detail.preview, preview_error: detail.preview_error } : fix;
  const sim = d.simulation;
  const wf = d.workflow_id ?? 0;

  return (
    <div className="space-y-2">
    {["proposing", "proposed", "discarded", "not_fixable", "failed"].includes(fix.status) && priorNote}
    <div className="space-y-3 rounded-lg border border-[var(--cta)]/30 bg-[var(--cta)]/[0.03] p-3">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full flex-wrap items-center gap-2 text-left">
        <Wrench className="h-4 w-4 text-[var(--cta)]" />
        <span className="text-sm font-medium">Automatic fix</span>
        <span className="text-xs text-muted-foreground">{STATUS_LABEL[d.status]}</span>
        {BUSY.includes(d.status) && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        {sim?.verdict && <Verdict value={sim.verdict} />}
        <ChevronDown className={cn("ml-auto h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-3">
          <Stepper fix={d} />
          {d.status === "proposing" && <p className="text-sm text-muted-foreground">The analysis model is reading the agent and the calls to propose a fix…</p>}
          {d.status === "not_fixable" && <p className="text-sm">{d.reason}</p>}
          {d.status === "failed" && <p className="text-sm text-destructive">{d.error}</p>}
          {d.review && d.review_reason && (
            <p className="flex items-start gap-1.5 rounded-md bg-amber-500/10 p-2 text-xs text-amber-900 dark:text-amber-200">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {d.review_reason} Check that a fix is really wanted.
            </p>
          )}

          {d.proposal && (
            <div className="space-y-2">
              <p className="text-sm font-medium">{d.proposal.summary}</p>
              {d.proposal.rationale && <p className="text-sm text-muted-foreground">{d.proposal.rationale}</p>}
              {d.proposal.expected_effect && (
                <p className="text-sm"><span className="text-muted-foreground">Expected effect: </span>{d.proposal.expected_effect}</p>
              )}
              {d.proposal.risks.length > 0 && (
                <ul className="list-disc space-y-0.5 rounded-md bg-amber-500/10 py-2 pl-7 pr-2 text-xs">
                  {d.proposal.risks.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              )}
              {d.model && <p className="flex items-center gap-1 text-[11px] text-muted-foreground"><Bot className="h-3 w-3" /> {d.model} · based on v{d.base_version_number}</p>}
              {d.preview?.changes?.length ? (
                <div className="space-y-2">{d.preview.changes.map((c) => <ChangeCard key={`${c.scope}:${c.id}`} change={c} />)}</div>
              ) : d.preview_error ? (
                <p className="text-xs text-destructive">{d.preview_error}</p>
              ) : null}
            </div>
          )}

          {d.draft_version_number && ["applied", "testing", "tested", "published"].includes(d.status) && (
            <p className="text-sm">
              {d.status === "published" ? "Published as " : "Saved as draft "}
              <Link href={`/workflow/${wf}/versions`} className="font-medium underline-offset-2 hover:underline">v{d.draft_version_number}</Link>
              {d.combined_with?.length ? ` (with ${d.combined_with.length} other fix${d.combined_with.length > 1 ? "es" : ""})` : ""}
              {d.status !== "published" && " — the published version keeps answering calls."}
            </p>
          )}

          {(d.status === "published" || d.status === "rolled_back") && <FollowUpSection fix={d} onChanged={() => { onChanged(); void loadDetail(d.id); }} />}

          {sim && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <FlaskConical className="h-4 w-4 text-[var(--cta)]" />
                <span className="text-sm font-medium">Simulation</span>
                {sim.status === "queued" ? (
                  <span className="text-xs text-muted-foreground">Waiting for another simulation to finish…</span>
                ) : sim.status === "running" || sim.status === "starting" ? (
                  <span className="text-xs text-muted-foreground">
                    Replaying call {Math.min((sim.cases?.length ?? 0) + 1, sim.total ?? 1)} of {sim.total ?? "…"} on the published version and the draft…
                  </span>
                ) : (
                  <Verdict value={sim.verdict} />
                )}
                {sim.model && <span className="text-[11px] text-muted-foreground">judged by {sim.model}</span>}
              </div>
              {sim.error && <p className="text-sm text-destructive">{sim.error}</p>}
              {sim.judge_error && (
                <p className="text-xs text-muted-foreground">
                  No verdict: the analysis model could not be reached ({sim.judge_error.slice(0, 120)}). The replays and metrics below are complete; test again for a verdict.
                </p>
              )}
              {sim.summary && <p className="text-sm">{sim.summary}</p>}
              <p className="text-[11px] text-muted-foreground">
                The caller&apos;s words are replayed as text from real calls, whatever the agent answers; tools are not
                executed (their recorded results are replayed).
              </p>
              {sim.cases?.map((c) => <CaseCard key={c.case} c={c} workflowId={wf} />)}
            </div>
          )}

          {confirmReplace && (
            <div className="space-y-2 rounded-md border border-amber-500/40 p-2 text-sm">
              <p>{confirmReplace}.</p>
              <div className="flex gap-2">
                <Button size="sm" variant="destructive" disabled={busy !== null} onClick={async () => { if (await call("apply", `/api/v1/oxee/fixes/${d.id}/apply`, { replace_draft: true })) setConfirmReplace(null); }}>
                  Discard it and apply the fix
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmReplace(null)}>Cancel</Button>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            {d.status === "proposed" && (
              <Button size="sm" className="gap-1.5" disabled={busy !== null} onClick={() => void call("apply", `/api/v1/oxee/fixes/${d.id}/apply`)}>
                {busy === "apply" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} Apply to a draft
              </Button>
            )}
            {(d.status === "applied" || d.status === "tested") && (
              <Button size="sm" variant={d.status === "tested" ? "outline" : "default"} className="gap-1.5" disabled={busy !== null} onClick={() => void call("simulate", `/api/v1/oxee/fixes/${d.id}/simulate`)}>
                {busy === "simulate" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
                {d.status === "tested" ? "Test again" : "Test by simulation"}
              </Button>
            )}
            {d.status === "tested" && (
              <Button size="sm" className="gap-1.5" disabled={busy !== null} onClick={() => void publish()}>
                {busy === "publish" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />} Publish v{d.draft_version_number}
              </Button>
            )}
            {["proposed", "failed", "not_fixable"].includes(d.status) && (
              <Button size="sm" variant="outline" className="gap-1.5" disabled={busy !== null} onClick={() => void call("propose", `/api/v1/oxee/fixes/${d.id}/propose`)}>
                <RefreshCw className="h-4 w-4" /> {d.status === "proposed" ? "Another proposal" : "Try again"}
              </Button>
            )}
            {["proposed", "applied", "tested"].includes(d.status) && (
              <Button size="sm" variant="ghost" className="gap-1.5" disabled={busy !== null} onClick={() => void call("discard", `/api/v1/oxee/fixes/${d.id}/discard`)}>
                <Trash2 className="h-4 w-4" /> Discard
              </Button>
            )}
            {d.status === "discarded" && (
              <Button size="sm" variant="outline" className="gap-1.5" disabled={busy !== null} onClick={async () => { setBusy("create"); await requestFixes(reportId, language, finding.id); setBusy(null); onChanged(); }}>
                <Wrench className="h-4 w-4" /> Propose a new fix
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
    </div>
  );
}
