"use client";

import { Info, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

// Agent settings > Speaking plans (Vapi-style). Replaces upstream's "Turn
// Detection" and "Interruption" sections; stored under `speaking_plan` in the
// workflow configuration and applied by api/brand/speaking_plan.py.

export interface SpeakingPlan {
  start: {
    wait_seconds: number;
    smart_endpointing: "off" | "smart_turn";
    on_punctuation_seconds: number;
    on_no_punctuation_seconds: number;
    on_number_seconds: number;
  };
  stop: {
    num_words: number;
    voice_seconds: number;
    backoff_seconds: number;
  };
}

// Must match the API defaults (StartSpeakingPlan / StopSpeakingPlan).
export const DEFAULT_SPEAKING_PLAN: SpeakingPlan = {
  start: {
    wait_seconds: 0.4,
    smart_endpointing: "off",
    on_punctuation_seconds: 0.1,
    on_no_punctuation_seconds: 1.5,
    on_number_seconds: 0.5,
  },
  stop: { num_words: 0, voice_seconds: 0.2, backoff_seconds: 1 },
};

interface UpstreamTurnSettings {
  turn_start_strategy?: string;
  turn_start_min_words?: number;
  turn_stop_strategy?: string;
}

/** The stored plan, or one derived from the upstream turn settings. */
export function speakingPlanFrom(configs: object): SpeakingPlan {
  const c = configs as UpstreamTurnSettings & { speaking_plan?: Partial<SpeakingPlan> };
  const stored = c.speaking_plan;
  if (stored) {
    return {
      start: { ...DEFAULT_SPEAKING_PLAN.start, ...stored.start },
      stop: { ...DEFAULT_SPEAKING_PLAN.stop, ...stored.stop },
    };
  }
  return {
    start: {
      ...DEFAULT_SPEAKING_PLAN.start,
      smart_endpointing: c.turn_stop_strategy === "turn_analyzer" ? "smart_turn" : "off",
    },
    stop: {
      ...DEFAULT_SPEAKING_PLAN.stop,
      num_words: c.turn_start_strategy === "min_words" ? (c.turn_start_min_words ?? 3) : 0,
    },
  };
}

/** Keys to save: the plan, plus the upstream turn settings kept in line with it. */
export function speakingPlanConfig(plan: SpeakingPlan) {
  return {
    speaking_plan: plan,
    turn_stop_strategy: plan.start.smart_endpointing === "smart_turn" ? "turn_analyzer" : "transcription",
    turn_start_strategy: plan.stop.num_words > 0 ? "min_words" : "default",
    turn_start_min_words: Math.max(1, plan.stop.num_words || 3),
  } as const;
}

function PlanSlider({
  id,
  label,
  help,
  value,
  onChange,
  min,
  max,
  step,
  unit = "s",
  disabled,
}: {
  id: string;
  label: string;
  help: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
  unit?: string;
  disabled?: boolean;
}) {
  const clamp = (v: number) => Math.min(max, Math.max(min, v));
  return (
    <div className={cn("space-y-1.5", disabled && "opacity-50")}>
      <div className="flex items-center gap-1.5">
        <Label htmlFor={id} className="text-xs">{label}</Label>
        <span title={help}><Info className="h-3.5 w-3.5 text-muted-foreground" /></span>
      </div>
      <p className="text-xs text-muted-foreground">{help}</p>
      <div className="flex items-center gap-3">
        <span className="w-6 text-right text-xs tabular-nums text-muted-foreground">{min}</span>
        <input
          type="range"
          aria-label={label}
          min={min}
          max={max}
          step={step}
          value={clamp(value)}
          disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          className="h-1.5 w-full cursor-pointer accent-[var(--cta)] disabled:cursor-not-allowed"
        />
        <span className="w-6 text-xs tabular-nums text-muted-foreground">{max}</span>
        <div className="flex shrink-0 items-center gap-1">
          <input
            id={id}
            type="number"
            min={min}
            max={max}
            step={step}
            value={value}
            disabled={disabled}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (e.target.value !== "" && Number.isFinite(v)) onChange(clamp(v));
            }}
            className="h-8 w-16 rounded-md border border-border bg-transparent px-2 text-right text-xs tabular-nums"
          />
          <span className="w-8 text-xs text-muted-foreground">{unit}</span>
        </div>
      </div>
    </div>
  );
}

