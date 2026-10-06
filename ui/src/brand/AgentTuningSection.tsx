"use client";

import { Info, Loader2, Play, RotateCcw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { detailFromError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

// Agent settings > Voice and Performance (api/brand/agent_tuning.py). Stored
// in the workflow configuration, hence versioned with the agent. Every value
// is optional: unset keeps the organization's voice / today's pipeline
// behaviour.

export interface VoiceOverride {
  voice?: string | null;
  speed?: number | null;
  language?: string | null;
  volume_gain_db?: number | null;
}

export interface AudioSettings {
  webrtc_sample_rate?: 8000 | 16000 | null;
  recording_buffer_seconds?: number | null;
  output_packet_ms?: number | null;
  end_silence_secs?: number | null;
}

export interface Performance {
  tts_first_chunk_ms?: number | null;
  tts_first_clause?: boolean | null;
  vad_stop_secs?: number | null;
  vad_confidence?: number | null;
  vad_min_volume?: number | null;
  llm_temperature?: number | null;
  llm_max_tokens?: number | null;
  mute_during_tools?: boolean | null;
  mute_until_first_reply?: boolean | null;
}

const clean = <T extends object>(value: T): T | undefined => {
  const out = Object.fromEntries(Object.entries(value).filter(([, v]) => v !== null && v !== undefined && v !== ""));
  return Object.keys(out).length ? (out as T) : undefined;
};

export function voiceOverrideFrom(configs: object): VoiceOverride {
  return { ...((configs as { voice_override?: VoiceOverride }).voice_override ?? {}) };
}

export function performanceFrom(configs: object): Performance {
  return { ...((configs as { performance?: Performance }).performance ?? {}) };
}

export function audioFrom(configs: object): AudioSettings {
  return { ...((configs as { audio?: AudioSettings }).audio ?? {}) };
}

/** Keys to save (absent when nothing is set: the platform values apply). */
export function agentTuningConfig(voice: VoiceOverride, performance: Performance, audio: AudioSettings = {}) {
  return { voice_override: clean(voice), performance: clean(performance), audio: clean(audio) };
}

export const hasValues = (value: object) => Boolean(clean(value));

function TuningSlider({
  id,
  label,
  help,
  value,
  fallback,
  fallbackLabel,
  onChange,
  min,
  max,
  step,
  unit,
  source = "default",
}: {
  id: string;
  label: string;
  help: string;
  value: number | null | undefined;
  /** What applies when unset. */
  fallback: number;
  fallbackLabel?: string;
  source?: string;
  onChange: (value: number | null) => void;
  min: number;
  max: number;
  step: number;
  unit?: string;
}) {
  const set = value !== null && value !== undefined;
  const shown = set ? value : fallback;
  const clamp = (v: number) => Math.min(max, Math.max(min, v));
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <Label htmlFor={id} className="text-xs">{label}</Label>
        <span title={help}><Info className="h-3.5 w-3.5 text-muted-foreground" /></span>
        {set ? (
          <button type="button" onClick={() => onChange(null)} className="ml-auto inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
            <RotateCcw className="h-3 w-3" /> {source} ({fallbackLabel ?? `${fallback}${unit ? ` ${unit}` : ""}`})
          </button>
        ) : (
          <span className="ml-auto rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{source}</span>
        )}
      </div>
      <p className="text-xs text-muted-foreground">{help}</p>
      <div className={cn("flex items-center gap-3", !set && "opacity-60")}>
        <span className="w-8 text-right text-xs tabular-nums text-muted-foreground">{min}</span>
        <input
          type="range"
          aria-label={label}
          min={min}
          max={max}
          step={step}
          value={clamp(shown)}
          onChange={(e) => onChange(Number(e.target.value))}
          className="h-1.5 w-full cursor-pointer accent-[var(--cta)]"
        />
        <span className="w-8 text-xs tabular-nums text-muted-foreground">{max}</span>
        <div className="flex shrink-0 items-center gap-1">
          <input
            id={id}
            type="number"
            min={min}
            max={max}
            step={step}
            value={shown}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (e.target.value !== "" && Number.isFinite(v)) onChange(clamp(v));
            }}
            className="h-8 w-20 rounded-md border border-border bg-transparent px-2 text-right text-xs tabular-nums"
          />
          <span className="w-8 text-xs text-muted-foreground">{unit}</span>
        </div>
      </div>
    </div>
  );
}

