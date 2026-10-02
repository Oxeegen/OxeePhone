"use client";

import { ChevronDown, Copy, Loader2, Save, Trash2, User } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

import { DIMENSION_ORDER, type DimensionInfo, type Scenario, type Voice } from "./model";
import { API, LevelChips } from "./ui";

const lines = (text: string) => text.split("\n").map((s) => s.trim()).filter(Boolean);
const pairs = (text: string) =>
  Object.fromEntries(
    lines(text)
      .map((l) => {
        const at = l.search(/[:=]/);
        return at > 0 ? [l.slice(0, at).trim(), l.slice(at + 1).trim()] : null;
      })
      .filter((p): p is [string, string] => p !== null),
  );
const unpairs = (o: Record<string, string>) => Object.entries(o ?? {}).map(([k, v]) => `${k}: ${v}`).join("\n");

function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("block space-y-1", className)}>
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

export function ScenarioCard({
  campaignId,
  scenario,
  dimensions,
  voices,
  onChanged,
  index,
}: {
  campaignId: string;
  scenario: Scenario;
  dimensions: Record<string, DimensionInfo>;
  voices: Voice[];
  onChanged: () => void;
  index: number;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Scenario>(scenario);
  const [texts, setTexts] = useState(() => ({
    facts: unpairs(scenario.facts),
    criteria: scenario.criteria.join("\n"),
    forbidden: scenario.forbidden.join("\n"),
    variables: unpairs(scenario.expected_variables),
    tools: scenario.expected_tools.join("\n"),
  }));
  const [busy, setBusy] = useState<string | null>(null);

  const reset = () => {
    setDraft(scenario);
    setTexts({
      facts: unpairs(scenario.facts),
      criteria: scenario.criteria.join("\n"),
      forbidden: scenario.forbidden.join("\n"),
      variables: unpairs(scenario.expected_variables),
      tools: scenario.expected_tools.join("\n"),
    });
  };

  const patch = async (changes: Partial<Scenario>, label = "save") => {
    setBusy(label);
    const response = await client.patch({
      url: `${API}/campaigns/${campaignId}/scenarios/${scenario.id}`,
      body: changes,
      headers: { "Content-Type": "application/json" },
    });
    setBusy(null);
    if (response.error) {
      toast.error(detailFromError(response.error, "The scenario could not be saved"));
      return false;
    }
    onChanged();
    return true;
  };

  const save = async () => {
    const ok = await patch({
      title: draft.title,
      intent: draft.intent,
      persona: draft.persona,
      goal: draft.goal,
      behaviour: draft.behaviour,
      facts: pairs(texts.facts),
      criteria: lines(texts.criteria),
      forbidden: lines(texts.forbidden),
      expected_end_node: draft.expected_end_node?.trim() || null,
      expected_variables: pairs(texts.variables),
      expected_tools: lines(texts.tools),
      tool_hints: draft.tool_hints,
      levels: draft.levels,
      speed: draft.speed,
      voice: draft.voice,
      caller_number: draft.caller_number?.trim() || null,
    });
    if (ok) toast.success("Scenario saved");
  };

  const p = scenario.persona;
  return (
    <div className={cn("rounded-lg border border-border", !scenario.enabled && "opacity-60")}>
      <div className="flex flex-wrap items-center gap-3 p-3">
        <span className="w-7 text-right font-mono text-xs text-muted-foreground">{index}</span>
        <button type="button" onClick={() => setOpen((o) => !o)} className="min-w-0 flex-1 text-left">
          <p className="truncate font-medium">
            {scenario.title}
            {scenario.variant_of && <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">variant</span>}
          </p>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <User className="h-3 w-3" /> {p.name || "?"}
              {p.age ? `, ${p.age}` : ""}
            </span>
            {scenario.intent && <span>· {scenario.intent}</span>}
            {scenario.voice && <span className="font-mono">· {scenario.voice.id}</span>}
            {scenario.caller_number && <span className="font-mono">· {scenario.caller_number}</span>}
          </p>
        </button>
        <LevelChips levels={scenario.levels} speed={scenario.speed} />
        <Switch
          checked={scenario.enabled}
          onCheckedChange={(v) => void patch({ enabled: v }, "enabled")}
          disabled={busy !== null}
          aria-label="Play this scenario"
          title={scenario.enabled ? "Played in executions" : "Skipped in executions"}
        />
        <button type="button" onClick={() => setOpen((o) => !o)} aria-label="Details">
          <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
        </button>
      </div>

      {open && (
        <div className="space-y-4 border-t border-border p-4 text-sm">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Title"><Input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></Field>
            <Field label="Intent"><Input value={draft.intent} onChange={(e) => setDraft({ ...draft, intent: e.target.value })} /></Field>
            <Field label="Goal of the caller" className="md:col-span-2">
              <Textarea rows={2} value={draft.goal} onChange={(e) => setDraft({ ...draft, goal: e.target.value })} />
            </Field>
            <Field label="Behaviour" className="md:col-span-2">
              <Textarea rows={2} value={draft.behaviour} onChange={(e) => setDraft({ ...draft, behaviour: e.target.value })} />
            </Field>
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            <Field label="Name"><Input value={draft.persona.name} onChange={(e) => setDraft({ ...draft, persona: { ...draft.persona, name: e.target.value } })} /></Field>
            <Field label="Age"><Input type="number" value={draft.persona.age ?? ""} onChange={(e) => setDraft({ ...draft, persona: { ...draft.persona, age: e.target.value ? Number(e.target.value) : null } })} /></Field>
            <Field label="Situation" className="md:col-span-2"><Input value={draft.persona.situation} onChange={(e) => setDraft({ ...draft, persona: { ...draft.persona, situation: e.target.value } })} /></Field>
            <Field label="Personality" className="md:col-span-2"><Input value={draft.persona.personality} onChange={(e) => setDraft({ ...draft, persona: { ...draft.persona, personality: e.target.value } })} /></Field>
            <Field label="Voice">
              <Select value={draft.voice?.id ?? "none"} onValueChange={(v) => setDraft({ ...draft, voice: voices.find((x) => x.id === v) ?? null })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Agent default</SelectItem>
                  {voices.map((v) => (
                    <SelectItem key={v.id} value={v.id}>{v.id} · {v.gender}</SelectItem>
                  ))}
                  {draft.voice && !voices.some((v) => v.id === draft.voice!.id) && <SelectItem value={draft.voice.id}>{draft.voice.id}</SelectItem>}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Caller number"><Input value={draft.caller_number ?? ""} onChange={(e) => setDraft({ ...draft, caller_number: e.target.value })} className="font-mono" /></Field>
          </div>

          <div className="grid gap-3 md:grid-cols-5">
            {DIMENSION_ORDER.filter((k) => dimensions[k]).map((k) => (
              <Field key={k} label={dimensions[k].label}>
                <Select value={String(draft.levels[k] ?? 1)} onValueChange={(v) => setDraft({ ...draft, levels: { ...draft.levels, [k]: Number(v) } })}>
                  <SelectTrigger title={dimensions[k].levels[String(draft.levels[k] ?? 1)]}>
                    <SelectValue>{String(draft.levels[k] ?? 1)}</SelectValue>
                  </SelectTrigger>
                  <SelectContent className="max-w-sm">
                    {[1, 2, 3, 4, 5].map((l) => (
                      <SelectItem key={l} value={String(l)}>{l} — {dimensions[k].levels[String(l)]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            ))}
            <Field label="Voice speed">
              <Input type="number" step={0.05} min={0.7} max={1.6} value={draft.speed} onChange={(e) => setDraft({ ...draft, speed: Number(e.target.value) || 1 })} />
            </Field>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Facts the caller can give (one “name: value” per line)">
              <Textarea rows={4} value={texts.facts} onChange={(e) => setTexts({ ...texts, facts: e.target.value })} className="font-mono text-xs" />
            </Field>
            <Field label="Success criteria (one per line)">
              <Textarea rows={4} value={texts.criteria} onChange={(e) => setTexts({ ...texts, criteria: e.target.value })} />
            </Field>
            <Field label="Forbidden (one per line)">
              <Textarea rows={3} value={texts.forbidden} onChange={(e) => setTexts({ ...texts, forbidden: e.target.value })} />
            </Field>
            <Field label="Expected variables (one “name: value” per line)">
              <Textarea rows={3} value={texts.variables} onChange={(e) => setTexts({ ...texts, variables: e.target.value })} className="font-mono text-xs" />
            </Field>
            <Field label="Expected end node">
              <Input value={draft.expected_end_node ?? ""} onChange={(e) => setDraft({ ...draft, expected_end_node: e.target.value })} />
            </Field>
            <Field label="Expected tools (one per line)">
              <Textarea rows={2} value={texts.tools} onChange={(e) => setTexts({ ...texts, tools: e.target.value })} className="font-mono text-xs" />
            </Field>
            <Field label="What simulated tools should answer" className="md:col-span-2">
              <Textarea rows={2} value={draft.tool_hints} onChange={(e) => setDraft({ ...draft, tool_hints: e.target.value })} />
            </Field>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => void save()} disabled={busy !== null} className="gap-1.5">
              {busy === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
            </Button>
            <Button size="sm" variant="ghost" onClick={reset} disabled={busy !== null}>Undo changes</Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              disabled={busy !== null}
              title="Same request, to play with other caller levels: edit the variant afterwards"
              onClick={async () => {
                setBusy("duplicate");
                const response = await client.post({ url: `${API}/campaigns/${campaignId}/scenarios/${scenario.id}/duplicate`, body: {}, headers: { "Content-Type": "application/json" } });
                setBusy(null);
                if (response.error) toast.error(detailFromError(response.error, "Could not duplicate"));
                else onChanged();
              }}
            >
              <Copy className="h-4 w-4" /> Variant
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="ml-auto gap-1.5 text-destructive"
              disabled={busy !== null}
              onClick={async () => {
                if (!window.confirm(`Delete “${scenario.title}”?`)) return;
                setBusy("delete");
                const response = await client.delete({ url: `${API}/campaigns/${campaignId}/scenarios/${scenario.id}` });
                setBusy(null);
                if (response.error) toast.error(detailFromError(response.error, "Could not delete"));
                else onChanged();
              }}
            >
              <Trash2 className="h-4 w-4" /> Delete
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
