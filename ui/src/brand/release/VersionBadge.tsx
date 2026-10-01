"use client";

import { ArrowUpCircle, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { BRAND } from "@/brand/brand";
import { client } from "@/client/client.gen";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { Markdown } from "./Markdown";

// Sidebar version: opens the release notes of the running version and, when
// GitHub has newer OxeePhone releases, their notes and the update command
// (GET /api/v1/oxee/releases, checked by the server).

export interface ReleaseNote {
  version: string;
  tag: string;
  name: string;
  url: string | null;
  published_at: string | null;
  notes: string;
}

export interface ReleaseInfo {
  enabled: boolean;
  repository: string;
  current: string;
  current_release?: ReleaseNote | null;
  latest?: Omit<ReleaseNote, "notes"> | null;
  update_available: boolean;
  newer: ReleaseNote[];
  error?: string | null;
}

export const UPDATE_COMMAND = "sudo ./brand/install.sh update";

const day = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString() : "");

function ReleaseSection({ release, title }: { release: ReleaseNote; title: string }) {
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="font-semibold">{title}</h3>
        <span className="text-xs text-muted-foreground">{day(release.published_at)}</span>
        {release.url && (
          <a href={release.url} target="_blank" rel="noopener noreferrer" className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            GitHub <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      {release.notes.trim() ? <Markdown source={release.notes} /> : <p className="text-sm text-muted-foreground">No release notes.</p>}
    </section>
  );
}

export function VersionBadge({ baseVersion }: { baseVersion?: string }) {
  const auth = useAuth();
  const [info, setInfo] = useState<ReleaseInfo | null>(null);
  const [open, setOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const loaded = useRef(false);

  const load = useCallback(async (refresh = false) => {
    const response = await client.get<{ 200: ReleaseInfo }, unknown>({
      url: "/api/v1/oxee/releases",
      query: refresh ? { refresh: true } : undefined,
    });
    if (response.data) setInfo(response.data as ReleaseInfo);
  }, []);

  useEffect(() => {
    if (auth.loading || !auth.isAuthenticated || loaded.current) return;
    loaded.current = true;
    void load();
  }, [auth.loading, auth.isAuthenticated, load]);

  const update = info?.update_available ? info.latest : null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-no-rebrand=""
        title={`${BRAND.productName} ${BRAND.version}${baseVersion ? ` — based on Dograh ${baseVersion}` : ""}. Click for the release notes.`}
        className="notranslate inline-flex items-center gap-1.5 rounded-md px-1 text-xs font-normal text-muted-foreground hover:bg-accent hover:text-foreground"
        translate="no"
      >
        v{BRAND.version}
        {update && (
          <span className="inline-flex items-center gap-0.5 rounded-md border border-amber-500/40 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium leading-none text-amber-900 dark:bg-amber-950 dark:text-amber-200">
            <ArrowUpCircle className="h-3 w-3" /> Update
          </span>
        )}
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl" data-no-rebrand="">
          <DialogHeader>
            <DialogTitle>
              {BRAND.productName} {BRAND.version}
            </DialogTitle>
            <DialogDescription>
              {baseVersion ? `Based on Dograh ${baseVersion}. ` : ""}
              Releases: {info?.repository ?? "Oxeegen/OxeePhone"} on GitHub.
            </DialogDescription>
          </DialogHeader>

          {!info ? (
            <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (
            <div className="space-y-5">
              {!info.enabled ? (
                <p className="text-sm text-muted-foreground">Update check turned off on this server (OXEE_UPDATE_CHECK=false).</p>
              ) : info.error ? (
                <p className="rounded-md bg-muted p-3 text-sm">
                  {info.error}: the release notes and the update check are not available. The server needs access to
                  api.github.com.
                </p>
              ) : update ? (
                <div className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                  <p className="font-medium">
                    {BRAND.productName} {update.version} is available ({info.newer.length} new release{info.newer.length > 1 ? "s" : ""}).
                  </p>
                  <p>On the server, in the install directory (default /opt/oxeephone):</p>
                  <pre className="overflow-x-auto rounded bg-background/80 p-2 text-xs"><code>{UPDATE_COMMAND}</code></pre>
                  <p className="text-xs text-muted-foreground">
                    It fetches the release, rebuilds and restarts; settings, agents and recordings are kept. Calls in
                    progress are cut during the restart (a minute or two).
                  </p>
                </div>
              ) : (
                <p className="text-sm text-emerald-700 dark:text-emerald-300">You are running the latest release.</p>
              )}

              {info.newer.map((r) => (
                <ReleaseSection key={r.tag} release={r} title={`What's new in ${r.version}`} />
              ))}

              {info.current_release ? (
                <ReleaseSection release={info.current_release} title={`Release notes — ${info.current} (running)`} />
              ) : info.enabled && !info.error ? (
                <p className="text-sm text-muted-foreground">No GitHub release for {info.current} (development build).</p>
              ) : null}

              {info.enabled && (
                <button
                  type="button"
                  disabled={refreshing}
                  onClick={async () => {
                    setRefreshing(true);
                    await load(true);
                    setRefreshing(false);
                  }}
                  className={cn("inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground")}
                >
                  <RefreshCw className={cn("h-3 w-3", refreshing && "animate-spin")} /> Check again
                </button>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
