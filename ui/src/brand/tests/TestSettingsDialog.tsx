"use client";

import { Loader2, Play, Plus, Settings2, Square, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";

import { parseNumbers, type SettingsResponse, type Voice } from "./model";
import { API } from "./ui";

function VoiceListen({ voice }: { voice: string }) {
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
      size="icon"
      variant="ghost"
      className="h-8 w-8 shrink-0"
      disabled={!voice.trim() || state === "loading"}
      title="Listen"
      onClick={async () => {
        if (state === "playing") return stop();
        setState("loading");
        const response = await client.post<{ 200: Blob }, unknown>({
          url: `${API}/voice-preview`,
          body: { voice },
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
    </Button>
  );
}

export function TestSettingsDialog({ data, onSaved }: { data: SettingsResponse | null; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState<string>("none");
  const [inbound, setInbound] = useState("");
  const [numbers, setNumbers] = useState("");
  const [voices, setVoices] = useState<Voice[]>([]);
  const [concurrency, setConcurrency] = useState(2);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !data) return;
    const s = data.settings;
    setConfig(s.tester_telephony_configuration_id ? String(s.tester_telephony_configuration_id) : "none");
    setInbound(s.test_inbound_number ?? "");
    setNumbers(s.caller_numbers.join("\n"));
    setVoices(s.voices);
    setConcurrency(s.concurrency);
  }, [open, data]);

  const save = async () => {
    setSaving(true);
    const response = await client.put({
      url: `${API}/settings`,
      body: {
        tester_telephony_configuration_id: config === "none" ? null : Number(config),
        test_inbound_number: inbound.trim() || null,
        caller_numbers: parseNumbers(numbers),
        voices: voices.filter((v) => v.id.trim()),
        concurrency,
      },
      headers: { "Content-Type": "application/json" },
    });
    setSaving(false);
    if (response.error) {
      toast.error(detailFromError(response.error, "The settings could not be saved"));
      return;
    }
    toast.success("Test settings saved");
    setOpen(false);
    onSaved();
  };

  const s = data?.settings;
  return (
    <>
      <Button variant="outline" className="gap-2" onClick={() => setOpen(true)}>
        <Settings2 className="h-4 w-4" /> Test settings
        {s && (!s.voices.length || !s.caller_numbers.length || !s.tester_telephony_configuration_id) && (
          <span className="h-2 w-2 rounded-full bg-amber-500" title="Incomplete" />
        )}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Test settings</DialogTitle>
            <DialogDescription>
              Shared by every test campaign of the organization. Each scenario gets its own caller number and voice
              from the pools, without repeats while the pools last.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-5 text-sm">
            <section className="space-y-2">
              <h4 className="font-medium">Telephony (phone executions)</h4>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1">
                  <span className="text-xs text-muted-foreground">Tester&apos;s telephony configuration</span>
                  <Select value={config} onValueChange={setConfig}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">None (text executions only)</SelectItem>
                      {data?.telephony_configurations.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>
                          {c.name} · {c.provider}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>
                <label className="space-y-1">
                  <span className="text-xs text-muted-foreground">Dedicated test number (optional)</span>
                  <Input value={inbound} onChange={(e) => setInbound(e.target.value)} placeholder="Empty: the agent's own number" />
                </label>
              </div>
              <p className="text-xs text-muted-foreground">
                The tester calls from this configuration. Without a dedicated test number it calls the agent&apos;s own
                inbound number; each test call carries a one-time token in its CallerID name, so it runs the version under
                test and stays out of the production statistics.
              </p>
              <label className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Calls in parallel</span>
                <Input
                  type="number"
                  min={1}
                  max={10}
                  value={concurrency}
                  onChange={(e) => setConcurrency(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
                  className="w-20"
                />
                <span className="text-xs text-muted-foreground">each test call uses two lines (caller + agent)</span>
              </label>
            </section>

            <section className="space-y-2">
              <h4 className="font-medium">Caller numbers ({parseNumbers(numbers).length})</h4>
              <Textarea
                value={numbers}
                onChange={(e) => setNumbers(e.target.value)}
                rows={5}
                placeholder={"+33612345678\n+33698765432"}
                className="font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">One per line: the number each simulated caller presents to the agent (real customer numbers, so lookups by caller number behave as in production).</p>
            </section>

            <section className="space-y-2">
              <h4 className="font-medium">Voices ({voices.filter((v) => v.id.trim()).length})</h4>
              <div className="space-y-1.5">
                {voices.map((v, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Input
                      value={v.id}
                      onChange={(e) => setVoices((list) => list.map((x, j) => (j === i ? { ...x, id: e.target.value } : x)))}
                      placeholder="Voice id (e.g. fr_cedric)"
                      className="font-mono text-xs"
                    />
                    <Select value={v.gender} onValueChange={(g) => setVoices((list) => list.map((x, j) => (j === i ? { ...x, gender: g as Voice["gender"] } : x)))}>
                      <SelectTrigger className="w-[120px] shrink-0"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="female">Female</SelectItem>
                        <SelectItem value="male">Male</SelectItem>
                        <SelectItem value="unknown">Unknown</SelectItem>
                      </SelectContent>
                    </Select>
                    <VoiceListen voice={v.id} />
                    <Button type="button" size="icon" variant="ghost" className="h-8 w-8 shrink-0" title="Remove" onClick={() => setVoices((list) => list.filter((_, j) => j !== i))}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
              <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={() => setVoices((list) => [...list, { id: "", gender: "female" }])}>
                <Plus className="h-4 w-4" /> Add a voice
              </Button>
              <p className="text-xs text-muted-foreground">Voices of your voice model (Models › Voice). The gender keeps the persona coherent with the voice.</p>
            </section>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => void save()} disabled={saving} className="gap-2 bg-[var(--cta)] text-[var(--cta-foreground)] hover:opacity-90">
              {saving && <Loader2 className="h-4 w-4 animate-spin" />} Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
