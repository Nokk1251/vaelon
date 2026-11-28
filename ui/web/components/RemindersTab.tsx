"use client";

import { useCallback, useEffect, useState } from "react";
import { VaelonApi, type PayReminder, type PayRemindersOverview } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";
import { money } from "./BillsPanel";

type Edit = { to: string; subject: string; body: string };
const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

/** Money > Reminders (issue #44): when an invoice is overdue Vaelon writes a polite reminder DRAFT (first friendly,
 *  then firmer). Nothing is sent by itself: the user checks it, then sends it (asked here every time) or copies it. */
export default function RemindersTab(props: { token: string; t: Strings; onNote: (s: string) => void }) {
  const { token, t, onNote } = props;
  const [data, setData] = useState<PayRemindersOverview | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [asking, setAsking] = useState<string | null>(null);
  const [days, setDays] = useState<{ first: string; second: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const o = await new VaelonApi(token).payReminders();
      setData(o);
      setDays((d) => d ?? { first: String(o.settings.first), second: String(o.settings.second) });
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [token]);

  useEffect(() => {
    void load();
    // what the reminder thread made while the tab is open shows up by itself (not while the page is hidden)
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const act = async (body: Record<string, unknown>, okNote: string) => {
    setBusy(true);
    let ok = false;
    try {
      const r = await new VaelonApi(token).payRemindersAct(body);
      ok = r.ok;
      onNote(r.ok ? okNote.replace("{to}", r.to || "") : r.error || t.remActFail);
      await load();
    } catch {
      onNote(t.remActFail);
    }
    setAsking(null);
    setBusy(false);
    return ok;
  };

  const copy = async (d: PayReminder) => {
    const text = `${d.subject}\n\n${d.body}`;
    try {
      await navigator.clipboard.writeText(text);
      onNote(t.remCopied);
    } catch {
      // no clipboard here (some windows refuse it): select the text, so Ctrl+C works, and try the older way once
      const box = document.getElementById(`remtext-${d.id}`) as HTMLTextAreaElement | null;
      box?.focus();
      box?.select();
      let ok = false;
      try {
        ok = document.execCommand("copy");
      } catch {
        ok = false;
      }
      onNote(ok ? t.remCopiedBody : t.remCopyFail);
    }
  };

  if (!data) return <p className="muted small" role="status">{failed ? t.remFail : t.loading}</p>;
  const shown = (d: PayReminder): Edit => edits[d.id] ?? { to: d.to, subject: d.subject, body: d.body };
  const dirty = (d: PayReminder) => {
    const e = edits[d.id];
    return !!e && (e.to !== d.to || e.subject !== d.subject || e.body !== d.body);
  };
  const change = (d: PayReminder, part: Partial<Edit>) => setEdits({ ...edits, [d.id]: { ...shown(d), ...part } });
  const save = async (d: PayReminder) => {
    if (await act({ action: "edit", id: d.id, ...shown(d) }, t.remSaved)) {
      const rest = { ...edits };
      delete rest[d.id];
      setEdits(rest);
    }
  };

  const card = (d: PayReminder) => {
    const e = shown(d);
    return (
      <div key={d.id} className="remcard">
        <p className="remhead">
          <b>{d.stage === 2 ? t.remFirmer : t.remFriendly}</b> · <span className="mono">{t.remInvoice} {d.number}</span> · {d.client} ·{" "}
          {money(d.total, d.currency)} · <span className="late">{t.remLate.replace("{n}", String(d.late))}</span>
          {d.demo && <em> · {t.remDemo}</em>}
        </p>
        <div className="calform">
          <div className="calrow">
            <input aria-label={t.remTo} placeholder={t.remToEmpty} type="email" maxLength={120} value={e.to} readOnly={!data.may_write}
              onChange={(ev) => change(d, { to: ev.target.value })} />
          </div>
          <div className="calrow">
            <input aria-label={t.remSubject} maxLength={200} value={e.subject} readOnly={!data.may_write}
              onChange={(ev) => change(d, { subject: ev.target.value })} />
          </div>
          <textarea id={`remtext-${d.id}`} aria-label={t.remText} className="remtext" rows={10} maxLength={6000} value={e.body} readOnly={!data.may_write}
            onChange={(ev) => change(d, { body: ev.target.value })} />
        </div>
        {asking === d.id ? (
          <div className="chatask remask" role="alertdialog" aria-label={t.remSendAsk}>
            <span className="small">{t.remSendAsk.replace("{to}", d.to)}</span>
            <button type="button" className="btn" disabled={busy}
              onClick={() => void act({ action: "send", id: d.id, confirm: { to: d.to, subject: d.subject, body: d.body } }, t.remSent)}>
              {t.remSendYes}
            </button>
            <button type="button" className="btn ghost" onClick={() => setAsking(null)}>{t.chatKeep}</button>
          </div>
        ) : (
          <div className="billacts remacts">
            {dirty(d) && data.may_write && (
              <button type="button" className="btn" disabled={busy} onClick={() => void save(d)}>{t.remSave}</button>
            )}
            <button type="button" className="btn ghost" onClick={() => void copy(d)}>{t.remCopy}</button>
            {data.may_send && (
              <button type="button" className="btn ghost" disabled={busy || dirty(d) || !d.to || !data.mail_ready || d.demo}
                title={dirty(d) ? t.remSaveFirst : !d.to ? t.remNeedTo : !data.mail_ready ? t.remNoMail : d.demo ? t.remDemo : t.remSendHint}
                onClick={() => setAsking(d.id)}>
                {t.remSend}
              </button>
            )}
            {data.may_write && (
              <button type="button" className="btn ghost" disabled={busy} onClick={() => void act({ action: "dismiss", id: d.id }, t.remDismissed)}>
                {t.remDismiss}
              </button>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <>
      <p className="muted small">{t.remIntro}</p>
      {!data.mail_ready && data.drafts.length > 0 && <p className="muted small">{t.remNoMail}</p>}
      {data.may_write && days && (
        <form className="calform budlimit" onSubmit={(e) => {
          e.preventDefault();
          void act({ action: "settings", on: data.settings.on, first: days.first, second: days.second }, t.remSettingsSaved);
        }}>
          <div className="calrow">
            <label className="small">
              <input type="checkbox" checked={data.settings.on}
                onChange={(e) => void act({ action: "settings", on: e.target.checked }, e.target.checked ? t.remOn : t.remOff)} />{" "}
              {t.remAuto}
            </label>
            <input aria-label={t.remFirstDays} title={t.remFirstDays} inputMode="numeric" className="tiny" value={days.first}
              onChange={(e) => setDays({ ...days, first: e.target.value.replace(/\D/g, "") })} />
            <span className="small">{t.remThen}</span>
            <input aria-label={t.remSecondDays} title={t.remSecondDays} inputMode="numeric" className="tiny" value={days.second}
              onChange={(e) => setDays({ ...days, second: e.target.value.replace(/\D/g, "") })} />
            <span className="small">{t.remDaysLate}</span>
            <button type="submit" className="btn ghost" disabled={busy}>{t.remSaveDays}</button>
          </div>
        </form>
      )}
      {data.drafts.length === 0 ? <p className="muted">{t.remNone}</p> : data.drafts.map(card)}
      {data.overdue.length > 0 && (
        <>
          <h4 className="remsub">{t.remOverdue}</h4>
          {data.overdue.map((i) => (
            <div key={i.id} className="billrow late">
              <span className="billwho"><b className="mono">{i.number}</b> {i.client}</span>
              <span className="billsum">{money(i.total, i.currency)}</span>
              <span className="billwhen">
                {t.remLate.replace("{n}", String(i.late))}
                {i.reminded && <span className="muted"> · {t.remReminded.replace("{d}", day(i.reminded))}</span>}
              </span>
              {data.may_write && i.sent_stage < 2 && (
                <span className="billacts">
                  <button type="button" className="btn ghost" disabled={busy} onClick={() => void act({ action: "draft", invoice: i.id }, t.remDrafted)}>
                    {i.stage >= 1 ? t.remWriteFirmer : t.remWrite}
                  </button>
                </span>
              )}
            </div>
          ))}
        </>
      )}
      {data.sent.length > 0 && (
        <>
          <h4 className="remsub">{t.remSentList}</h4>
          {data.sent.map((s) => (
            <p key={s.id} className="small muted">
              {day(s.sent_on)} · <span className="mono">{t.remInvoice} {s.number}</span> · {s.client} → {s.to}
            </p>
          ))}
        </>
      )}
    </>
  );
}
