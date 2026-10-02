"use client";

import { Loader2, RotateCcw, Save } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

import {
  AudioSection,
  type AudioSettings,
  type EngineSettings,
  hasValues,
  loadEngineSettings,
  type Performance,
  PerformanceSection,
} from "./AgentTuningSection";
import { DEFAULT_SPEAKING_PLAN, type SpeakingPlan, SpeakingPlanSection } from "./SpeakingPlanSection";

// Platform Settings › Call engine: the values every agent uses unless it
// overrides them (agent settings). "Restore built-in values" goes back to
// what was hardcoded in the pipeline (api/brand/agent_tuning.py BUILTIN).

type Block = "speaking_plan" | "performance" | "audio";

const clean = (v: object) => Object.fromEntries(Object.entries(v).filter(([, x]) => x !== null && x !== undefined));

function BlockCard({
  id,
  title,
  description,
  custom,
  busy,
  dirty,
  onSave,
  onReset,
  children,
}: {
  id: string;
  title: string;
  description: ReactNode;
  custom: boolean;
  busy: boolean;
  dirty: boolean;
  onSave: () => void;
  onReset: () => void;
  children: ReactNode;
}) {
  return (
    <Card id={id}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {title}
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">
            {custom ? "custom values" : "built-in values"}
          </span>
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {children}
        <div className="flex flex-wrap gap-2 border-t border-border pt-4">
          <Button size="sm" className="gap-1.5" disabled={busy || !dirty} onClick={onSave}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
          </Button>
          <Button size="sm" variant="outline" className="gap-1.5" disabled={busy || !custom} onClick={onReset}>
            <RotateCcw className="h-4 w-4" /> Restore built-in values
          </Button>
          {dirty && <span className="self-center text-xs text-muted-foreground">Unsaved changes</span>}
        </div>
      </CardContent>
    </Card>
  );
}

function planOf(raw: Record<string, unknown> | undefined): SpeakingPlan {
  const p = (raw ?? {}) as Partial<SpeakingPlan>;
  return { start: { ...DEFAULT_SPEAKING_PLAN.start, ...p.start }, stop: { ...DEFAULT_SPEAKING_PLAN.stop, ...p.stop } };
}

export function EngineSettingsCard() {
  const auth = useAuth();
  const [engine, setEngine] = useState<EngineSettings | null>(null);
  const [plan, setPlan] = useState<SpeakingPlan>(DEFAULT_SPEAKING_PLAN);
  const [smartTurn, setSmartTurn] = useState(2);
  const [perf, setPerf] = useState<Performance>({});
  const [audio, setAudio] = useState<AudioSettings>({});
  const [busy, setBusy] = useState<Block | null>(null);

  const apply = (data: EngineSettings) => {
    setEngine(data);
    setPlan(planOf(data.effective.speaking_plan));
    setSmartTurn(Number(data.effective.speaking_plan.smart_turn_stop_secs ?? 2));
    setPerf(data.platform.performance ?? {});
    setAudio(data.platform.audio ?? {});
  };

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    void loadEngineSettings().then((d) => d && apply(d));
  }, [auth.loading, auth.isAuthenticated]);

  const put = async (block: Block, value: object | null, message: string) => {
    setBusy(block);
    const response = await client.put<{ 200: EngineSettings }, unknown>({
      url: "/api/v1/oxee/engine-settings",
      body: { [block]: value },
      headers: { "Content-Type": "application/json" },
    });
    setBusy(null);
    if (response.error) {
      toast.error(detailFromError(response.error, "The settings could not be saved"));
      return;
    }
    apply(response.data as EngineSettings);
    toast.success(message);
  };

  if (!engine) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading the call engine settings…
        </CardContent>
      </Card>
    );
  }

  const savedPlan = JSON.stringify({ ...planOf(engine.effective.speaking_plan), smart: Number(engine.effective.speaking_plan.smart_turn_stop_secs ?? 2) });
  const planDirty = JSON.stringify({ ...plan, smart: smartTurn }) !== savedPlan;
  const perfDirty = JSON.stringify(clean(perf)) !== JSON.stringify(clean(engine.platform.performance ?? {}));
  const audioDirty = JSON.stringify(clean(audio)) !== JSON.stringify(clean(engine.platform.audio ?? {}));

  return (
    <div className="space-y-6" id="call-engine">
      <div>
        <h2 className="text-xl font-semibold">Call engine</h2>
        <p className="text-sm text-muted-foreground">
          Values used by every agent, unless an agent overrides a block in its own settings. These platform values are not
          versioned with the agents: a test execution records the ones in force, and a comparison shows when they changed.
          The voice of all agents is set in{" "}
          <Link href="/model-configurations" className="underline underline-offset-2">Models › Voice</Link>.
        </p>
      </div>

      <BlockCard
        id="call-engine-speaking-plan"
        title="Speaking plan"
        description="When the agents take the floor and when they yield it to the caller."
        custom={Boolean(engine.platform.speaking_plan)}
        busy={busy === "speaking_plan"}
        dirty={planDirty}
        onSave={() => void put("speaking_plan", { ...plan, smart_turn_stop_secs: smartTurn }, "Speaking plan saved")}
        onReset={() => void put("speaking_plan", null, "Built-in speaking plan restored")}
      >
        <SpeakingPlanSection value={plan} onChange={setPlan} smartTurnStopSecs={smartTurn} onSmartTurnStopSecsChange={setSmartTurn} />
      </BlockCard>

      <BlockCard
        id="call-engine-performance"
        title="Performance"
        description="Voice output, voice detection, language model and listening settings of the call pipeline."
        custom={hasValues(engine.platform.performance ?? {})}
        busy={busy === "performance"}
        dirty={perfDirty}
        onSave={() => void put("performance", hasValues(perf) ? clean(perf) : null, "Performance settings saved")}
        onReset={() => void put("performance", null, "Built-in performance settings restored")}
      >
        <PerformanceSection value={perf} onChange={setPerf} fallback={engine.builtin.performance} source="built-in" header={false} />
      </BlockCard>

      <BlockCard
        id="call-engine-audio"
        title="Audio & sampling"
        description="Sample rate of browser calls, audio packets, end-of-call silence, recording assembly. Phone calls keep the operator's rate."
        custom={hasValues(engine.platform.audio ?? {})}
        busy={busy === "audio"}
        dirty={audioDirty}
        onSave={() => void put("audio", hasValues(audio) ? clean(audio) : null, "Audio settings saved")}
        onReset={() => void put("audio", null, "Built-in audio settings restored")}
      >
        <AudioSection value={audio} onChange={setAudio} fallback={engine.builtin.audio} source="built-in" />
      </BlockCard>
    </div>
  );
}
