"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Separator } from "@/components/ui/separator";
import { useAuth } from "@/lib/auth";

import {
  agentTuningConfig,
  AgentVoiceSection,
  audioFrom,
  AudioSection,
  type AudioSettings,
  type EngineSettings,
  hasValues,
  loadEngineSettings,
  OverrideBlock,
  type Performance,
  performanceFrom,
  PerformanceSection,
  type VoiceOverride,
  voiceOverrideFrom,
} from "./AgentTuningSection";
import { DEFAULT_SPEAKING_PLAN, type SpeakingPlan, speakingPlanConfig, speakingPlanFrom, SpeakingPlanSection } from "./SpeakingPlanSection";

// Agent settings: the call-engine blocks (speaking plan, voice, performance,
// audio & sampling). Each one follows the platform settings (Platform
// Settings › Call engine; Models › Voice for the voice) unless overridden here;
// overrides are saved in the agent's configuration, hence versioned.

type Configs = Record<string, unknown>;

function planFromPlatform(engine: EngineSettings | null): SpeakingPlan {
  const p = engine?.effective.speaking_plan as Partial<SpeakingPlan> | undefined;
  return p ? { start: { ...DEFAULT_SPEAKING_PLAN.start, ...p.start }, stop: { ...DEFAULT_SPEAKING_PLAN.stop, ...p.stop } } : DEFAULT_SPEAKING_PLAN;
}

function patchOf(state: {
  planOn: boolean;
  plan: SpeakingPlan;
  voiceOn: boolean;
  voice: VoiceOverride;
  perfOn: boolean;
  perf: Performance;
  audioOn: boolean;
  audio: AudioSettings;
}) {
  const tuning = agentTuningConfig(state.voiceOn ? state.voice : {}, state.perfOn ? state.perf : {}, state.audioOn ? state.audio : {});
  return {
    ...(state.planOn ? speakingPlanConfig(state.plan) : { speaking_plan: undefined }),
    ...tuning,
  };
}

function initial(configs: Configs) {
  return {
    planOn: Boolean(configs.speaking_plan),
    plan: speakingPlanFrom(configs),
    voiceOn: hasValues(voiceOverrideFrom(configs)),
    voice: voiceOverrideFrom(configs),
    perfOn: hasValues(performanceFrom(configs)),
    perf: performanceFrom(configs),
    audioOn: hasValues(audioFrom(configs)),
    audio: audioFrom(configs),
  };
}

const s = (v: number | null | undefined, unit: string) => (v === null || v === undefined ? "—" : `${v}${unit}`);

export function useAgentEngineSettings(
  configs: Configs,
  smartTurnStopSecs: number,
  setSmartTurnStopSecs: (v: number) => void,
) {
  const auth = useAuth();
  const [engine, setEngine] = useState<EngineSettings | null>(null);
  const [state, setState] = useState(() => initial(configs));
  const saved = useMemo(() => JSON.stringify(patchOf(initial(configs))), [configs]);

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    void loadEngineSettings().then(setEngine);
  }, [auth.loading, auth.isAuthenticated]);

  const patch = patchOf(state);
  const dirty = JSON.stringify(patch) !== saved;
  const update = (p: Partial<typeof state>) => setState((x) => ({ ...x, ...p }));
  const perfFallback = engine?.effective.performance ?? {};
  const audioFallback = engine?.effective.audio ?? {};
  const platformPlan = planFromPlatform(engine);

  const element = (
    <>
      <OverrideBlock
        title="Speaking plan"
        description="When the agent takes the floor and when it yields it to the caller."
        overridden={state.planOn}
        onOverride={() => update({ planOn: true, plan: platformPlan })}
        onUsePlatform={() => update({ planOn: false })}
        platformSummary={
          <>
            Wait {platformPlan.start.wait_seconds} s · smart endpointing {platformPlan.start.smart_endpointing === "smart_turn" ? "on" : "off"} ·
            after a sentence {platformPlan.start.on_punctuation_seconds} s · interrupt on{" "}
            {platformPlan.stop.num_words ? `${platformPlan.stop.num_words} words` : "voice"}.{" "}
            <Link href="/settings#call-engine" className="underline underline-offset-2">Platform settings</Link>
          </>
        }
      >
        <SpeakingPlanSection
          value={state.plan}
          onChange={(plan) => update({ plan })}
          smartTurnStopSecs={smartTurnStopSecs}
          onSmartTurnStopSecsChange={setSmartTurnStopSecs}
        />
      </OverrideBlock>
      <Separator />
      <OverrideBlock
        title="Voice"
        description="The agent's voice, speed, language and volume, on top of the organization's voice model (endpoint, key and model stay the organization's)."
        overridden={state.voiceOn}
        onOverride={() => update({ voiceOn: true })}
        onUsePlatform={() => update({ voiceOn: false })}
        platformSummary={
          <>
            Organization voice:{" "}
            <Link href="/model-configurations" className="underline underline-offset-2">Models › Voice</Link>.
          </>
        }
      >
        <AgentVoiceSection value={state.voice} onChange={(voice) => update({ voice })} header={false} />
      </OverrideBlock>
      <Separator />
      <OverrideBlock
        title="Performance"
        description="Voice output, voice detection, language model and listening settings of the call pipeline."
        overridden={state.perfOn}
        onOverride={() => update({ perfOn: true })}
        onUsePlatform={() => update({ perfOn: false })}
        platformSummary={
          <>
            First audio chunk {s(perfFallback.tts_first_chunk_ms, " ms")} · end-of-speech silence {s(perfFallback.vad_stop_secs, " s")} ·
            temperature {perfFallback.llm_temperature ?? "server"} · max reply{" "}
            {perfFallback.llm_max_tokens ? `${perfFallback.llm_max_tokens} tokens` : "no limit"}.
          </>
        }
      >
        <PerformanceSection value={state.perf} onChange={(perf) => update({ perf })} fallback={perfFallback} source="platform" header={false} />
      </OverrideBlock>
      <Separator />
      <OverrideBlock
        title="Audio & sampling"
        description="Sample rate of browser calls, audio packets, end-of-call silence, recording assembly."
        overridden={state.audioOn}
        onOverride={() => update({ audioOn: true })}
        onUsePlatform={() => update({ audioOn: false })}
        platformSummary={
          <>
            Browser calls {((audioFallback.webrtc_sample_rate ?? 16000) / 1000).toString()} kHz · packets{" "}
            {s(audioFallback.output_packet_ms, " ms")} · silence before hanging up {s(audioFallback.end_silence_secs, " s")}.
          </>
        }
      >
        <AudioSection value={state.audio} onChange={(audio) => update({ audio })} fallback={audioFallback} source="platform" />
      </OverrideBlock>
    </>
  );

  return { patch, dirty, element };
}
