"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Vaelon's answers as Markdown (tables, code, lists). Raw HTML is never rendered; links open outside the app. */
export default function Rich({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{ a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}
    >
      {/* quick answers (bills, calendar, budget, bank import) write one "• item" per line; in Markdown single lines
          run together, so those lines become a real list, and a heading line right after a list (the calendar's next
          day) gets a blank line so it does not glue onto the last item */}
      {text
        .replace(/<br\s*\/?>/gi, " · ")
        .replace(/^([ \t]*)• /gm, "$1- ")
        .replace(/^([ \t]*- .*)\n(?![ \t]*- |[ \t]*\n|$)/gm, "$1\n\n")}
    </ReactMarkdown>
  );
}
