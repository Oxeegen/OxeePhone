"use client";

import { ArrowRightLeft, CircleDot, Settings2, Variable } from "lucide-react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { type Change, type FieldChange, formatValue, SCOPE_LABEL, type TextOp } from "./model";

// Field-level diff views shared by the versions page and the fix cards.

const KIND_STYLE: Record<Change["kind"], string> = {
  added: "text-emerald-700 dark:text-emerald-300",
  removed: "text-rose-700 dark:text-rose-300",
  changed: "text-sky-700 dark:text-sky-300",
};

const SCOPE_ICON: Record<Change["scope"], typeof CircleDot> = {
  node: CircleDot,
  edge: ArrowRightLeft,
  config: Settings2,
  variables: Variable,
};

export function TextDiff({ ops }: { ops: TextOp[] }) {
  return (
    <p className="whitespace-pre-wrap rounded-md border border-border/70 bg-muted/30 p-2.5 text-sm leading-relaxed">
      {ops.map((op, i) =>
        op.op === "equal" ? (
          <span key={i}>{op.text}</span>
        ) : op.op === "insert" ? (
          <ins key={i} className="rounded-sm bg-emerald-500/20 text-emerald-900 no-underline dark:text-emerald-200">
            {op.text}
          </ins>
        ) : (
          <del key={i} className="rounded-sm bg-rose-500/15 text-rose-900 dark:text-rose-200">
            {op.text}
          </del>
        ),
      )}
    </p>
  );
}

function FieldRow({ field, kind }: { field: FieldChange; kind: Change["kind"] }) {
  const single = kind === "added" ? field.after : kind === "removed" ? field.before : undefined;
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-muted-foreground">{field.label}</p>
      {kind !== "changed" ? (
        <p className="whitespace-pre-wrap text-sm">{formatValue(single)}</p>
      ) : field.text_diff ? (
        <TextDiff ops={field.text_diff} />
      ) : (
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <span className="rounded bg-rose-500/10 px-1.5 py-0.5 line-through decoration-rose-500/60">{formatValue(field.before)}</span>
          <span className="text-muted-foreground">→</span>
          <span className="rounded bg-emerald-500/15 px-1.5 py-0.5">{formatValue(field.after)}</span>
        </p>
      )}
    </div>
  );
}

export function ChangeCard({ change }: { change: Change }) {
  const Icon = SCOPE_ICON[change.scope];
  return (
    <Card className="gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Icon className="h-4 w-4 text-muted-foreground" />
        <span className="text-xs text-muted-foreground">{SCOPE_LABEL[change.scope]}</span>
        <span className="font-medium">{change.title}</span>
        <span className={cn("ml-auto text-xs font-medium capitalize", KIND_STYLE[change.kind])}>{change.kind}</span>
      </div>
      <div className="space-y-3">
        {change.fields.map((f) => (
          <FieldRow key={f.field} field={f} kind={change.kind} />
        ))}
      </div>
    </Card>
  );
}

