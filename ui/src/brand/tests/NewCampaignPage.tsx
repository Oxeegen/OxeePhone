"use client";

import { ArrowLeft, FlaskConical, Loader2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { getWorkflowOptionsApiV1OrganizationsReportsWorkflowsGet } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

import { DIMENSION_ORDER, type Range, rangeLabel, speedText, TOOLS_MODE_LABEL, type ToolsMode } from "./model";
import { API, RangeSlider, useTestSettings } from "./ui";

/** Texts of the two ends of a range: min on the left, max on the right. */
function RangeEnds({ min, max }: { min: { value: string; text?: string }; max: { value: string; text?: string } }) {
  if (min.value === max.value) {
    return (
      <p className="text-[11px] leading-snug text-muted-foreground">
        <span className="font-medium text-foreground/80">Only {min.value}</span> · {min.text}
      </p>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3 text-[11px] leading-snug text-muted-foreground">
      <p>
        <span className="font-medium text-foreground/80">Min {min.value}</span> · {min.text}
      </p>
      <p className="text-right">
        <span className="font-medium text-foreground/80">Max {max.value}</span> · {max.text}
      </p>
    </div>
  );
}

export function DimensionSliders({
  dimensions,
  ranges,
  onChange,
  speed,
  onSpeed,
  speedLimits,
}: {
  dimensions: Record<string, { label: string; levels: Record<string, string> }>;
  ranges: Record<string, Range>;
  onChange: (key: string, value: Range) => void;
  speed: Range;
  onSpeed: (value: Range) => void;
  speedLimits: Range;
}) {
  return (
    <div className="grid gap-x-8 gap-y-5 md:grid-cols-2">
      {DIMENSION_ORDER.filter((k) => dimensions[k]).map((key) => {
        const d = dimensions[key];
        const [lo, hi] = ranges[key] ?? [1, 1];
        return (
          <div key={key} className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium">{d.label}</span>
              <span className="font-mono text-xs text-muted-foreground">{rangeLabel([lo, hi])}</span>
            </div>
            <RangeSlider label={d.label} min={1} max={5} value={[lo, hi]} onChange={(v) => onChange(key, v)} />
            <RangeEnds
              min={{ value: String(lo), text: d.levels[String(lo)] }}
              max={{ value: String(hi), text: d.levels[String(hi)] }}
            />
          </div>
        );
      })}
      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-sm font-medium">Voice speed</span>
          <span className="font-mono text-xs text-muted-foreground">
            ×{speed[0].toFixed(2)}
            {speed[1] !== speed[0] ? ` – ×${speed[1].toFixed(2)}` : ""}
          </span>
        </div>
        <RangeSlider label="Voice speed" min={speedLimits[0]} max={speedLimits[1]} step={0.05} value={speed} onChange={onSpeed} format={(v) => `×${v.toFixed(2)}`} />
        <RangeEnds
          min={{ value: `×${speed[0].toFixed(2)}`, text: speedText(speed[0]) }}
          max={{ value: `×${speed[1].toFixed(2)}`, text: speedText(speed[1]) }}
        />
        <p className="text-[11px] text-muted-foreground">Speech rate of the caller&apos;s voice (1 = normal). Phone executions only.</p>
      </div>
    </div>
  );
}

export function NewCampaignPage() {
  const auth = useAuth();
  const router = useRouter();
  const settings = useTestSettings();
  const [workflows, setWorkflows] = useState<Array<{ id: number; name: string }>>([]);
  const [workflowId, setWorkflowId] = useState<string>("");
  const [name, setName] = useState("");
  const [count, setCount] = useState(30);
  const [language, setLanguage] = useState("French");
  const [toolsMode, setToolsMode] = useState<ToolsMode>("simulated");
  const [maxDuration, setMaxDuration] = useState(300);
  const [instructions, setInstructions] = useState("");
  const [ranges, setRanges] = useState<Record<string, Range>>({});
  const [speed, setSpeed] = useState<Range>([0.95, 1.15]);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    void getWorkflowOptionsApiV1OrganizationsReportsWorkflowsGet().then((r) =>
      setWorkflows((r.data as Array<{ id: number; name: string }>) ?? []),
    );
  }, [auth.loading, auth.isAuthenticated]);

  useEffect(() => {
    if (!settings.data) return;
    setRanges((r) => (Object.keys(r).length ? r : settings.data!.default_ranges));
    setSpeed(settings.data.default_speed);
  }, [settings.data]);

  const testerId = settings.data?.settings.tester_workflow_id;
  const agents = workflows.filter((w) => w.id !== testerId);
  const voices = settings.data?.settings.voices.length ?? 0;
  const numbers = settings.data?.settings.caller_numbers.length ?? 0;

  const create = async () => {
    if (!workflowId) return;
    setCreating(true);
    const response = await client.post<{ 200: { id: string } }, unknown>({
      url: `${API}/campaigns`,
      body: {
        name,
        workflow_id: Number(workflowId),
        ranges,
        speed,
        count,
        language,
        tools_mode: toolsMode,
        max_duration_seconds: maxDuration,
        instructions: instructions.trim() || null,
      },
      headers: { "Content-Type": "application/json" },
    });
    setCreating(false);
    if (response.error) {
      toast.error(detailFromError(response.error, "The campaign could not be created"));
      return;
    }
    router.push(`/test-campaigns/${(response.data as { id: string }).id}`);
  };

  return (
    <div className="container mx-auto w-full max-w-5xl space-y-6 p-6 [contain:inline-size]">
      <Link href="/test-campaigns" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Test campaigns
      </Link>
      <h1 className="flex items-center gap-2 text-3xl font-bold">
        <FlaskConical className="h-7 w-7 text-[var(--cta)]" /> New test campaign
      </h1>

      <Card className="grid gap-4 p-5 md:grid-cols-2">
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Agent to test</span>
          <Select value={workflowId} onValueChange={(v) => {
            setWorkflowId(v);
            if (!name) setName(`Tests — ${agents.find((a) => String(a.id) === v)?.name ?? ""}`);
          }}>
            <SelectTrigger><SelectValue placeholder="Choose an agent" /></SelectTrigger>
            <SelectContent>
              {agents.map((w) => (
                <SelectItem key={w.id} value={String(w.id)}>{w.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Name</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Tests — my agent" />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Scenarios to write (one caller each)</span>
          <Input type="number" min={1} max={100} value={count} onChange={(e) => setCount(Math.max(1, Math.min(100, Number(e.target.value) || 1)))} />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Language of the calls</span>
          <Select value={language} onValueChange={setLanguage}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="French">Français</SelectItem>
              <SelectItem value="English">English</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Agent&apos;s tools during the tests</span>
          <Select value={toolsMode} onValueChange={(v) => setToolsMode(v as ToolsMode)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {(Object.keys(TOOLS_MODE_LABEL) as ToolsMode[]).map((m) => (
                <SelectItem key={m} value={m}>{TOOLS_MODE_LABEL[m]}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="block text-[11px] text-muted-foreground">
            {toolsMode === "simulated"
              ? "A model answers in place of each tool, following the scenario. Post-call webhooks and integrations stay off."
              : toolsMode === "real"
                ? "Tools, webhooks and integrations run for real: they may book, send or write in your systems."
                : "HTTP tools run for real with an X-Oxee-Test: 1 header your backend can route to a sandbox. MCP tools, webhooks and integrations run for real."}
          </span>
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">Maximum call duration (seconds)</span>
          <Input type="number" min={60} max={900} step={30} value={maxDuration} onChange={(e) => setMaxDuration(Math.max(60, Math.min(900, Number(e.target.value) || 300)))} />
        </label>
      </Card>

      <Card className="space-y-4 p-5">
        <div>
          <h2 className="text-lg font-semibold">Callers</h2>
          <p className="text-sm text-muted-foreground">
            Each setting is a range (1 easy → 5 hard): the scenarios are spread over every value of each range. A range
            reduced to one value tests that value only.
          </p>
        </div>
        {settings.data ? (
          <DimensionSliders
            dimensions={settings.data.dimensions}
            ranges={ranges}
            onChange={(key, value) => setRanges((r) => ({ ...r, [key]: value }))}
            speed={speed}
            onSpeed={setSpeed}
            speedLimits={settings.data.speed_limits}
          />
        ) : (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        )}
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">Instructions for the scenario writer (optional)</span>
          <Textarea
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            rows={3}
            placeholder="e.g. focus on cancellations; half of the callers are existing patients; include callers who do not know their file number"
          />
        </label>
        <p className="text-xs text-muted-foreground">
          {voices === 0 && numbers === 0
            ? "Pools empty (Test settings): every caller uses the agent's default voice and no caller number. Fine for text executions."
            : `Pools: ${voices} voice${voices === 1 ? "" : "s"}, ${numbers} caller number${numbers === 1 ? "" : "s"}${voices < count || numbers < count ? " — fewer than the scenarios: some will be reused." : "."}`}
        </p>
      </Card>

      <div className="flex justify-end gap-2">
        <Button variant="outline" asChild>
          <Link href="/test-campaigns">Cancel</Link>
        </Button>
        <Button onClick={() => void create()} disabled={!workflowId || creating} className="gap-2 bg-[var(--cta)] text-[var(--cta-foreground)] hover:opacity-90">
          {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Write the scenarios
        </Button>
      </div>
    </div>
  );
}