export function SpeakingPlanSection({
  value,
  onChange,
  smartTurnStopSecs,
  onSmartTurnStopSecsChange,
}: {
  value: SpeakingPlan;
  onChange: (plan: SpeakingPlan) => void;
  smartTurnStopSecs: number;
  onSmartTurnStopSecsChange: (secs: number) => void;
}) {
  const setStart = (patch: Partial<SpeakingPlan["start"]>) => onChange({ ...value, start: { ...value.start, ...patch } });
  const setStop = (patch: Partial<SpeakingPlan["stop"]>) => onChange({ ...value, stop: { ...value.stop, ...patch } });
  const smart = value.start.smart_endpointing === "smart_turn";

  return (
    <>
      <div className="space-y-5">
        <div className="flex items-start gap-2">
          <div>
            <h3 className="text-sm font-medium">Start speaking plan</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              When the agent decides the caller has finished and starts answering.
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="ml-auto h-7 gap-1.5 text-xs"
            onClick={() => onChange({ ...value, start: DEFAULT_SPEAKING_PLAN.start })}
          >
            <RotateCcw className="h-3 w-3" /> Defaults
          </Button>
        </div>
        <PlanSlider
          id="plan_wait_seconds"
          label="Wait seconds"
          help="Minimum time between the end of the caller's turn and the agent's first word. Model latency counts towards it."
          value={value.start.wait_seconds}
          onChange={(wait_seconds) => setStart({ wait_seconds })}
          min={0}
          max={5}
          step={0.1}
        />
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <Label htmlFor="plan_smart_endpointing" className="text-xs">Smart endpointing</Label>
            <span title="Decides when the caller has finished speaking."><Info className="h-3.5 w-3.5 text-muted-foreground" /></span>
          </div>
          <p className="text-xs text-muted-foreground">
            {smart
              ? "The Smart Turn model (runs locally) listens to the caller's intonation to tell a pause from the end of the turn."
              : "Off: the end of the turn is decided from the transcript, with the waits below."}
          </p>
          <Select
            value={value.start.smart_endpointing}
            onValueChange={(v: "off" | "smart_turn") => setStart({ smart_endpointing: v })}
          >
            <SelectTrigger id="plan_smart_endpointing" className="w-64">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="off">Off — transcript based</SelectItem>
              <SelectItem value="smart_turn">Smart Turn (local model)</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {smart ? (
          <PlanSlider
            id="smart_turn_stop_secs"
            label="Incomplete turn timeout"
            help="When the model thinks the caller has not finished, silence after which the turn ends anyway."
            value={smartTurnStopSecs}
            onChange={onSmartTurnStopSecsChange}
            min={0.5}
            max={10}
            step={0.5}
          />
        ) : (
          <div className="space-y-5 rounded-lg border border-border/70 p-4">
            <p className="text-xs font-medium text-muted-foreground">Silence needed after the caller&apos;s last words</p>
            <PlanSlider
              id="plan_on_punctuation_seconds"
              label="On punctuation seconds"
              help="The transcript ends with . ! or ? — the sentence is likely complete."
              value={value.start.on_punctuation_seconds}
              onChange={(on_punctuation_seconds) => setStart({ on_punctuation_seconds })}
              min={0}
              max={3}
              step={0.1}
            />
            <PlanSlider
              id="plan_on_no_punctuation_seconds"
              label="On no punctuation seconds"
              help="The transcript ends without punctuation — the caller may go on."
              value={value.start.on_no_punctuation_seconds}
              onChange={(on_no_punctuation_seconds) => setStart({ on_no_punctuation_seconds })}
              min={0}
              max={3}
              step={0.1}
            />
            <PlanSlider
              id="plan_on_number_seconds"
              label="On number seconds"
              help="The transcript ends with a number — phone numbers and dates are often dictated in chunks."
              value={value.start.on_number_seconds}
              onChange={(on_number_seconds) => setStart({ on_number_seconds })}
              min={0}
              max={3}
              step={0.1}
            />
          </div>
        )}
      </div>

      <div className="h-px bg-border" />

      <div className="space-y-5">
        <div className="flex items-start gap-2">
          <div>
            <h3 className="text-sm font-medium">Stop speaking plan</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              When the caller&apos;s speech interrupts the agent.
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="ml-auto h-7 gap-1.5 text-xs"
            onClick={() => onChange({ ...value, stop: DEFAULT_SPEAKING_PLAN.stop })}
          >
            <RotateCcw className="h-3 w-3" /> Defaults
          </Button>
        </div>
        <PlanSlider
          id="plan_num_words"
          label="Number of words"
          help="Words the caller must say to interrupt the agent while it speaks. 0 interrupts on voice alone, before transcription."
          value={value.stop.num_words}
          onChange={(num_words) => setStop({ num_words: Math.round(num_words) })}
          min={0}
          max={10}
          step={1}
          unit="words"
        />
        <PlanSlider
          id="plan_voice_seconds"
          label="Voice seconds"
          help="How long the caller must speak before it counts as speech. Higher values ignore short noises and coughs."
          value={value.stop.voice_seconds}
          onChange={(voice_seconds) => setStop({ voice_seconds })}
          min={0}
          max={0.5}
          step={0.05}
        />
        <PlanSlider
          id="plan_backoff_seconds"
          label="Back off seconds"
          help="After being interrupted, the agent waits at least this long before speaking again."
          value={value.stop.backoff_seconds}
          onChange={(backoff_seconds) => setStop({ backoff_seconds })}
          min={0}
          max={10}
          step={0.5}
        />
      </div>
    </>
  );
}
