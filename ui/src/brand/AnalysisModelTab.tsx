"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { LocalModelPicker } from "@/brand/LocalModelPicker";
import { client } from "@/client/client.gen";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

// Models > Analysis: the model that reviews recorded calls on the Analysis
// page. Saved together with the rest of the Models form (see
// ServiceConfigurationForm), stored under the org config OXEE_ANALYSIS_MODEL.

export interface AnalysisModelTabHandle {
  save: () => Promise<void>;
}

interface AnalysisModel {
  same_as_llm: boolean;
  base_url: string | null;
  api_key: string | null;
  model: string | null;
}

export const AnalysisModelTab = forwardRef<AnalysisModelTabHandle>(function AnalysisModelTab(_props, ref) {
  const [config, setConfig] = useState<AnalysisModel>({ same_as_llm: true, base_url: "", api_key: "", model: "" });
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A late load must never overwrite what the user already changed.
  const touched = useRef(false);
  const auth = useAuth();

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated) return;
    (async () => {
      const response = await client.get<{ 200: AnalysisModel }, unknown>({ url: "/api/v1/oxee/analysis/model" });
      if (response.data && !touched.current) setConfig(response.data as AnalysisModel);
      setLoaded(true);
    })();
  }, [auth.loading, auth.isAuthenticated]);

  useImperativeHandle(ref, () => ({
    save: async () => {
      if (!loaded && !touched.current) return;
      setError(null);
      const response = await client.put<{ 200: AnalysisModel }, unknown>({
        url: "/api/v1/oxee/analysis/model",
        body: config,
        headers: { "Content-Type": "application/json" },
      });
      if (response.error) {
        const message = detailFromError(response.error, "Could not save the analysis model");
        setError(message);
        throw new Error(`Analysis: ${message}`);
      }
      setConfig(response.data as AnalysisModel);
    },
  }));

  const set = (patch: Partial<AnalysisModel>) => {
    touched.current = true;
    setConfig((c) => ({ ...c, ...patch }));
  };

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Model used by the <span className="font-medium text-foreground">Analysis</span> page to review recorded calls and
        point out configuration problems. A larger model than the one answering callers usually gives better reviews.
      </p>
      <div className="flex items-center gap-2">
        <Checkbox
          id="analysis-same-as-llm"
          checked={config.same_as_llm}
          onCheckedChange={(checked) => set({ same_as_llm: checked === true })}
        />
        <Label htmlFor="analysis-same-as-llm" className="cursor-pointer font-normal">
          Use the LLM configuration
        </Label>
      </div>
      {!config.same_as_llm && (
        <>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Base URL</Label>
              <Input
                placeholder="https://…/v1"
                value={config.base_url ?? ""}
                onChange={(e) => set({ base_url: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">OpenAI-compatible endpoint, including /v1 (e.g. vLLM).</p>
            </div>
            <div className="space-y-2">
              <Label>Model</Label>
              <LocalModelPicker
                service="analysis"
                baseUrl={config.base_url ?? ""}
                apiKey={config.api_key ?? ""}
                value={config.model ?? ""}
                onChange={(model) => set({ model })}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>API Key</Label>
            <Input
              placeholder="Enter API key"
              value={config.api_key ?? ""}
              onChange={(e) => set({ api_key: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">Leave blank unless the endpoint enforces one.</p>
          </div>
        </>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
});