function TuningSwitch({
  id,
  label,
  help,
  value,
  fallback,
  onChange,
  source = "default",
}: {
  id: string;
  label: string;
  help: string;
  value: boolean | null | undefined;
  fallback: boolean;
  onChange: (value: boolean | null) => void;
  source?: string;
}) {
  const set = value !== null && value !== undefined;
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="space-y-0.5">
        <Label htmlFor={id} className="text-xs">{label}</Label>
        <p className="text-xs text-muted-foreground">{help}</p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {set ? (
          <button type="button" onClick={() => onChange(null)} className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
            <RotateCcw className="h-3 w-3" /> {source}
          </button>
        ) : (
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{source}</span>
        )}
        <Switch id={id} checked={set ? value : fallback} onCheckedChange={(v) => onChange(v)} />
      </div>
    </div>
  );
}

function Listen({ voice, speed }: { voice: string; speed: number | null | undefined }) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const audio = useRef<HTMLAudioElement | null>(null);
  const stop = () => {
    audio.current?.pause();
    audio.current = null;
    setState("idle");
  };
  useEffect(() => stop, []);
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="gap-1.5"
      disabled={!voice.trim() || state === "loading"}
      onClick={async () => {
        if (state === "playing") return stop();
        setState("loading");
        const response = await client.post<{ 200: Blob }, unknown>({
          url: "/api/v1/oxee/voice/preview",
          body: { voice, speed: speed ?? null },
          headers: { "Content-Type": "application/json" },
          parseAs: "blob",
        });
        if (response.error || !response.data) {
          setState("idle");
          toast.error(detailFromError(response.error, "This voice could not be played"));
          return;
        }
        const url = URL.createObjectURL(response.data as Blob);
        const el = new Audio(url);
        audio.current = el;
        el.onended = () => {
          URL.revokeObjectURL(url);
          setState("idle");
        };
        setState("playing");
        void el.play();
      }}
    >
      {state === "loading" ? <Loader2 className="h-4 w-4 animate-spin" /> : state === "playing" ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}
      Listen
    </Button>
  );
}

