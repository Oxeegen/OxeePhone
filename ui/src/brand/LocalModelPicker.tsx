"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { detailFromError } from "@/lib/apiError";

// Model field for Local Models services: lists what the configured
// OpenAI-compatible endpoint serves (GET {base_url}/models, proxied by the
// backend so masked keys and private endpoints work). Falls back to free text
// when the endpoint cannot be listed.

type Service = "llm" | "tts" | "stt" | "embeddings";

const FETCH_DEBOUNCE_MS = 600;

export function LocalModelPicker({
  service,
  baseUrl,
  apiKey,
  value,
  onChange,
}: {
  service: Service;
  baseUrl: string;
  apiKey: string;
  value: string;
  onChange: (model: string) => void;
}) {
  const [models, setModels] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState(false);
  const requestId = useRef(0);

  const fetchModels = useCallback(async () => {
    const url = baseUrl.trim();
    if (!url) {
      setModels(null);
      setError(null);
      return;
    }
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    const response = await client.post<{ 200: { models: string[] } }, unknown>({
      url: "/api/v1/oxee/models",
      body: { service, base_url: url, api_key: apiKey || null },
      headers: { "Content-Type": "application/json" },
    });
    if (id !== requestId.current) return;
    setLoading(false);
    if (response.error) {
      setModels(null);
      setError(detailFromError(response.error, "Could not list the endpoint's models"));
      return;
    }
    setModels(response.data?.models ?? []);
  }, [service, baseUrl, apiKey]);

  useEffect(() => {
    const timer = setTimeout(fetchModels, FETCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [fetchModels]);

  const options = models ? Array.from(new Set([...(value ? [value] : []), ...models])) : [];
  const showSelect = !manual && models !== null && options.length > 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {showSelect ? (
          <Select value={value} onValueChange={(model) => model && onChange(model)}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select a model" />
            </SelectTrigger>
            <SelectContent>
              {options.map((model) => (
                <SelectItem key={model} value={model}>
                  {model}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            type="text"
            placeholder={baseUrl.trim() ? "Model name" : "Enter the base URL first"}
            value={value}
            onChange={(event) => onChange(event.target.value)}
          />
        )}
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label="Reload models"
          title="Reload models from the endpoint"
          disabled={!baseUrl.trim() || loading}
          onClick={() => void fetchModels()}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
        </Button>
      </div>
      {error ? (
        <p className="text-xs text-destructive">{error} — you can type the model name.</p>
      ) : models !== null ? (
        <p className="text-xs text-muted-foreground">
          {models.length === 0
            ? "The endpoint lists no model — type the model name."
            : `${models.length} model${models.length > 1 ? "s" : ""} available on the endpoint.`}{" "}
          {models.length > 0 && (
            <button type="button" className="underline" onClick={() => setManual((m) => !m)}>
              {manual ? "Pick from the list" : "Type a name instead"}
            </button>
          )}
        </p>
      ) : null}
    </div>
  );
}
