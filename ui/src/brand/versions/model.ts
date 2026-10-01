// Agent versions page: API shapes (GET /api/v1/oxee/workflows/{id}/versions…)
// and the small pure helpers the page renders with.

export interface Person {
  id: number | null;
  email: string | null;
}

export interface AiSummary {
  headline: string;
  points: string[];
  risks: string[];
  model: string | null;
  at: string;
  language?: string;
}

export interface VersionHeader {
  id: number;
  version_number: number;
  status: "draft" | "published" | "archived" | string;
  created_at: string;
  published_at: string | null;
  origin: string | null;
  created_by: Person | null;
  last_edited_at: string | null;
  last_edited_by: Person | null;
  edit_count: number;
  published_by: Person | null;
  restored_from: number | null;
  note: string | null;
  api_key_prefix: string | null;
  calls: number | null;
}

export interface Counts {
  added: number;
  removed: number;
  changed: number;
}

export interface VersionItem extends VersionHeader {
  base_version_number: number | null;
  counts: Counts;
  bullets: string[];
  bullet_count: number;
  ai_summary?: AiSummary;
}

export interface TextOp {
  op: "equal" | "insert" | "delete";
  text: string;
}

export interface FieldChange {
  field: string;
  label: string;
  before: unknown;
  after: unknown;
  text_diff?: TextOp[];
}

export interface Change {
  scope: "node" | "edge" | "config" | "variables";
  kind: "added" | "removed" | "changed";
  id: string;
  title: string;
  node_type?: string;
  fields: FieldChange[];
}

export interface VersionDiff {
  target: VersionHeader;
  base: VersionHeader | null;
  changes: Change[];
  bullets: string[];
  counts: Counts;
  identical: boolean;
  ai_summary: AiSummary | null;
}

export const ORIGIN_LABEL: Record<string, string> = {
  editor: "Editor",
  api: "API key",
  mcp: "MCP agent",
  restore: "Restore",
  fix: "Automatic fix",
  internal: "System",
};

/** "API key dgr__bMZ", "Restore of v1", "Editor"; null when unknown (versions made before tracking). */
export function originLabel(v: Pick<VersionHeader, "origin" | "api_key_prefix" | "restored_from">): string | null {
  if (!v.origin) return null;
  if (v.origin === "restore" && v.restored_from != null) return `Restore of v${v.restored_from}`;
  const base = ORIGIN_LABEL[v.origin] ?? v.origin;
  return v.api_key_prefix && (v.origin === "api" || v.origin === "mcp") ? `${base} ${v.api_key_prefix}…` : base;
}

export function personLabel(p: Person | null | undefined): string | null {
  if (!p) return null;
  return p.email ?? (p.id != null ? `user #${p.id}` : null);
}

/** Short display of a before / after value. */
export function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "on" : "off";
  if (typeof v === "number") return String(v);
  if (typeof v === "string") return v;
  return JSON.stringify(v, null, 1).replace(/\s*\n\s*/g, " ");
}

export function countsLabel(c: Counts): string {
  const parts = [];
  if (c.added) parts.push(`+${c.added}`);
  if (c.removed) parts.push(`−${c.removed}`);
  if (c.changed) parts.push(`~${c.changed}`);
  return parts.join(" ");
}

export const SCOPE_LABEL: Record<Change["scope"], string> = {
  node: "Node",
  edge: "Transition",
  config: "Setting",
  variables: "Variables",
};

/** Language for the AI summary from the browser locale. */
export function summaryLanguage(locale: string | undefined): string {
  const lang = (locale ?? "en").slice(0, 2).toLowerCase();
  return { fr: "French", de: "German", es: "Spanish", it: "Italian", pt: "Portuguese", nl: "Dutch" }[lang] ?? "English";
}
