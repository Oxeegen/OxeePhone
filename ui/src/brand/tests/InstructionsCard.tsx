"use client";

import { Loader2, Pencil, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";

import type { Campaign } from "./model";
import { API } from "./ui";

/** The campaign's instructions to the scenario writer; saving them revises
 * the existing scenarios (api/brand/test_campaigns.py rewrite). */
export function InstructionsCard({ campaign, onSaved }: { campaign: Campaign; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(campaign.instructions ?? "");
  const [apply, setApply] = useState(true);
  const [keepEdited, setKeepEdited] = useState(false);
  const [busy, setBusy] = useState(false);
  const writing = campaign.status === "generating";
  const edited = campaign.scenarios.filter((s) => s.edited_at && !s.rewritten_at).length;

  const save = async () => {
    setBusy(true);
    const response = await client.put({
      url: `${API}/campaigns/${campaign.id}/instructions`,
      body: { instructions: text.trim() || null, apply_to_scenarios: apply, keep_edited: keepEdited },
      headers: { "Content-Type": "application/json" },
    });
    setBusy(false);
    if (response.error) {
      toast.error(detailFromError(response.error, "The instructions could not be saved"));
      return;
    }
    toast.success(apply && campaign.scenarios.length ? "Instructions saved: the scenarios are being revised" : "Instructions saved");
    setEditing(false);
    onSaved();
  };

  if (!editing) {
    return (
      <Card className="gap-1 p-4">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium">Instructions for the scenarios</p>
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto h-7 gap-1.5 text-xs"
            disabled={writing}
            onClick={() => {
              setText(campaign.instructions ?? "");
              setEditing(true);
            }}
          >
            <Pencil className="h-3.5 w-3.5" /> Edit
          </Button>
        </div>
        <p className="whitespace-pre-wrap text-sm text-muted-foreground">
          {campaign.instructions || "None: the scenarios follow the agent's configuration and the caller settings only."}
        </p>
      </Card>
    );
  }

  const changed = (text.trim() || null) !== (campaign.instructions ?? null);
  return (
    <Card className="gap-3 p-4">
      <p className="text-sm font-medium">Instructions for the scenarios</p>
      <Textarea
        rows={4}
        maxLength={2000}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. callers ask to be put through to the switchboard for billing questions; half of them are existing patients"
      />
      <div className="space-y-1.5 text-xs">
        <label className="flex items-center gap-2">
          <Checkbox checked={apply} onCheckedChange={(v) => setApply(v === true)} />
          Revise the {campaign.scenarios.length} existing scenarios to follow them (caller settings, voices and numbers are kept)
        </label>
        {apply && edited > 0 && (
          <label className="flex items-center gap-2 pl-6">
            <Checkbox checked={keepEdited} onCheckedChange={(v) => setKeepEdited(v === true)} />
            Leave out the {edited} scenario{edited > 1 ? "s" : ""} edited by hand
          </label>
        )}
        <p className="text-muted-foreground">
          Executions already played keep the scenarios as they were; comparing with a later execution shows the changes
          of the scenarios too.
        </p>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={() => setEditing(false)}>
          Cancel
        </Button>
        <Button size="sm" className="gap-1.5" disabled={busy || (!changed && !apply)} onClick={() => void save()}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          {apply && campaign.scenarios.length ? "Save and revise the scenarios" : "Save"}
        </Button>
      </div>
    </Card>
  );
}
