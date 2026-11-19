"use client";

import { useEffect, useState } from "react";
import { VaelonApi, type ChatMessage, type ChatRow } from "@/lib/vaelonApi";
import { STRINGS, type Lang } from "@/lib/i18n";

function when(ts: number, t: (typeof STRINGS)["en"]): string {
  const min = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
  if (min < 1) return t.chatNow;
  if (min < 60) return `${min} ${t.chatMin}`;
  if (min < 60 * 24) return `${Math.round(min / 60)} ${t.chatHours}`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Your conversations: start a new one, go back to an old one, rename or delete. Stored encrypted on this PC. */
export default function ChatsPanel(props: { token: string; lang: Lang; onClose: () => void; onNote: (s: string) => void;
  onShow: (messages: ChatMessage[], fresh: boolean) => void }) {
  const { token, lang, onClose, onNote, onShow } = props;
  const t = STRINGS[lang];
  const [rows, setRows] = useState<ChatRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);

  useEffect(() => {
    new VaelonApi(token)
      .chats()
      .then(setRows)
      .catch(() => onNote(t.chatsFail));
  }, [token, onNote, t.chatsFail]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const act = async (action: "new" | "open" | "delete" | "rename", id?: string, title?: string) => {
    setBusy(true);
    try {
      const was = rows?.find((r) => r.current)?.id;
      const r = await new VaelonApi(token).chatAction(action, id, title);
      if (!r.ok) onNote(r.error === "wait for the running tasks to finish first" ? t.chatBusy : r.error || t.chatsFail);
      else {
        setRows(r.chats);
        if (r.current !== was || action === "new") {
          onShow(r.messages, action === "new");
          if (action !== "delete") onClose();
        }
      }
    } catch {
      onNote(t.chatsFail);
    }
    setEditing(null);
    setConfirm(null);
    setBusy(false);
  };

  return (
    <div className="panel-wrap" onClick={onClose}>
      <aside className="panel chats" role="dialog" aria-label={t.chats} onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <span className="panel-title">{t.chats}</span>
          <span className="panel-sub">{rows ? `${rows.length}` : ""}</span>
          <button className="x" onClick={onClose} aria-label={t.close}>
            ✕
          </button>
        </div>
        <div className="panel-body">
          <button type="button" className="btn wide" disabled={busy} onClick={() => void act("new")}>
            + {t.chatNew}
          </button>
          {!rows && <p className="muted scan">{t.loading}</p>}
          {rows?.map((c) => (
            <div key={c.id} className={`chatrow ${c.current ? "on" : ""}`}>
              {editing === c.id ? (
                <form
                  className="keyform"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (draft.trim()) void act("rename", c.id, draft);
                  }}
                >
                  <input autoFocus maxLength={60} aria-label={t.chatRename} value={draft} onChange={(e) => setDraft(e.target.value)} />
                  <button type="submit" className="btn" disabled={busy || !draft.trim()}>
                    {t.save}
                  </button>
                </form>
              ) : (
                <button type="button" className="chatopen" disabled={busy} onClick={() => (c.current ? onClose() : void act("open", c.id))}>
                  <b>{c.title || t.chatUntitled}</b>
                  <em>
                    {c.current ? `${t.chatOpen} · ` : ""}
                    {c.count} {t.chatMsgs} · {when(c.updated, t)}
                  </em>
                </button>
              )}
              {confirm === c.id ? (
                <span className="chatask">
                  <button type="button" className="btn" disabled={busy} onClick={() => void act("delete", c.id)}>
                    {t.chatDelete}
                  </button>
                  <button type="button" className="btn ghost" onClick={() => setConfirm(null)}>
                    {t.chatKeep}
                  </button>
                </span>
              ) : (
                editing !== c.id && (
                  <span className="chattools">
                    <button type="button" className="x" title={t.chatRename} aria-label={`${t.chatRename}: ${c.title || t.chatUntitled}`}
                      onClick={() => {
                        setDraft(c.title);
                        setEditing(c.id);
                      }}
                    >
                      ✎
                    </button>
                    <button type="button" className="x" title={t.chatDelete} aria-label={`${t.chatDelete}: ${c.title || t.chatUntitled}`}
                      onClick={() => setConfirm(c.id)}>
                      🗑
                    </button>
                  </span>
                )
              )}
            </div>
          ))}
          <p className="muted small">{t.chatsNote}</p>
        </div>
      </aside>
    </div>
  );
}
