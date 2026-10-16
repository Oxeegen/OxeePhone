"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { detailFromError } from "@/lib/apiError";

import { postValue } from "../tests/model";
import { ScoreBadge, techStatus } from "../tests/ui";
import type { CallScore } from "./model";

const SCORE_LABEL: Record<string, string> = {
  understanding: "Understanding",
  accuracy: "Accuracy",
  concision: "Concision",
  tone: "Tone",
  resolution: "Resolution",
};

/** Quality and technical badges of a call (header). */
export function CallScoreBadges({ score }: { score: CallScore | null }) {
  if (!score) return null;
  const q = score.quality?.score ?? null;
  const t = score.technical?.score ?? null;
  return (
    <span className="flex items-center gap-2">
      {q != null && (
        <span title="Quality score: the analysis model's review of the agent">
          <ScoreBadge score={q} status={techStatus(q)} compact />
        </span>
      )}
      {t != null && (
        <span title={`Technical score${score.technical?.weakest ? ` · weakest: ${score.technical.weakest}` : ""}`}>
          <ScoreBadge score={t} status={techStatus(t)} compact />
        </span>
      )}
    </span>
  );
}

/** Quality review and technical grades of a call (Analysis tab). */
export function CallScoreCard({ runId, score, onScored }: { runId: number; score: CallScore | null; onScored: () => void }) {
  const [busy, setBusy] = useState(false);
  const grade = async () => {
    setBusy(true);
    const response = await client.post({ url: `/api/v1/oxee/runs/${runId}/score` });
    setBusy(false);
    if (response.error) {
      toast.error(detailFromError(response.error, "This call could not be graded"));
      return;
    }
    toast.success("Call graded");
    onScored();
  };
  const q = score?.quality;
  const t = score?.technical;
  return (
    <section className="space-y-3 rounded-xl border border-border/70 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-semibold">Call review</h3>
        {q?.score != null && (
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            Quality <ScoreBadge score={q.score} status={techStatus(q.score)} />
          </span>
        )}
        {t?.score != null && (
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            Technical <ScoreBadge score={t.score} status={techStatus(t.score)} />
          </span>
        )}
        <Button variant="outline" size="sm" className="ml-auto h-7 gap-1.5 text-xs" disabled={busy} onClick={() => void grade()}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          {score ? "Grade again" : "Grade this call"}
        </Button>
      </div>
      {!score && <p className="text-sm text-muted-foreground">Not graded yet: calls are graded when they end.</p>}
      {q?.error && <p className="text-sm text-muted-foreground">Quality review failed: {q.error}</p>}
      {q && !q.error && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2 text-sm">
            <p>{q.summary}</p>
            <p className="text-xs text-muted-foreground">{q.resolved ? "The caller got what they called for." : "The caller did not get what they called for."}</p>
            {q.issues.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
                {q.issues.map((i) => (
                  <li key={i}>{i}</li>
                ))}
              </ul>
            )}
          </div>
          <div className="space-y-1 text-sm">
            {Object.entries(q.scores).map(([k, v]) => (
              <div key={k} className="flex items-center gap-3">
                <span className="w-28 text-muted-foreground">{SCORE_LABEL[k] ?? k}</span>
                <div className="h-2 flex-1 rounded-full bg-muted">
                  <div className="h-2 rounded-full bg-[var(--cta)]" style={{ width: `${(v / 5) * 100}%` }} />
                </div>
                <span className="w-6 text-right tabular-nums">{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {t && t.posts.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-border/60 pt-3">
          {t.posts.map((p) => (
            <span key={p.key} className="flex items-center gap-1.5 rounded-md border border-border/70 px-2 py-1 text-xs">
              <span className="text-muted-foreground">{p.label}</span>
              {p.p50 != null && <span className="tabular-nums">{postValue(p.unit as "ms" | "rate" | "x", p.p50)}</span>}
              {p.score != null && <ScoreBadge score={p.score} status={techStatus(p.score)} compact />}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
