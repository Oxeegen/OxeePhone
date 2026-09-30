"use client";

import { Bot, ChevronDown, Info, Loader2, RotateCcw, Save, SlidersHorizontal, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

// Detection thresholds of the configuration analysis. Proposed by the
// analysis model by default (from the agents' purpose and the recorded
// calls), editable here; values are clamped server-side.

interface Spec {
  key: string;
  group: string;
  label: string;
  description: string;
  unit: string;
  default: number;
  min: number;
  max: number;
  step: number;
}

interface ThresholdsState {
  spec: Spec[];
  values: Record<string, number>;
  source: "builtin" | "model" | "custom";
  suggestions: Record<string, { value: number; reason: string }>;
  suggested_at: string | null;
  model: string | null;
}

const isRate = (s: Spec) => s.unit === "%";
const toDisplay = (s: Spec, v: number) => (isRate(s) ? Math.round(v * 1000) / 10 : v);
const fromDisplay = (s: Spec, v: number) => (isRate(s) ? v / 100 : v);
const fmt = (s: Spec, v: number) => `${toDisplay(s, v).toLocaleString()} ${s.unit}`;

const SOURCE_LABEL: Record<ThresholdsState["source"], string> = {
  model: "Proposed by the model",
  custom: "Custom",
  builtin: "Built-in",
};

export function ThresholdsPanel({ timezone, language }: { timezone: string; language: string }) {
  const auth = useAuth();
  const [state, setState] = useState<ThresholdsState | null>(null);
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<"suggest" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const autoSuggested = useRef(false);

  const apply = (next: ThresholdsState) => {
    setState(next);
    setDraft(next.values);
  };

  const suggest = useCallback(async () => {
    setBusy("suggest");
    setError(null);
    const response = await client.post<{ 200: ThresholdsState }, unknown>({
      url: "/api/v1/oxee/analysis/thresholds/suggest",
      body: { timezone, language },
      headers: { "Content-Type": "application/json" },
    });
    setBusy(null);
    if (response.error) {
      setError(detailFromError(response.error, "The model could not propose thresholds"));
      return;
    }
    apply(response.data as ThresholdsState);
  }, [timezone, language]);

  // Latest suggest() for the one-time load below (timezone / language may
  // change later without reloading, which would drop unsaved edits).
  const suggestRef = useRef(suggest);
  suggestRef.current = suggest;

  const loadedOnce = useRef(false);
  useEffect(() => {
    // Wait for auth: the API client only sends the token once it is ready.
    if (auth.loading || !auth.isAuthenticated || loadedOnce.current) return;
    loadedOnce.current = true;
    (async () => {
      const response = await client.get<{ 200: ThresholdsState }, unknown>({ url: "/api/v1/oxee/analysis/thresholds" });
      if (!response.data) return;
      const loaded = response.data as ThresholdsState;
      apply(loaded);
      // Defaults are the model's proposal: ask once if it was never asked.
      if (loaded.source === "builtin" && !loaded.suggested_at && !autoSuggested.current) {
        autoSuggested.current = true;
        void suggestRef.current();
      }
    })();
  }, [auth.loading, auth.isAuthenticated]);

  const groups = useMemo(() => {
    const map = new Map<string, Spec[]>();
    for (const s of state?.spec ?? []) map.set(s.group, [...(map.get(s.group) ?? []), s]);
    return Array.from(map.entries());
  }, [state]);

  if (!state) return null;
  const dirty = state.spec.some((s) => draft[s.key] !== state.values[s.key]);
  const hasSuggestions = Object.keys(state.suggestions).length > 0;
  const matchesSuggestions = hasSuggestions && state.spec.every((s) => state.suggestions[s.key]?.value === undefined || draft[s.key] === state.suggestions[s.key].value);

  const save = async () => {
    setBusy("save");
    const response = await client.put<{ 200: ThresholdsState }, unknown>({
      url: "/api/v1/oxee/analysis/thresholds",
      body: { values: draft, source: matchesSuggestions ? "model" : "custom" },
      headers: { "Content-Type": "application/json" },
    });
    setBusy(null);
    if (response.error) {
      toast.error(detailFromError(response.error, "Could not save the thresholds"));
      return;
    }
    apply(response.data as ThresholdsState);
    toast.success("Thresholds saved — used by the next analyses");
  };

  return (
    <Card className="gap-0 p-0">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-3 px-4 py-3 text-left">
        <SlidersHorizontal className="h-4 w-4 text-[var(--cta)]" />
        <span className="font-medium">Detection thresholds</span>
        <span className="inline-flex items-center gap-1 rounded-md border border-border px-1.5 py-0.5 text-[11px]">
          {state.source === "model" && <Bot className="h-3 w-3" />}
          {SOURCE_LABEL[state.source]}
          {state.source === "model" && state.model ? ` · ${state.model}` : ""}
        </span>
        {busy === "suggest" && (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" /> The analysis model is proposing thresholds suited to your agents…
          </span>
        )}
        {dirty && <span className="text-xs text-amber-600 dark:text-amber-400">Unsaved changes</span>}
        <ChevronDown className={cn("ml-auto h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {error && <p className="px-4 pb-3 text-sm text-destructive">{error}</p>}
      {open && (
        <div className="space-y-5 border-t border-border px-4 py-4">
          <p className="text-sm text-muted-foreground">
            What the rules consider a problem. The analysis model proposes values from your agents&apos; purpose and the
            recorded calls; adjust them to your expectations. Changes apply to the next analyses.
          </p>
          {groups.map(([group, specs]) => (
            <div key={group} className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{group}</p>
              <div className="grid gap-3 md:grid-cols-2">
                {specs.map((s) => {
                  const suggestion = state.suggestions[s.key];
                  const changed = draft[s.key] !== state.values[s.key];
                  return (
                    <div key={s.key} className={cn("space-y-1.5 rounded-lg border p-3", changed ? "border-amber-500/50" : "border-border/70")}>
                      <div className="flex items-center gap-2">
                        <label htmlFor={`th-${s.key}`} className="text-sm font-medium">{s.label}</label>
                        <span title={s.description}><Info className="h-3.5 w-3.5 text-muted-foreground" /></span>
                        <div className="ml-auto flex items-center gap-1.5">
                          <Input
                            id={`th-${s.key}`}
                            type="number"
                            className="h-8 w-24 text-right tabular-nums"
                            min={toDisplay(s, s.min)}
                            max={toDisplay(s, s.max)}
                            step={isRate(s) ? 1 : s.step}
                            value={toDisplay(s, draft[s.key] ?? s.default)}
                            onChange={(e) => {
                              const v = Number(e.target.value);
                              if (Number.isFinite(v)) setDraft((d) => ({ ...d, [s.key]: fromDisplay(s, v) }));
                            }}
                          />
                          <span className="w-20 text-xs text-muted-foreground">{s.unit}</span>
                        </div>
                      </div>
                      {suggestion && (
                        <p className="flex items-start gap-1.5 text-xs">
                          <Bot className="mt-0.5 h-3 w-3 shrink-0 text-[var(--cta)]" />
                          <span>
                            <span className="font-medium">{fmt(s, suggestion.value)}</span>
                            {suggestion.reason && <span className="text-muted-foreground"> — {suggestion.reason}</span>}
                          </span>
                        </p>
                      )}
                      <p className="text-[11px] text-muted-foreground">
                        Built-in {fmt(s, s.default)} · range {fmt(s, s.min)} – {fmt(s, s.max)}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
            <Button onClick={() => void save()} disabled={!dirty || busy !== null} className="gap-2">
              {busy === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save thresholds
            </Button>
            <Button variant="outline" onClick={() => void suggest()} disabled={busy !== null} className="gap-2">
              <Sparkles className="h-4 w-4" /> Ask the model again
            </Button>
            {hasSuggestions && (
              <Button
                variant="outline"
                disabled={busy !== null || matchesSuggestions}
                onClick={() => setDraft((d) => ({ ...d, ...Object.fromEntries(Object.entries(state.suggestions).map(([k, v]) => [k, v.value])) }))}
                className="gap-2"
              >
                <Bot className="h-4 w-4" /> Use the model&apos;s proposal
              </Button>
            )}
            <Button
              variant="ghost"
              disabled={busy !== null}
              onClick={() => setDraft(Object.fromEntries(state.spec.map((s) => [s.key, s.default])))}
              className="gap-2"
            >
              <RotateCcw className="h-4 w-4" /> Built-in values
            </Button>
            {state.suggested_at && (
              <span className="ml-auto text-xs text-muted-foreground">
                Model proposal from {new Date(state.suggested_at).toLocaleString()}
              </span>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
