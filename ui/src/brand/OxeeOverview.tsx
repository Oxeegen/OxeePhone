"use client";

import { ArrowRight, BarChart3, FlaskConical, Loader2, Phone, SearchCheck, Sparkles, Workflow } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useOrganizationTimezone } from "@/hooks/useOrganizationTimezone";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { BRAND } from "./brand";
import { OxeeBrandLogo } from "./BrandLogo";

// Home page: the day at a glance — calls, average quality and technical
// scores (api/brand/call_overview.py), against the day before and the week.

interface DayStats {
  date?: string;
  calls: number;
  scored: number;
  quality: number | null;
  technical: number | null;
  resolved_rate: number | null;
  minutes: number;
}

interface Overview {
  timezone: string;
  today: DayStats;
  yesterday: DayStats;
  week: DayStats;
  daily: DayStats[];
  unscored: number;
}

const score = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(1));

function Delta({ now, before, unit = "", digits = 0 }: { now: number | null; before: number | null; unit?: string; digits?: number }) {
  if (now == null || before == null) return null;
  const d = now - before;
  if (Math.abs(d) < (digits ? 0.05 : 0.5)) return <span className="text-muted-foreground">same as yesterday</span>;
  return (
    <span className={d > 0 ? "text-[var(--verdict-pass-ink)]" : "text-[var(--verdict-fail-ink)]"}>
      {d > 0 ? "+" : "−"}
      {Math.abs(d).toFixed(digits)}
      {unit} vs yesterday
    </span>
  );
}

function Kpi({
  icon: Icon,
  label,
  value,
  suffix,
  badge,
  delta,
  hint,
}: {
  icon: typeof Phone;
  label: string;
  value: string;
  suffix?: string;
  badge?: React.ReactNode;
  delta?: React.ReactNode;
  hint: React.ReactNode;
}) {
  return (
    <Card className="gap-2 p-5">
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--cta)]/10 text-[var(--cta)]">
          <Icon className="h-4 w-4" />
        </span>
        {label}
      </p>
      <p className="flex items-baseline gap-2">
        <span className="text-4xl font-semibold tabular-nums tracking-tight">{value}</span>
        {suffix && <span className="text-lg text-muted-foreground">{suffix}</span>}
        <span className="ml-auto">{badge}</span>
      </p>
      <p className="text-xs">{delta}</p>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </Card>
  );
}

