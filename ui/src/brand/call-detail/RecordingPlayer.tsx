"use client";

import { Download, Loader2, Pause, Play } from "lucide-react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { getSignedUrl } from "@/lib/files";

import { formatClock } from "./model";

// Two-lane recording player (caller on top, agent below) drawn on a canvas:
// the played part is bright, the rest dimmed; hover shows the time, click
// seeks. Playback uses the mixed recording; lanes come from the split tracks
// (falling back to the mixed one).

export interface RecordingPlayerHandle {
  seek: (seconds: number, play?: boolean) => void;
}

const PEAK_BUCKETS = 1600;
const USER_COLOR = "#F5B83D";
const AGENT_COLOR = "#8E80FF";
const SPEEDS = [0.75, 1, 1.25, 1.5, 2];
const HEIGHT = 150;
const LANE = { user: [14, 58], agent: [72, 116] } as const;

type Peaks = Float32Array;

async function decodePeaks(url: string): Promise<{ peaks: Peaks; duration: number; onset: number | null }> {
  const response = await fetch(url);
  const buffer = await response.arrayBuffer();
  const ctx = new AudioContext();
  try {
    const audio = await ctx.decodeAudioData(buffer);
    const data = audio.getChannelData(0);
    const peaks = new Float32Array(PEAK_BUCKETS);
    const size = Math.max(1, Math.floor(data.length / PEAK_BUCKETS));
    let max = 0;
    for (let b = 0; b < PEAK_BUCKETS; b++) {
      let peak = 0;
      const end = Math.min(data.length, (b + 1) * size);
      for (let i = b * size; i < end; i++) {
        const v = Math.abs(data[i]);
        if (v > peak) peak = v;
      }
      peaks[b] = peak;
      if (peak > max) max = peak;
    }
    if (max > 0) for (let b = 0; b < PEAK_BUCKETS; b++) peaks[b] /= max;
    // First sustained sound (for aligning calls recorded before the marker).
    const threshold = 0.02;
    const window = Math.floor(audio.sampleRate * 0.02);
    let onset: number | null = null;
    for (let i = 0; i + window < data.length; i += window) {
      let energy = 0;
      for (let j = i; j < i + window; j++) energy += data[j] * data[j];
      if (Math.sqrt(energy / window) > threshold) {
        onset = i / audio.sampleRate;
        break;
      }
    }
    return { peaks, duration: audio.duration, onset };
  } finally {
    void ctx.close();
  }
}

export const RecordingPlayer = forwardRef<
  RecordingPlayerHandle,
  {
    mixedKey: string | null;
    userKey: string | null;
    agentKey: string | null;
    onTime?: (seconds: number) => void;
    onAgentOnset?: (seconds: number | null) => void;
  }