export function AgentVoiceSection({ value, onChange, header = true }: { value: VoiceOverride; onChange: (value: VoiceOverride) => void; header?: boolean }) {
  const set = (patch: Partial<VoiceOverride>) => onChange({ ...value, ...patch });
  const custom = Boolean(clean(value));
  return (
    <div className="space-y-5">
      <div className={cn("flex items-start gap-2", !header && "hidden")}>
        <div>
          <h3 className="text-sm font-medium">Voice</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            This agent&apos;s voice, on top of the organization&apos;s voice model (Models › Voice): the endpoint, key and
            model stay the organization&apos;s. Empty fields keep the organization&apos;s values.
          </p>
        </div>
        {custom && (
          <Button type="button" variant="ghost" size="sm" className="ml-auto h-7 gap-1.5 text-xs" onClick={() => onChange({})}>
            <RotateCcw className="h-3 w-3" /> Organization voice
          </Button>
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto]">
        <div className="space-y-1.5">
          <Label htmlFor="agent_voice" className="text-xs">Voice id</Label>
          <Input
            id="agent_voice"
            value={value.voice ?? ""}
            onChange={(e) => set({ voice: e.target.value.trim() ? e.target.value : null })}
            placeholder="Organization voice"
            className="font-mono text-xs"
          />
        </div>
        <div className="flex items-end">
          <Listen voice={value.voice ?? ""} speed={value.speed} />
        </div>
      </div>
      <TuningSlider
        id="agent_voice_speed"
        label="Speed"
        help="Speech rate of the agent (1 = normal)."
        value={value.speed}
        fallback={1}
        fallbackLabel="organization"
        onChange={(speed) => set({ speed })}
        min={0.5}
        max={2}
        step={0.05}
        unit="×"
      />
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="agent_voice_language" className="text-xs">Language</Label>
          <Input
            id="agent_voice_language"
            value={value.language ?? ""}
            onChange={(e) => set({ language: e.target.value.trim() ? e.target.value.trim() : null })}
            placeholder="Organization language (e.g. fr)"
          />
        </div>
        <TuningSlider
          id="agent_voice_gain"
          label="Volume"
          help="Gain applied to the agent's voice."
          value={value.volume_gain_db}
          fallback={0}
          fallbackLabel="organization"
          onChange={(volume_gain_db) => set({ volume_gain_db })}
          min={-12}
          max={12}
          step={1}
          unit="dB"
        />
      </div>
    </div>
  );
}

export function PerformanceSection({
  value,
  onChange,
  fallback,
  source = "built-in",
  header = true,
}: {
  value: Performance;
  onChange: (value: Performance) => void;
  /** Values applying to the unset fields (platform or built-in). */
  fallback: Performance;
  source?: string;
  header?: boolean;
}) {
  const set = (patch: Partial<Performance>) => onChange({ ...value, ...patch });
  const custom = Boolean(clean(value));
  const num = (v: number | null | undefined, d: number) => (v === null || v === undefined ? d : v);
  return (
    <div className="space-y-5">
      {header && (
        <div className="flex items-start gap-2">
          <div>
            <h3 className="text-sm font-medium">Performance</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Low-level settings of the call pipeline. Change one at a time in a draft, then replay a test campaign and
              compare the technical score.
            </p>
          </div>
          {custom && (
            <Button type="button" variant="ghost" size="sm" className="ml-auto h-7 gap-1.5 text-xs" onClick={() => onChange({})}>
              <RotateCcw className="h-3 w-3" /> All {source}
            </Button>
          )}
        </div>
      )}

      <p className="text-xs font-medium text-muted-foreground">Voice output</p>
      <TuningSlider
        id="perf_first_chunk"
        label="First audio chunk"
        help="Audio received from the voice model before the agent starts playing it. Smaller starts sooner; too small may stutter on a slow voice server."
        value={value.tts_first_chunk_ms}
        fallback={num(fallback.tts_first_chunk_ms, 250)}
        source={source}
        onChange={(tts_first_chunk_ms) => set({ tts_first_chunk_ms })}
        min={20}
        max={500}
        step={10}
        unit="ms"
      />
      <TuningSwitch
        id="perf_first_clause"
        label="Speak the first clause without waiting for the sentence"
        help="On: the start of each reply is sent to the voice at its first comma (after a few words) instead of at the end of the first sentence, so the agent starts speaking sooner. The intonation of that first piece may sound slightly cut."
        value={value.tts_first_clause}
        fallback={fallback.tts_first_clause ?? false}
        source={source}
        onChange={(tts_first_clause) => set({ tts_first_clause })}
      />

      <p className="text-xs font-medium text-muted-foreground">Voice detection (caller)</p>
      <TuningSlider
        id="perf_vad_stop"
        label="End-of-speech silence"
        help="Silence before the voice detector says the caller stopped speaking. Adds to every reply; too short cuts callers who hesitate."
        value={value.vad_stop_secs}
        fallback={num(fallback.vad_stop_secs, 0.2)}
        source={source}
        onChange={(vad_stop_secs) => set({ vad_stop_secs })}
        min={0.1}
        max={1}
        step={0.05}
        unit="s"
      />
      <TuningSlider
        id="perf_vad_confidence"
        label="Speech confidence"
        help="How sure the detector must be that it hears a voice. Higher ignores more noise (fewer false interruptions) but may miss quiet callers."
        value={value.vad_confidence}
        fallback={num(fallback.vad_confidence, 0.7)}
        source={source}
        onChange={(vad_confidence) => set({ vad_confidence })}
        min={0.3}
        max={0.95}
        step={0.05}
      />
      <TuningSlider
        id="perf_vad_volume"
        label="Minimum volume"
        help="Quieter sounds are not treated as speech. Raise it on noisy lines."
        value={value.vad_min_volume}
        fallback={num(fallback.vad_min_volume, 0.6)}
        source={source}
        onChange={(vad_min_volume) => set({ vad_min_volume })}
        min={0.05}
        max={0.9}
        step={0.05}
      />

      <p className="text-xs font-medium text-muted-foreground">Language model</p>
      <TuningSlider
        id="perf_temperature"
        label="Temperature"
        help="Lower answers more consistently, higher more varied. Default: the model server's own setting."
        value={value.llm_temperature}
        fallback={num(fallback.llm_temperature, 0.7)}
        fallbackLabel={fallback.llm_temperature == null ? "server" : undefined}
        source={source}
        onChange={(llm_temperature) => set({ llm_temperature })}
        min={0}
        max={1.5}
        step={0.05}
      />
      <TuningSlider
        id="perf_max_tokens"
        label="Maximum reply length"
        help="Caps a reply in tokens (about ¾ of a word each). Bounds rambling answers; too low cuts sentences. Default: no limit."
        value={value.llm_max_tokens}
        fallback={num(fallback.llm_max_tokens, 4000)}
        fallbackLabel={fallback.llm_max_tokens == null ? "no limit" : undefined}
        source={source}
        onChange={(llm_max_tokens) => set({ llm_max_tokens })}
        min={16}
        max={4000}
        step={16}
        unit="tokens"
      />

      <p className="text-xs font-medium text-muted-foreground">Listening</p>
      <TuningSwitch
        id="perf_mute_tools"
        label="Ignore the caller while a tool runs"
        help="On: what the caller says during a tool call is not heard. Off: the caller can speak (and interrupt) meanwhile."
        value={value.mute_during_tools}
        fallback={fallback.mute_during_tools ?? true}
        source={source}
        onChange={(mute_during_tools) => set({ mute_during_tools })}
      />
      <TuningSwitch
        id="perf_mute_first"
        label="Ignore the caller until the first reply ends"
        help="On: the caller cannot interrupt the greeting / first reply. Off: they can speak over it."
        value={value.mute_until_first_reply}
        fallback={fallback.mute_until_first_reply ?? true}
        source={source}
        onChange={(mute_until_first_reply) => set({ mute_until_first_reply })}
      />
    </div>
  );
}

const AUDIO_HELP = {
  webrtc_sample_rate:
    "Sample rate of browser calls (web widget, Test Audio). 16 kHz carries more of the voice for the transcriber; 8 kHz matches phone quality. Phone calls always use the operator's rate (8 kHz, 16 kHz for Vonage).",
  recording_buffer_seconds: "How often the call recording is assembled. No effect on the conversation.",
  output_packet_ms:
    "Size of the audio packets sent to the caller. Smaller packets reach the caller sooner and stop faster when the caller interrupts, at the cost of more packets.",
  end_silence_secs: "Silence sent after the agent's last words before the call is closed.",
};

export function AudioSection({
  value,
  onChange,
  fallback,
  source = "built-in",
}: {
  value: AudioSettings;
  onChange: (value: AudioSettings) => void;
  fallback: AudioSettings;
  source?: string;
}) {
  const set = (patch: Partial<AudioSettings>) => onChange({ ...value, ...patch });
  const rate = value.webrtc_sample_rate ?? fallback.webrtc_sample_rate ?? 16000;
  const rateSet = value.webrtc_sample_rate != null;
  return (
    <div className="space-y-5">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <Label className="text-xs">Browser call sample rate</Label>
          {rateSet ? (
            <button type="button" onClick={() => set({ webrtc_sample_rate: null })} className="ml-auto inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
              <RotateCcw className="h-3 w-3" /> {source} ({(fallback.webrtc_sample_rate ?? 16000) / 1000} kHz)
            </button>
          ) : (
            <span className="ml-auto rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{source}</span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{AUDIO_HELP.webrtc_sample_rate}</p>
        <div className={cn("flex gap-2", !rateSet && "opacity-60")}>
          {([8000, 16000] as const).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => set({ webrtc_sample_rate: r })}
              className={cn("rounded-md border px-3 py-1.5 text-xs", rate === r ? "border-[var(--cta)] bg-[var(--cta)]/10 font-medium" : "border-border")}
            >
              {r / 1000} kHz
            </button>
          ))}
        </div>
      </div>
      <TuningSlider
        id="audio_packet"
        label="Output audio packets"
        help={AUDIO_HELP.output_packet_ms}
        value={value.output_packet_ms}
        fallback={fallback.output_packet_ms ?? 40}
        source={source}
        onChange={(output_packet_ms) => set({ output_packet_ms })}
        min={10}
        max={100}
        step={10}
        unit="ms"
      />
      <TuningSlider
        id="audio_end_silence"
        label="Silence before hanging up"
        help={AUDIO_HELP.end_silence_secs}
        value={value.end_silence_secs}
        fallback={fallback.end_silence_secs ?? 2}
        source={source}
        onChange={(end_silence_secs) => set({ end_silence_secs })}
        min={0}
        max={3}
        step={0.1}
        unit="s"
      />
      <TuningSlider
        id="audio_buffer"
        label="Recording assembly interval"
        help={AUDIO_HELP.recording_buffer_seconds}
        value={value.recording_buffer_seconds}
        fallback={fallback.recording_buffer_seconds ?? 5}
        source={source}
        onChange={(recording_buffer_seconds) => set({ recording_buffer_seconds })}
        min={1}
        max={30}
        step={1}
        unit="s"
      />
    </div>
  );
}

