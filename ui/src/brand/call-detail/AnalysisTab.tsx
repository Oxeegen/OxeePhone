"use client";

import { type CallRun, extractedVariables, qaResults } from "./model";

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <div>
        <h3 className="text-base font-semibold">{title}</h3>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function Json({ value }: { value: unknown }) {
  return (
    <pre className="overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border/70 bg-muted/30 p-3 font-mono text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

const sentimentStyle = (s: string) =>
  /pos/i.test(s)
    ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
    : /neg/i.test(s)
      ? "bg-destructive/15 text-destructive"
      : "bg-muted text-muted-foreground";

export function AnalysisTab({ run }: { run: CallRun }) {
  const qa = qaResults(run);
  const variables = extractedVariables(run);
  const gathered = run.gathered_context ?? {};
  const disposition = (gathered.mapped_call_disposition ?? gathered.call_disposition) as string | undefined;
  const tags = [
    ...(Array.isArray(gathered.call_tags) ? (gathered.call_tags as unknown[]) : []),
    ...(Array.isArray(run.annotations?.tags) ? (run.annotations?.tags as unknown[]) : []),
  ].map(String);

  return (
    <div className="space-y-6 py-2">
      <Section title="Outcome">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Disposition:</span>
          <span className="rounded-md bg-muted px-2 py-0.5 font-medium">{disposition || "—"}</span>
          {Array.from(new Set(tags)).map((t) => (
            <span key={t} className="rounded-md border border-border px-2 py-0.5 text-xs">{t}</span>
          ))}
        </div>
      </Section>

      <Section title="Summary" hint="Post-call QA analysis (enable a QA node on the agent to get one).">
        {qa.length === 0 ? (
          <p className="text-sm text-muted-foreground">No analysis for this call.</p>
        ) : (
          <div className="space-y-3">
            {qa.map((r, i) => (
              <div key={i} className="space-y-2 rounded-xl border border-border/70 p-4">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">{r.node}</span>
                  {r.score !== null && <span className="rounded-md bg-muted px-2 py-0.5 tabular-nums">Score {r.score}/10</span>}
                  {r.sentiment && <span className={`rounded-md px-2 py-0.5 text-xs ${sentimentStyle(r.sentiment)}`}>{r.sentiment}</span>}
                  {r.tags.map((t) => (
                    <span key={t} className="rounded-md border border-border px-2 py-0.5 text-xs">{t}</span>
                  ))}
                </div>
                {r.summary && <p className="text-sm leading-relaxed text-muted-foreground">{r.summary}</p>}
                {r.skipped && <p className="text-sm text-muted-foreground">Skipped: {r.skipped}</p>}
                {r.error && <p className="text-sm text-destructive">Error: {r.error}</p>}
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Extracted data" hint="Variables gathered during the conversation.">
        {Object.keys(variables).length ? <Json value={variables} /> : <p className="text-sm text-muted-foreground">No data extracted.</p>}
      </Section>

      <Section title="Initial context" hint="Variables the call started with.">
        {run.initial_context && Object.keys(run.initial_context).length ? (
          <Json value={run.initial_context} />
        ) : (
          <p className="text-sm text-muted-foreground">No initial context.</p>
        )}
      </Section>

      {Array.isArray(gathered.nodes_visited) && (
        <Section title="Path">
          <p className="text-sm text-muted-foreground">{(gathered.nodes_visited as unknown[]).map(String).join(" → ")}</p>
        </Section>
      )}
    </div>
  );
}
