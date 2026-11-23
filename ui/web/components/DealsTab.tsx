"use client";

import { useCallback, useEffect, useState } from "react";
import { VaelonApi, type Deal, type DealsOverview, type MadeFile } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";
import { money } from "./BillsPanel";

const sums = (t: Record<string, number>) =>
  Object.entries(t)
    .sort()
    .map(([cur, c]) => money(c, cur))
    .join(" + ") || money(0, "EUR");

/** The sales pipeline: deals by stage, the next step of each (Vaelon reminds you on its date), won / lost,
 *  and the invoice of a won deal in one click. */
export default function DealsTab(props: { token: string; t: Strings; onNote: (s: string) => void; onFile: (f: MadeFile) => void }) {
  const { token, t, onNote, onFile } = props;
  const [data, setData] = useState<DealsOverview | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null); // the deal whose details are shown
  const [asking, setAsking] = useState<string | null>(null); // delete being confirmed
  const [form, setForm] = useState({ client: "", title: "", value: "", currency: "EUR", stage: "lead", close: "" });
  const [edit, setEdit] = useState({ next_step: "", next_date: "", note: "" });

  const load = useCallback(async () => {
    try {
      setData(await new VaelonApi(token).deals());
    } catch {
      onNote(t.dealsFail);
    }
  }, [token, onNote, t.dealsFail]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (body: Record<string, unknown>, okNote: string) => {
    setBusy(true);
    let ok = false;
    try {
      const r = await new VaelonApi(token).dealsAct(body);
      ok = r.ok;
      onNote(r.ok ? r.text || okNote : r.error || t.dealsFail);
      if (r.ok && r.path) onFile({ path: r.path, name: r.path.split(/[\\/]/).pop() || r.path, kb: r.kb ?? 1 });
      await load();
    } catch {
      onNote(t.dealsFail);
    }
    setAsking(null);
    setBusy(false);
    return ok;
  };

  const show = (d: Deal) => {
    if (open === d.id) return setOpen(null);
    setOpen(d.id);
    setEdit({ next_step: d.next_step, next_date: d.next_date, note: "" });
  };

  if (!data) return <p className="muted scan">{t.loading}</p>;
  const tot = data.totals;
  const stageName = (s: string) => t.dealStages[s as keyof typeof t.dealStages] ?? s;

  const row = (d: Deal) => (
    <div key={d.id} className={`dealwrap ${d.stage}`}>
      <div className={`billrow ${d.late ? "late" : ""} ${d.stage === "lost" ? "void" : ""}`}>
        <button type="button" className="dealname" onClick={() => show(d)} aria-expanded={open === d.id}
          aria-label={`${d.client}${d.title ? `, ${d.title}` : ""}: ${t.dealDetails}`}>
          <b>{d.client}</b>
          {d.title && <em> · {d.title}</em>}
          {d.next_date && d.stage !== "won" && d.stage !== "lost" && (
            <span className={`dealnext ${d.late ? "late" : ""}`}> · {d.next_step || t.dealFollow} {d.next_date.slice(8)}.{d.next_date.slice(5, 7)}</span>
          )}
          {d.stale && <span className="dealnext late"> · {t.dealStale}</span>}
        </button>
        <span className="billsum">{d.value ? money(d.value, d.currency) : "—"}</span>
        <select aria-label={`${t.dealStage}: ${d.client}`} className="dealstage" value={d.stage} disabled={busy}
          onChange={(e) => void act({ action: "update", id: d.id, stage: e.target.value }, t.dealSaved)}>
          {data.stages.map((s) => <option key={s} value={s}>{stageName(s)} {s !== "won" && s !== "lost" ? `${data.chance[s]}%` : ""}</option>)}
        </select>
        {d.stage === "won" && !d.invoice && (
          <button type="button" className="btn ghost" disabled={busy || !d.value} title={d.value ? t.dealInvoiceHint : t.dealNoValue}
            onClick={() => void act({ action: "invoice", id: d.id }, t.invMade)}>{t.dealInvoice}</button>
        )}
        {d.invoice && <span className="muted small mono">no. {d.invoice}</span>}
      </div>
      {open === d.id && (
        <div className="dealmore">
          {d.stage !== "won" && d.stage !== "lost" && (
            <form className="calrow" onSubmit={(e) => {
              e.preventDefault();
              void act({ action: "update", id: d.id, next_step: edit.next_step, next_date: edit.next_date }, t.dealSaved);
            }}>
              <input aria-label={t.dealNextStep} placeholder={t.dealNextStep} maxLength={200} value={edit.next_step}
                onChange={(e) => setEdit({ ...edit, next_step: e.target.value })} />
              <input type="date" aria-label={t.dealNextDate} value={edit.next_date} onChange={(e) => setEdit({ ...edit, next_date: e.target.value })} />
              <button type="submit" className="btn ghost" disabled={busy}>{t.save}</button>
            </form>
          )}
          <form className="calrow" onSubmit={(e) => {
            e.preventDefault();
            if (!edit.note.trim()) return;
            void act({ action: "note", id: d.id, text: edit.note }, t.dealNoted).then((ok) => ok && setEdit({ ...edit, note: "" }));
          }}>
            <input aria-label={t.dealNote} placeholder={t.dealNote} maxLength={500} value={edit.note}
              onChange={(e) => setEdit({ ...edit, note: e.target.value })} />
            <button type="submit" className="btn ghost" disabled={busy || !edit.note.trim()}>{t.calAdd}</button>
          </form>
          {d.notes.length > 0 && (
            <ul className="dealnotes">
              {[...d.notes].reverse().map((n, i) => <li key={i}><span className="mono">{n.date.slice(8)}.{n.date.slice(5, 7)}</span> {n.text}</li>)}
            </ul>
          )}
          <p className="muted small">
            {d.close && <>{t.dealClose}: {d.close} · </>}
            {d.contact && <>{d.contact} · </>}
            {asking === d.id ? (
              <span className="chatask">
                <button type="button" className="btn" disabled={busy} onClick={() => void act({ action: "delete", id: d.id }, t.dealDeleted)}>{t.chatDelete}</button>
                <button type="button" className="btn ghost" onClick={() => setAsking(null)}>{t.chatKeep}</button>
              </span>
            ) : (
              <button type="button" className="btn ghost" onClick={() => setAsking(d.id)}>{t.dealDelete}</button>
            )}
          </p>
        </div>
      )}
    </div>
  );

  const openDeals = data.deals.filter((d) => d.stage !== "won" && d.stage !== "lost");
  const closed = data.deals.filter((d) => d.stage === "won" || d.stage === "lost");
  return (
    <>
      <p className="billtotal">
        {t.dealOpen}: <b>{tot.count}</b> · <b>{sums(tot.open)}</b> · {t.dealExpected}: <b>{sums(tot.expected)}</b>
        <br />
        {t.dealWonYear.replace("{y}", String(tot.year))}: <b>{sums(tot.won_year)}</b> ({tot.won} / {tot.won + tot.lost})
      </p>
      <form className="calform" onSubmit={(e) => {
        e.preventDefault();
        if (!form.client.trim()) return;
        void act({ action: "add", ...form }, t.dealAdded).then((ok) => ok && setForm({ ...form, client: "", title: "", value: "", close: "" }));
      }}>
        <div className="calrow">
          <input aria-label={t.dealClient} placeholder={t.dealClient} maxLength={120} value={form.client}
            onChange={(e) => setForm({ ...form, client: e.target.value })} />
          <input aria-label={t.dealTitle} placeholder={t.dealTitle} maxLength={200} value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </div>
        <div className="calrow">
          <input aria-label={t.dealValue} placeholder={t.dealValue} inputMode="decimal" className="narrow" value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })} />
          <select aria-label={t.billCurrency} className="narrow" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
            {data.currencies.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select aria-label={t.dealStage} value={form.stage} onChange={(e) => setForm({ ...form, stage: e.target.value })}>
            {data.stages.map((s) => <option key={s} value={s}>{stageName(s)}</option>)}
          </select>
          <input type="date" aria-label={t.dealClose} title={t.dealClose} value={form.close} onChange={(e) => setForm({ ...form, close: e.target.value })} />
          <button type="submit" className="btn" disabled={busy || !form.client.trim()}>{t.calAdd}</button>
        </div>
      </form>
      <p className="muted small">{t.dealSay}</p>
      {data.deals.length === 0 && <p className="muted">{t.dealNone}</p>}
      {openDeals.map(row)}
      {closed.length > 0 && <h4 className="budhead">{t.dealClosed}</h4>}
      {closed.map(row)}
    </>
  );
}