/** A settings block the agent takes from the platform unless overridden. */
export function OverrideBlock({
  title,
  description,
  overridden,
  onOverride,
  onUsePlatform,
  platformSummary,
  children,
}: {
  title: string;
  description: string;
  overridden: boolean;
  onOverride: () => void;
  onUsePlatform: () => void;
  platformSummary?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="flex items-center gap-2 text-sm font-medium">
            {title}
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px] font-normal",
                overridden ? "bg-[var(--cta)]/15 text-foreground" : "bg-muted text-muted-foreground",
              )}
            >
              {overridden ? "overridden for this agent" : "platform settings"}
            </span>
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          {!overridden && platformSummary && <div className="mt-1.5 text-xs text-muted-foreground">{platformSummary}</div>}
        </div>
        {overridden ? (
          <Button type="button" variant="ghost" size="sm" className="h-7 gap-1.5 text-xs" onClick={onUsePlatform}>
            <RotateCcw className="h-3 w-3" /> Use platform settings
          </Button>
        ) : (
          <Button type="button" variant="outline" size="sm" className="h-7 text-xs" onClick={onOverride}>
            Override
          </Button>
        )}
      </div>
      {overridden && children}
    </div>
  );
}

export interface EngineSettings {
  builtin: { speaking_plan: Record<string, unknown>; performance: Performance; audio: AudioSettings };
  platform: { speaking_plan: Record<string, unknown> | null; performance: Performance | null; audio: AudioSettings | null };
  effective: { speaking_plan: Record<string, unknown>; performance: Performance; audio: AudioSettings };
}

export async function loadEngineSettings(): Promise<EngineSettings | null> {
  const response = await client.get<{ 200: EngineSettings }, unknown>({ url: "/api/v1/oxee/engine-settings" });
  return (response.data as EngineSettings) ?? null;
}
