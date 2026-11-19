"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { HELP } from "@/lib/help";
import { STRINGS, type Lang } from "@/lib/i18n";
import { VaelonApi, type MadeFile } from "@/lib/vaelonApi";
import FileCard from "./FileCard";
import Rich from "./Rich";

const KINDS = ["idea", "problem", "question", "praise"] as const;

/** Help and feedback: every part of Vaelon explained in one place, plus a note to the author (saved as a file). */
export default function HelpPanel(props: { token: string; lang: Lang; section?: string; owner: boolean; onClose: () => void;
  onNote: (s: string) => void }) {
  const { token, lang, section, owner, onClose, onNote } = props;
  const t = STRINGS[lang];
  const [open, setOpen] = useState(section && HELP.some((h) => h.id === section) ? section : "start");
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<(typeof KINDS)[number]>("idea");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<MadeFile | null>(null);
  const [canMail, setCanMail] = useState(false);
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!owner) return;
    new VaelonApi(token).settings().then((s) => setCanMail(!!s.feedback_mail)).catch(() => undefined);
  }, [token, owner]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    body.current?.scrollTo({ top: 0 });
  }, [open]);

  const ql = q.trim().toLowerCase();
  const found = useMemo(
    () => (ql ? HELP.filter((h) => (h.title + " " + h.body).toLowerCase().includes(ql)) : []),
    [ql],
  );
  const shown = ql ? found : HELP.filter((h) => h.id === open);

  const send = async (mail: boolean) => {
    setBusy(true);
    try {
      const r = await new VaelonApi(token).feedback(kind, text, mail);
      if (r.ok && r.path) {
        const name = r.path.split(/[\\/]/).pop() ?? r.path;
        setSaved({ path: r.path, name, kb: 1 });
        setText("");
        onNote(r.error || t.fbSaved);
      } else onNote(r.error || t.fbFail);
    } catch {
      onNote(t.fbFail);
    }
    setBusy(false);
  };

  return (
    <div className="panel-wrap" onClick={onClose}>
      <aside className="panel help" role="dialog" aria-label={t.help} onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <span className="panel-title">{t.help}</span>
          <span className="panel-sub">{t.helpSub}</span>
          <button className="x" onClick={onClose} aria-label={t.close}>
            ✕
          </button>
        </div>
        <input className="search" placeholder={t.helpSearch} value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="helpgrid">
          <nav className="helpnav" aria-label={t.help}>
            {HELP.map((h) => (
              <button key={h.id} type="button" className={!ql && open === h.id ? "on" : ""} onClick={() => {
                setQ("");
                setOpen(h.id);
              }}>
                {h.title}
              </button>
            ))}
            {owner && (
              <button type="button" className={`fb ${!ql && open === "feedback" ? "on" : ""}`} onClick={() => {
                setQ("");
                setOpen("feedback");
              }}>
                ✉ {t.feedback}
              </button>
            )}
          </nav>
          <div className="panel-body helpbody" ref={body}>
            {ql && !found.length && <p className="muted">{t.helpNothing}</p>}
            {shown.map((h) => (
              <section key={h.id} className="helptext">
                <h3>{h.title}</h3>
                <Rich text={h.body} />
              </section>
            ))}
            {!ql && open === "feedback" && owner && (
              <section className="helptext">
                <h3>{t.feedback}</h3>
                <p>{t.fbIntro}</p>
                <div className="pills">
                  {KINDS.map((k) => (
                    <button key={k} type="button" className={`pill ${kind === k ? "on" : ""}`} onClick={() => setKind(k)}>
                      {t.fbKinds[k]}
                    </button>
                  ))}
                </div>
                <textarea className="fbtext" maxLength={5000} rows={7} value={text} placeholder={t.fbPlaceholder}
                  onChange={(e) => setText(e.target.value)} />
                <div className="keyform">
                  <span className="muted small grow">{text.length} / 5000</span>
                  <button type="button" className={canMail ? "btn ghost" : "btn"} disabled={busy || !text.trim()} onClick={() => void send(false)}>
                    {t.fbSave}
                  </button>
                  {canMail && (
                    <button type="button" className="btn" disabled={busy || !text.trim()} onClick={() => void send(true)}>
                      {t.fbMail}
                    </button>
                  )}
                </div>
                <p className="muted small">{t.fbPrivacy}</p>
                {saved && <FileCard file={saved} token={token} t={t} onNote={onNote} />}
              </section>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
