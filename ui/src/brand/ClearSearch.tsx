"use client";

import { X } from "lucide-react";

/** Clears a search field (placed inside its relative wrapper, on the right). */
export function ClearSearch({ value, onClear }: { value: string; onClear: () => void }) {
  if (!value) return null;
  return (
    <button
      type="button"
      onClick={onClear}
      title="Clear the search"
      aria-label="Clear the search"
      className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      <X className="h-4 w-4" />
    </button>
  );
}
