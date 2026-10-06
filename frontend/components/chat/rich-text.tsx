// Renders the assistant's light Markdown (paragraphs, bullet/numbered lists, **bold**,
// `code`) as React elements. No HTML is ever injected.

import { Fragment, type ReactNode } from "react";

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={i} className="rounded bg-muted px-1 py-0.5 text-[0.9em]">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <Fragment key={i}>{part.replace(/\*([^*]+)\*/g, "$1")}</Fragment>;
  });
}

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "list"; ordered: boolean; items: { level: number; text: string }[] };

const LIST_ITEM = /^(\s*)([-*•]|\d+[.)])\s+(.*)$/;

function blocks(text: string): Block[] {
  const out: Block[] = [];
  for (const line of text.split("\n")) {
    const item = LIST_ITEM.exec(line);
    const last = out[out.length - 1];
    if (item) {
      const entry = { level: Math.min(Math.floor(item[1].length / 2), 3), text: item[3] };
      if (last?.kind === "list") last.items.push(entry);
      else out.push({ kind: "list", ordered: /\d/.test(item[2]), items: [entry] });
    } else if (!line.trim()) {
      out.push({ kind: "p", lines: [] });
    } else if (last?.kind === "p") {
      last.lines.push(line);
    } else {
      out.push({ kind: "p", lines: [line] });
    }
  }
  return out.filter((b) => b.kind === "list" || b.lines.length > 0);
}

export function RichText({ text }: { text: string }) {
  return (
    <div className="grid gap-2 leading-relaxed">
      {blocks(text).map((block, i) =>
        block.kind === "p" ? (
          <p key={i}>
            {block.lines.map((line, j) => (
              <Fragment key={j}>
                {j > 0 && <br />}
                {inline(line)}
              </Fragment>
            ))}
          </p>
        ) : (
          (() => {
            const List = block.ordered ? "ol" : "ul";
            return (
              <List key={i} className={block.ordered ? "list-decimal pl-5" : "list-disc pl-5"}>
                {block.items.map((item, j) => (
                  <li key={j} style={{ marginLeft: `${item.level}rem` }}>
                    {inline(item.text)}
                  </li>
                ))}
              </List>
            );
          })()
        ),
      )}
    </div>
  );
}
