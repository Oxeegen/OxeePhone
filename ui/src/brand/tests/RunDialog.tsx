"use client";

import { Loader2, MessageSquareText, Phone, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { detailFromError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

import type { VersionItem } from "../versions/model";
import { type Campaign, type Channel, estimateMinutes } from "./model";
import { API } from "./ui";

interface PhoneCheck {
  ok: boolean;
  error?: string;
  destination?: string;
  provider?: string;
}

export function RunDialog({
  campaign,
  open,
  onOpenChange,
  onStarted,
  concurrencyDefault,
}: {
  campaign: Campaign;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (executionId: string) => void;
  concurrencyDefault: number;
}) {
  const [versions, setVersions] = useState<VersionItem[]>([]);
  const [version, setVersion] = useState("published");
  const [channel, setChannel] = useState<Channel>("phone");
  const [passes, setPasses] = useState(1);
  const [personas, setPersonas] = useState<"frozen" | "fresh">("frozen");
  const [concurrency, setConcurrency] = useState(concurrencyDefault);
  const [phone, setPhone] = useState<PhoneCheck | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setConcurrency(concurrencyDefault);
    void client
      .get<{ 200: { items: VersionItem[] } }, unknown>({ url: `/api/v1/oxee/workflows/${campaign.workflow_id}/versions`, query: { limit: 30 } })
      .then((r) => {
        const items = (r.data as { items: VersionItem[] } | undefined)?.items ?? [];
        setVersions(items);
        setVersion(items.some((v) => v.status === "draft") ? "draft" : "published");
      });
    void client
      .get<{ 200: PhoneCheck }, unknown>({ url: `${API}/phone-check`, query: { workflow_id: campaign.workflow_id } })
      .then((r) => {
        const check = (r.data as PhoneCheck) ?? { ok: false };
        setPhone(check);
        if (!check.ok) setChannel("text");
      });
  }, [open, campaign.workflow_id, concurrencyDefault]);

  const enabled = campaign.scenarios.filter((s) => s.enabled).length;
  const calls = enabled * passes;
  const draft = versions.find((v) => v.status === "draft");
  const published = versions.find((v) => v.status === "published");

  const start = async () => {
    setStarting(true);
    const response = await client.post<{ 200: { id: string } }, unknown>({
      url: `${API}/campaigns/${campaign.id}/executions`,
      body: {
        version: version === "published" || version === "draft" ? version : Number(version),
        channel,
        passes,
        personas,
        concurrency,
      },
      headers: { "Content-Type": "application/json" },
    });
    setStarting(false);
    if (response.error) {
      toast.error(detailFromError(response.error, "The execution could not start"));
      return;
    }
    onOpenChange(false);
    onStarted((response.data as { id: string }).id);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Play the campaign</DialogTitle>
          <DialogDescription>
            {enabled} enabled scenario{enabled === 1 ? "" : "s"} on one version of {campaign.workflow_name}. Replay it on
            another version later and compare the two executions.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 text-sm">
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">Version of the agent</span>
            <Select value={version} onValueChange={setVersion}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {published && <SelectItem value="published">Published (v{published.version_number})</SelectItem>}
                {draft && <SelectItem value="draft">Draft (v{draft.version_number})</SelectItem>}
                {versions
                  .filter((v) => v.status !== "draft" && v.status !== "published")
                  .map((v) => (
                    <SelectItem key={v.id} value={String(v.id)}>
                      v{v.version_number} · {v.status}
                      {v.published_at ? ` · ${new Date(v.published_at).toLocaleDateString()}` : ""}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </label>

          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Channel</span>
            <div className="grid grid-cols-2 gap-2">
              {(
                [
                  ["phone", Phone, "Phone", "Real calls: voices, speech recognition, latency, interruptions."],
                  ["text", MessageSquareText, "Text", "Fast and free: logic, routing, prompts and extractions only."],
                ] as const
              ).map(([value, Icon, label, hint]) => (
                <button
                  key={value}
                  type="button"
                  disabled={value === "phone" && !phone?.ok}
                  onClick={() => setChannel(value)}
                  className={cn(
                    "space-y-1 rounded-lg border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                    channel === value ? "border-[var(--cta)] bg-[var(--cta)]/5" : "border-border hover:bg-muted/40",
                  )}
                >
                  <span className="flex items-center gap-1.5 font-medium"><Icon className="h-4 w-4" /> {label}</span>
                  <span className="block text-[11px] text-muted-foreground">{hint}</span>
                </button>
              ))}
            </div>
            {phone && !phone.ok && <p className="text-[11px] text-amber-700 dark:text-amber-300">Phone not available: {phone.error}</p>}
            {phone?.ok && channel === "phone" && (
              <p className="text-[11px] text-muted-foreground">Calls {phone.destination} through {phone.provider}.</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">Plays per scenario</span>
              <Input type="number" min={1} max={10} value={passes} onChange={(e) => setPasses(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} />
            </label>
            {channel === "phone" && (
              <label className="space-y-1">
                <span className="text-xs text-muted-foreground">Calls in parallel</span>
                <Input type="number" min={1} max={10} value={concurrency} onChange={(e) => setConcurrency(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} />
              </label>
            )}
          </div>

          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">Callers</span>
            <Select value={personas} onValueChange={(v) => setPersonas(v as "frozen" | "fresh")}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="frozen">Same personas as before (fair comparison)</SelectItem>
                <SelectItem value="fresh">New voices, numbers and speeds this time</SelectItem>
              </SelectContent>
            </Select>
          </label>

          <p className="rounded-md bg-muted/60 p-2.5 text-xs text-muted-foreground">
            {calls} call{calls === 1 ? "" : "s"} · about {estimateMinutes(calls, channel, concurrency)} min. A model plays
            each caller and judges each call. One execution runs at a time; the next ones wait in the queue.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => void start()} disabled={starting || !enabled} className="gap-2 bg-[var(--cta)] text-[var(--cta-foreground)] hover:opacity-90">
            {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Start
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