>(function RecordingPlayer({ mixedKey, userKey, agentKey, onTime, onAgentOnset }, ref) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [lanes, setLanes] = useState<{ user: Peaks | null; agent: Peaks | null; mixed: Peaks | null }>({
    user: null, agent: null, mixed: null,
  });
  const [duration, setDuration] = useState(0);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [hover, setHover] = useState<number | null>(null);
  const [width, setWidth] = useState(0);
  const [status, setStatus] = useState<"loading" | "ready" | "missing" | "error">("loading");

  useImperativeHandle(ref, () => ({
    seek: (seconds, play = true) => {
      const audio = audioRef.current;
      if (!audio) return;
      audio.currentTime = Math.max(0, seconds);
      setTime(audio.currentTime);
      onTime?.(audio.currentTime);
      if (play) void audio.play();
    },
  }));

  // Sign URLs and decode lanes.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!mixedKey && !agentKey) {
        setStatus("missing");
        return;
      }
      try {
        const [mixed, user, agent, download] = await Promise.all([
          getSignedUrl(mixedKey ?? agentKey, true),
          getSignedUrl(userKey, true),
          getSignedUrl(agentKey, true),
          getSignedUrl(mixedKey ?? agentKey, false),
        ]);
        if (cancelled) return;
        setSrc(mixed);
        setDownloadUrl(download);
        const decoded = await Promise.all([
          user ? decodePeaks(user) : null,
          agent ? decodePeaks(agent) : null,
          !user && !agent && mixed ? decodePeaks(mixed) : null,
        ]);
        if (cancelled) return;
        setLanes({ user: decoded[0]?.peaks ?? null, agent: decoded[1]?.peaks ?? null, mixed: decoded[2]?.peaks ?? null });
        setDuration((d) => d || decoded.find((x) => x)?.duration || 0);
        onAgentOnset?.(decoded[1]?.onset ?? null);
        setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mixedKey, userKey, agentKey, onAgentOnset]);

  // Track container width.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Smooth time updates while playing.
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      const t = audioRef.current?.currentTime ?? 0;
      setTime(t);
      onTime?.(t);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, onTime]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = speed;
  }, [speed]);

  // Draw.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !width) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = HEIGHT * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, HEIGHT);
    const muted = getComputedStyle(canvas).color;
    const progressX = duration ? (time / duration) * width : 0;

    const drawLane = (peaks: Peaks | null, [top, bottom]: readonly [number, number], color: string) => {
      const mid = (top + bottom) / 2;
      const half = (bottom - top) / 2;
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.28;
      ctx.fillRect(0, mid - 0.5, width, 1);
      if (!peaks) return;
      for (let x = 0; x < width; x++) {
        const from = Math.floor((x / width) * peaks.length);
        const to = Math.max(from + 1, Math.floor(((x + 1) / width) * peaks.length));
        let peak = 0;
        for (let i = from; i < to; i++) peak = Math.max(peak, peaks[i]);
        const h = Math.max(0.5, peak * half);
        ctx.globalAlpha = x <= progressX ? 1 : 0.32;
        ctx.fillRect(x, mid - h, 1, h * 2);
      }
    };
    if (lanes.user || lanes.agent) {
      drawLane(lanes.user, LANE.user, USER_COLOR);
      drawLane(lanes.agent, LANE.agent, AGENT_COLOR);
    } else {
      drawLane(lanes.mixed, [LANE.user[0], LANE.agent[1]], AGENT_COLOR);
    }

    // Ruler.
    ctx.globalAlpha = 1;
    ctx.fillStyle = muted;
    ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
    if (duration > 0) {
      const step = duration > 300 ? 30 : duration > 120 ? 10 : duration > 40 ? 5 : 1;
      for (let s = 0; s <= duration; s += step) {
        const x = (s / duration) * width;
        const major = s % (step * 5) === 0;
        ctx.globalAlpha = major ? 0.9 : 0.45;
        ctx.fillRect(x, 124, 1, major ? 10 : 5);
        if (major && s > 0) ctx.fillText(formatClock(s), x + 3, 146);
      }
    }
    // Playhead + hover.
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(Math.min(width - 1, progressX), 4, 1.5, 132);
    if (hover !== null && duration > 0) {
      const hx = (hover / duration) * width;
      ctx.globalAlpha = 0.5;
      ctx.fillStyle = muted;
      ctx.fillRect(hx, 4, 1, 132);
      ctx.globalAlpha = 1;
      const label = formatClock(hover);
      ctx.fillText(label, Math.min(hx + 4, width - 34), 12);
    }
  }, [lanes, width, time, duration, hover]);

  const positionToTime = useCallback(
    (clientX: number) => {
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect || !duration) return null;
      return Math.min(duration, Math.max(0, ((clientX - rect.left) / rect.width) * duration));
    },
    [duration],
  );

  const toggle = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) void audio.play();
    else audio.pause();
  };

  if (status === "missing") {
    return <p className="text-sm text-muted-foreground">No recording for this call.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Recording</h2>
        <span className="font-mono text-sm tabular-nums text-muted-foreground">
          {formatClock(time)} / {formatClock(duration)}
        </span>
      </div>
      <div ref={wrapRef} className="relative w-full">
        <canvas
          ref={canvasRef}
          className="block w-full cursor-pointer text-muted-foreground"
          style={{ height: HEIGHT }}
          role="slider"
          aria-label="Recording position"
          aria-valuemin={0}
          aria-valuemax={Math.round(duration)}
          aria-valuenow={Math.round(time)}
          onMouseMove={(e) => setHover(positionToTime(e.clientX))}
          onMouseLeave={() => setHover(null)}
          onClick={(e) => {
            const t = positionToTime(e.clientX);
            if (t !== null && audioRef.current) {
              audioRef.current.currentTime = t;
              setTime(t);
              onTime?.(t);
            }
          }}
        />
        {status === "loading" && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading recording…
          </div>
        )}
        {status === "error" && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-destructive">
            Could not load the recording.
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" size="icon" onClick={toggle} disabled={!src} aria-label={playing ? "Pause" : "Play"} className="bg-[var(--cta)] text-[var(--cta-foreground)] hover:opacity-90">
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        </Button>
        <div className="flex overflow-hidden rounded-md border border-border text-xs">
          {SPEEDS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSpeed(s)}
              className={`px-2 py-1.5 tabular-nums ${s === speed ? "bg-muted font-semibold" : "text-muted-foreground hover:bg-muted/60"}`}
            >
              {s}×
            </button>
          ))}
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: USER_COLOR }} /> Caller</span>
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: AGENT_COLOR }} /> Agent</span>
        </div>
        {downloadUrl && (
          <Button asChild variant="outline" size="sm" className="ml-auto gap-2">
            <a href={downloadUrl} download>
              <Download className="h-4 w-4" /> Audio
            </a>
          </Button>
        )}
      </div>
      {src && (
        <audio
          ref={audioRef}
          src={src}
          preload="auto"
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 0)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          onSeeked={(e) => {
            setTime(e.currentTarget.currentTime);
            onTime?.(e.currentTarget.currentTime);
          }}
        />
      )}
    </div>
  );
});
