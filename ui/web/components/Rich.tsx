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
      {text.replace(/<br\s*\/?>/gi, " · ")}
    </ReactMarkdown>
  );
}
