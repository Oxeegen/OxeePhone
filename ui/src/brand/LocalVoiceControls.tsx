"use client";

import { Loader2, Play, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { detailFromError } from "@/lib/apiError";

// Voice tab controls for Local Models TTS: the voice id with a "Listen" button
// rendering a sample exactly as a call would (POST /api/v1/oxee/tts/preview:
// same pronunciation dictionary, French normalization and gain; masked keys
// and private endpoints work), plus range sliders for speed and volume.

const SAMPLE_PLACEHOLDER = "Bonjour, votre rendez-vous est confirmé mardi à 14h30.";

// Friendlier labels than the schema field names.
const FIELD_LABELS: Record<string, string> = {
  volume_gain_db: "Volume",
  pronunciations: "Pronunciation dictionary",
};

export function localFieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field.replace(/_/g, " ");
}

export interface VoicePreviewSettings {
  baseUrl: string;
  apiKey: string;
  model: string;
  speed?: number;
  language?: string;
  volumeGainDb?: number;
  pronunciations?: string;
}

export function LocalVoiceField({
  value,
  onChange,
  preview,
}: {
  value: string;
  onChange: (voice: string) => void;
  preview: VoicePreviewSettings;
}) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [error, setError] = useState<string | null>(null);
  const [sample, setSample] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);

  const stop = () => {
    audioRef.current?.pause();
    audioRef.current = null;
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
    setState("idle");
  };

  useEffect(() => stop, []);

  const missing = !preview.baseUrl.trim() ? "base URL" : !preview.model.trim() ? "model" : !value.trim() ? "voice" : null;

  const listen = async () => {
    if (state === "playing") {
      stop();
      return;
    }
    setError(null);
    setState("loading");
    const response = await client.post<{ 200: Blob }, unknown>({
      url: "/api/v1/oxee/tts/preview",
      body: {
        base_url: preview.baseUrl.trim(),
        api_key: preview.apiKey || null,
        model: preview.model.trim(),
        voice: value.trim(),
        speed: preview.speed ?? null,
        language: preview.language?.trim() || null,
        volume_gain_db: preview.volumeGainDb ?? null,
        pronunciations: preview.pronunciations || null,
        text: sample.trim() || null,
      },
      headers: { "Content-Type": "application/json" },
      parseAs: "blob",
    });
    if (response.error || !response.data) {
      setState("idle");
      setError(detailFromError(response.error, "Could not render a sample"));
      return;
    }
    const url = URL.createObjectURL(response.data as Blob);
    urlRef.current = url;
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.onended = stop;
    try {
      await audio.play();
      setState("playing");
    } catch {
      stop();
      setError("The browser blocked audio playback.");
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Input type="text" placeholder="Voice id (e.g. fr_cedric)" value={value} onChange={(e) => onChange(e.target.value)} />
        <Button
          type="button"
          variant="outline"
          className="shrink-0 gap-1.5"
          disabled={state === "loading" || (state === "idle" && missing !== null)}
          title={missing ? `Fill in the ${missing} first` : "Play a sample with these settings"}
          onClick={() => void listen()}
        >
          {state === "loading" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : state === "playing" ? (
            <Square className="h-4 w-4" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {state === "playing" ? "Stop" : "Listen"}
        </Button>
      </div>
      <Input
        type="text"
        className="h-8 text-xs"
        placeholder={`Test sentence (default: "${SAMPLE_PLACEHOLDER}")`}
        value={sample}
        onChange={(e) => setSample(e.target.value)}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

export function LocalSpeedSlider(props: {
  value: number;
  onChange: (speed: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <LocalRangeSlider
      {...props}
      min={props.min ?? 0.5}
      max={props.max ?? 2}
      step={0.05}
      neutral={1}
      ariaLabel="Speech speed"
      lowLabel="Slower"
      highLabel="Faster"
      format={(v) => `${v.toFixed(2)}×`}
    />
  );
}

export function LocalVolumeSlider(props: {
  value: number;
  onChange: (db: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <LocalRangeSlider
      {...props}
      min={props.min ?? -12}
      max={props.max ?? 12}
      step={0.5}
      neutral={0}
      ariaLabel="Volume adjustment"
      lowLabel="Quieter"
      highLabel="Louder"
      format={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)} dB`}
    />
  );
}

function LocalRangeSlider({
  value,
  onChange,
  min,
  max,
  step,
  neutral,
  ariaLabel,
  lowLabel,
  highLabel,
  format,
}: {
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
  neutral: number;
  ariaLabel: string;
  lowLabel: string;
  highLabel: string;
  format: (value: number) => string;
}) {
  const current = Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : neutral;
  return (
    <div className="flex h-9 items-center gap-3">
      <span className="text-xs text-muted-foreground">{lowLabel}</span>
      <input
        type="range"
        aria-label={ariaLabel}
        min={min}
        max={max}
        step={step}
        value={current}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 w-full cursor-pointer accent-[var(--cta)]"
      />
      <span className="text-xs text-muted-foreground">{highLabel}</span>
      <button
        type="button"
        className="w-16 shrink-0 rounded-md border border-border px-1.5 py-1 text-center text-xs tabular-nums hover:bg-muted"
        title={`Reset to ${format(neutral)}`}
        onClick={() => onChange(neutral)}
      >
        {format(current)}
      </button>
    </div>
  );
}
