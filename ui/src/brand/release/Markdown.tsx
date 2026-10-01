import { Fragment, type ReactNode } from "react";

// Minimal Markdown for release notes (GitHub release bodies, brand/CHANGELOG.md):
// headings, bullet lists (with wrapped lines), paragraphs, rules, fenced code,
// `code`, **bold**, [links](https://...). Builds React elements, never HTML.

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "paragraph"; text: string }
  | { kind: "code"; text: string }
  | { kind: "rule" };

export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.trim().startsWith("```")) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) body.push(lines[i++]);
      i++;
      blocks.push({ kind: "code", text: body.join("\n") });
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2].trim() });
      i++;
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      blocks.push({ kind: "rule" });
      i++;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && lines[i].trim()) {
        if (/^\s*[-*]\s+/.test(lines[i])) items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        else if (items.length) items[items.length - 1] += ` ${lines[i].trim()}`;
        i++;
      }
      blocks.push({ kind: "list", items });
      continue;
    }
    const text: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*[-*]\s|```)/.test(lines[i])) text.push(lines[i++].trim());
    blocks.push({ kind: "paragraph", text: text.join(" ") });
  }
  return blocks;
}

const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;

export function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    const token = m[0];
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    if (token.startsWith("`")) {
      out.push(<code key={at} className="rounded bg-muted px-1 py-0.5 text-[0.85em]">{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      out.push(<strong key={at}>{token.slice(2, -2)}</strong>);
    } else {
      const label = token.slice(1, token.indexOf("]("));
      out.push(
        <a key={at} href={m[2]} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
          {label}
        </a>,
      );
    }
    last = at + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ source }: { source: string }) {
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {parseBlocks(source).map((b, i) => {
        switch (b.kind) {
          case "heading":
            return (
              <p key={i} className={b.level <= 2 ? "pt-1 font-semibold" : "pt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground"}>
                {renderInline(b.text)}
              </p>
            );
          case "list":
            return (
              <ul key={i} className="list-disc space-y-1 pl-5">
                {b.items.map((item, j) => <li key={j}>{renderInline(item)}</li>)}
              </ul>
            );
          case "code":
            return <pre key={i} className="overflow-x-auto rounded-md bg-muted p-2 text-xs"><code>{b.text}</code></pre>;
          case "rule":
            return <hr key={i} className="border-border" />;
          default:
            return <p key={i}><Fragment>{renderInline(b.text)}</Fragment></p>;
        }
      })}
    </div>
  );
}
