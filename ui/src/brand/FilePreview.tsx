"use client";

import { Eye, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { client } from "@/client/client.gen";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { detailFromError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

// Files page: preview of a document (api/brand/files.py). Markdown is rendered
// (GitHub flavour: tables, task lists); raw HTML in the file is shown as text.

interface Preview {
  filename: string;
  format: "markdown" | "text";
  source: "file" | "extracted";
  content: string;
  truncated: boolean;
}

const TEXT_FILE = /\.(md|markdown|txt)$/i;

/** Text files, and documents kept whole (their extracted text), have a preview. */
export function hasPreview(filename: string, retrievalMode?: string | null): boolean {
  return TEXT_FILE.test(filename) || retrievalMode === "full_document";
}

const MARKDOWN: Components = {
  h1: ({ className, ...p }) => <h1 className={cn("mb-3 mt-6 text-2xl font-bold first:mt-0", className)} {...p} />,
  h2: ({ className, ...p }) => <h2 className={cn("mb-2 mt-6 border-b border-border pb-1 text-xl font-semibold first:mt-0", className)} {...p} />,
  h3: ({ className, ...p }) => <h3 className={cn("mb-2 mt-5 text-lg font-semibold first:mt-0", className)} {...p} />,
  h4: ({ className, ...p }) => <h4 className={cn("mb-1 mt-4 font-semibold first:mt-0", className)} {...p} />,
  p: ({ className, ...p }) => <p className={cn("my-3 leading-relaxed", className)} {...p} />,
  ul: ({ className, ...p }) => <ul className={cn("my-3 list-disc space-y-1 pl-6 [&.contains-task-list]:list-none [&.contains-task-list]:pl-1", className)} {...p} />,
  ol: ({ className, ...p }) => <ol className={cn("my-3 list-decimal space-y-1 pl-6", className)} {...p} />,
  li: ({ className, ...p }) => <li className={cn("leading-relaxed [&>input]:mr-2", className)} {...p} />,
  a: ({ className, ...p }) => <a className={cn("text-[var(--cta)] underline underline-offset-2", className)} target="_blank" rel="noopener noreferrer" {...p} />,
  blockquote: ({ className, ...p }) => <blockquote className={cn("my-3 border-l-4 border-border pl-4 text-muted-foreground", className)} {...p} />,
  hr: () => <hr className="my-6 border-border" />,
  pre: ({ className, ...p }) => <pre className={cn("my-3 overflow-x-auto rounded-md bg-muted p-3 text-xs [&>code]:bg-transparent [&>code]:p-0", className)} {...p} />,
  code: ({ className, ...p }) => <code className={cn("rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]", className)} {...p} />,
  table: ({ className, ...p }) => (
    <div className="my-3 overflow-x-auto">
      <table className={cn("w-full border-collapse text-sm", className)} {...p} />
    </div>
  ),
  th: ({ className, ...p }) => <th className={cn("border border-border bg-muted/50 px-3 py-1.5 text-left font-medium", className)} {...p} />,
  td: ({ className, ...p }) => <td className={cn("border border-border px-3 py-1.5 align-top", className)} {...p} />,
  img: ({ alt }) => <span className="text-muted-foreground">[image{alt ? `: ${alt}` : ""}]</span>,
};

function PreviewBody({ preview, raw }: { preview: Preview; raw: boolean }) {
  if (raw || preview.format === "text") {
    return <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed">{preview.content}</pre>;
  }
  return (
    <div className="text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN}>
        {preview.content}
      </ReactMarkdown>
    </div>
  );
}

export function FilePreviewButton({ documentUuid, filename }: { documentUuid: string; filename: string }) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [raw, setRaw] = useState(false);

  useEffect(() => {
    if (!open || preview) return;
    let cancelled = false;
    void client.get<{ 200: Preview }, unknown>({ url: `/api/v1/oxee/files/${documentUuid}/preview` }).then((response) => {
      if (cancelled) return;
      if (response.error) setError(detailFromError(response.error, "This document could not be previewed"));
      else setPreview(response.data as Preview);
    });
    return () => {
      cancelled = true;
    };
  }, [open, preview, documentUuid]);

  return (
    <>
      <Button variant="ghost" size="sm" title="Preview" onClick={() => setOpen(true)}>
        <Eye className="h-4 w-4" />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="flex max-h-[85vh] flex-col gap-3 sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="truncate pr-6">{filename}</DialogTitle>
            <DialogDescription>
              {preview?.source === "extracted"
                ? "Text extracted from the document, as the agent reads it."
                : "Content of the file as uploaded."}
              {preview?.truncated ? " Only the first 2 MB are shown." : ""}
            </DialogDescription>
          </DialogHeader>
          {preview?.format === "markdown" && (
            <div className="flex gap-1 text-xs">
              {(["Formatted", "Source"] as const).map((label) => {
                const active = (label === "Source") === raw;
                return (
                  <button
                    key={label}
                    type="button"
                    onClick={() => setRaw(label === "Source")}
                    className={cn("rounded-md border px-2.5 py-1", active ? "border-[var(--cta)] bg-[var(--cta)]/10 font-medium" : "border-border text-muted-foreground")}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
            {error ? (
              <p className="text-sm text-destructive">{error}</p>
            ) : preview ? (
              <PreviewBody preview={preview} raw={raw} />
            ) : (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading…
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