function WeekBars({ days }: { days: DayStats[] }) {
  const max = Math.max(1, ...days.map((d) => d.calls));
  return (
    <Card className="gap-3 p-5">
      <div className="flex items-baseline justify-between">
        <p className="font-medium">Last 7 days</p>
        <p className="text-xs text-muted-foreground">Calls per day · quality / technical average below</p>
      </div>
      <div className="grid grid-cols-7 gap-3">
        {days.map((d, i) => {
          const label = d.date ? new Date(`${d.date}T12:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric" }) : "";
          const today = i === days.length - 1;
          return (
            <div key={d.date ?? i} className="flex flex-col items-center gap-1.5" title={`${label}: ${d.calls} calls · quality ${score(d.quality)} · technical ${score(d.technical)}`}>
              <span className="text-xs tabular-nums text-muted-foreground">{d.calls || ""}</span>
              <div className="flex h-24 w-full items-end justify-center">
                <div
                  className={cn("w-full max-w-10 rounded-t-[4px]", today ? "bg-[var(--cta)]" : "bg-[var(--cta)]/40")}
                  style={{ height: `${d.calls ? Math.max(4, (d.calls / max) * 100) : 0}%` }}
                />
              </div>
              <span className={cn("text-xs", today ? "font-medium" : "text-muted-foreground")}>{today ? "Today" : label}</span>
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {score(d.quality)} / {score(d.technical)}
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

const LINKS = [
  { href: "/workflow", label: "Voice agents", text: "Build and publish your agents", icon: Workflow },
  { href: "/test-campaigns", label: "Test campaigns", text: "Play scenarios against an agent", icon: FlaskConical },
  { href: "/analysis", label: "Analysis", text: "Find what to fix in the calls", icon: SearchCheck },
  { href: "/reports", label: "Reports", text: "Latency, usage and outcomes", icon: BarChart3 },
];

export function OxeeOverview() {
  const auth = useAuth();
  const tz = useOrganizationTimezone();
  const [data, setData] = useState<Overview | null>(null);
  const [grading, setGrading] = useState(false);

  const load = useCallback(async () => {
    const response = await client.get<{ 200: Overview }, unknown>({ url: "/api/v1/oxee/overview", query: { tz } });
    if (!response.error) setData(response.data as Overview);
  }, [tz]);

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    void load();
    const timer = setInterval(() => void load(), 60_000);
    return () => clearInterval(timer);
  }, [auth.loading, auth.isAuthenticated, load]);

  const gradeMissing = async () => {
    setGrading(true);
    const response = await client.post<{ 200: { queued: number } }, unknown>({
      url: "/api/v1/oxee/runs/score-missing",
      body: { days: 7 },
      headers: { "Content-Type": "application/json" },
    });
    setGrading(false);
    if (response.error) toast.error(detailFromError(response.error, "The calls could not be graded"));
    else toast.success(`${(response.data as { queued: number }).queued} calls are being graded; the averages update in a few minutes.`);
  };

  const t = data?.today;
  const w = data?.week;
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-4 py-10">
      <header className="space-y-2">
        <OxeeBrandLogo className="h-14" />
        <p className="text-muted-foreground">{BRAND.description}</p>
      </header>

      {!data ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading today&apos;s activity…
        </p>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            <Kpi
              icon={Phone}
              label="Calls today"
              value={String(t!.calls)}
              delta={<Delta now={t!.calls} before={data.yesterday.calls} />}
              hint={`${t!.minutes} min today · ${w!.calls} call${w!.calls === 1 ? "" : "s"} over 7 days`}
            />
            <Kpi
              icon={Sparkles}
              label="Average quality today"
              value={score(t!.quality)}
              suffix={t!.quality != null ? "/5" : undefined}
              delta={<Delta now={t!.quality} before={data.yesterday.quality} digits={1} />}
              hint={
                <>
                  7-day average {score(w!.quality)}
                  {t!.resolved_rate != null ? ` · ${Math.round(t!.resolved_rate * 100)} % of callers served today` : ""}
                </>
              }
            />
            <Kpi
              icon={BarChart3}
              label="Average technical score today"
              value={score(t!.technical)}
              suffix={t!.technical != null ? "/5" : undefined}
              delta={<Delta now={t!.technical} before={data.yesterday.technical} digits={1} />}
              hint={`7-day average ${score(w!.technical)} · ${t!.scored} of ${t!.calls} call${t!.calls === 1 ? "" : "s"} graded today`}
            />
          </div>

          {data.unscored > 0 && (
            <Card className="flex-row flex-wrap items-center gap-3 p-4 text-sm">
              <span className="text-muted-foreground">
                {data.unscored} call{data.unscored > 1 ? "s" : ""} of the last 7 days {data.unscored > 1 ? "have" : "has"} no score yet (made
                before grading existed, or still being graded).
              </span>
              <Button size="sm" variant="outline" className="ml-auto gap-1.5" disabled={grading} onClick={() => void gradeMissing()}>
                {grading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Grade them
              </Button>
            </Card>
          )}

          <WeekBars days={data.daily} />
        </>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {LINKS.map(({ href, label, text, icon: Icon }) => (
          <Link key={href} href={href} className="group">
            <Card className="h-full gap-1 p-4 transition-colors group-hover:border-[var(--cta)]/50">
              <p className="flex items-center gap-2 font-medium">
                <Icon className="h-4 w-4 text-[var(--cta)]" /> {label}
                <ArrowRight className="ml-auto h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </p>
              <p className="text-xs text-muted-foreground">{text}</p>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
