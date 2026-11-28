"use client";

import { useCallback, useEffect, useState } from "react";
import { VaelonApi, readNumber, type RecurringOverview, type RecurringPlan } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";
import { money } from "./BillsPanel";

type Line = { desc: string; qty: string; price: string };
const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

/** Money > Recurring (issue #44): invoices that repeat (a retainer, rent). On its day Vaelon issues the invoice in the
 *  normal unbroken numbering and makes its PDF - it never sends it. */
export default function RecurringTab(props: { token: string; t: Strings; onNote: (s: string) => void; onBusiness: () => void;
  onMade: () => void }) {
  const { token, t, onNote } = props;
  const [data, setData] = useState<RecurringOverview | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState<string | null>(null);
  const blank = { name: "", email: "", address: "", company_id: "", vat_id: "" };
  const [client, setClient] = useState(blank);
  const [lines, setLines] = useState<Line[]>([{ desc: "", qty: "1", price: "" }]);
  const [form, setForm] = useState({ every: "monthly", day: "", start: "", vat: "", due: 14, lang: "en" as "en" | "bg", notes: "" });

  const load = useCallback(async () => {
    try {
      setData(await new VaelonApi(token).recurring());
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
      const r = await new VaelonApi(token).recurringAct(body);
      ok = r.ok;
      if (!r.ok) onNote(r.error || t.recActFail);
      else if (body.action === "run") {
        onNote(r.said && r.said.length ? r.said.join("\n") : t.recNothingDue);
        props.onMade();
      } else onNote(okNote);
      await load();
    } catch {
      onNote(t.recActFail);
    }
    setAsking(null);
    setBusy(false);
    return ok;
  };

  const make = async () => {
    const items = lines.filter((l) => l.desc.trim() && l.price.trim());
    if (!client.name.trim() || !items.length) return;
    const done = await act({ action: "add", client, items, every: form.every, day: form.day, start: form.start, vat_rate: form.vat,
      due_days: String(form.due), lang: form.lang, notes: form.notes }, t.recMade);
    if (done) {
      setClient(blank);
      setLines([{ desc: "", qty: "1", price: "" }]);
      setForm((f) => ({ ...f, day: "", start: "", notes: "" }));
    }
  };

  if (!data) return <p className="muted small" role="status">{failed ? t.recFail : t.loading}</p>;
  const vatShown = form.vat !== "" ? form.vat : data.vat_rate;
  const net = lines.reduce((s, l) => s + (readNumber(l.price) || 0) * (readNumber(l.qty) || 0), 0); // as the core reads them
  const due = data.plans.some((p) => p.active && p.next <= data.today);

  const row = (p: RecurringPlan) => (
    <div key={p.id} className={`billrow quoterow ${p.active ? "" : "void"} ${p.error ? "late" : ""}`}>
      <span className="billwho">
        <b>{p.client}</b> <em>· {t.recEvery[p.every]} · {t.recOnDay.replace("{d}", String(p.day))}</em>
        {p.notes && <span className="small muted"> · {t.recNoteShown}: {p.notes}</span>}
        {p.error && <span className="small"> · {t.recProblem}: {p.error}</span>}
      </span>
      <span className="billsum">{money(p.total, p.currency)}</span>
      <span className="billwhen">
        {p.active ? `${t.recNext} ${day(p.next)}` : t.recPaused}
        {p.made.length > 0 && <span className="muted"> · {t.recLast} {p.made[p.made.length - 1]}</span>}
      </span>
      {asking === p.id ? (
        <span className="chatask">
          <span className="small">{t.recDeleteAsk}</span>
          <button type="button" className="btn" disabled={busy} onClick={() => void act({ action: "delete", id: p.id }, t.recDeleted)}>
            {t.chatDelete}
          </button>
          <button type="button" className="btn ghost" onClick={() => setAsking(null)}>{t.chatKeep}</button>
        </span>
      ) : (
        data.may_write && (
          <span className="billacts">
            <button type="button" className="btn ghost" disabled={busy}
              onClick={() => void act({ action: p.active ? "pause" : "resume", id: p.id }, p.active ? t.recPausedNote : t.recResumed)}>
              {p.active ? t.recPause : t.recResume}
            </button>
            <button type="button" className="x" disabled={busy} aria-label={`${t.chatDelete}: ${p.client}`} onClick={() => setAsking(p.id)}>
              ✕
            </button>
          </span>
        )
      )}
    </div>
  );

  return (
    <>
      <p className="muted small">{t.recIntro}</p>
      {data.may_write && (!data.has_business ? (
        <p className="muted">
          {t.invNeedBiz}{" "}
          <button type="button" className="btn ghost" onClick={props.onBusiness}>{t.billTabs.business}</button>
        </p>
      ) : (
        <form className="calform" onSubmit={(e) => { e.preventDefault(); void make(); }}>
          <div className="calrow">
            <input aria-label={t.invClient} placeholder={t.invClient} maxLength={120} value={client.name}
              onChange={(e) => setClient({ ...client, name: e.target.value })} />
            <input aria-label={t.recEmail} placeholder={t.recEmail} type="email" maxLength={120} value={client.email}
              onChange={(e) => setClient({ ...client, email: e.target.value })} />
          </div>
          <div className="calrow">
            <input aria-label={t.invClientAddr} placeholder={t.invClientAddr} maxLength={200} value={client.address}
              onChange={(e) => setClient({ ...client, address: e.target.value })} />
            <input aria-label={t.recCompanyId} placeholder={t.recCompanyId} maxLength={30} className="narrow" value={client.company_id}
              onChange={(e) => setClient({ ...client, company_id: e.target.value })} />
            <input aria-label={t.recVatId} placeholder={t.recVatId} maxLength={30} className="narrow" value={client.vat_id}
              onChange={(e) => setClient({ ...client, vat_id: e.target.value })} />
          </div>
          {lines.map((l, n) => (
            <div key={n} className="calrow">
              <input aria-label={t.invItem} placeholder={t.invItem} maxLength={200} value={l.desc}
                onChange={(e) => setLines(lines.map((x, k) => (k === n ? { ...x, desc: e.target.value } : x)))} />
              <input aria-label={t.invQty} placeholder={t.invQty} inputMode="decimal" className="tiny" value={l.qty}
                onChange={(e) => setLines(lines.map((x, k) => (k === n ? { ...x, qty: e.target.value } : x)))} />
              <input aria-label={t.invPrice} placeholder={t.invPrice} inputMode="decimal" className="narrow" value={l.price}
                onChange={(e) => setLines(lines.map((x, k) => (k === n ? { ...x, price: e.target.value } : x)))} />
              {lines.length > 1 && (
                <button type="button" className="x" aria-label={t.chatDelete} onClick={() => setLines(lines.filter((_, k) => k !== n))}>✕</button>
              )}
            </div>
          ))}
          <div className="calrow">
            <button type="button" className="btn ghost" onClick={() => setLines([...lines, { desc: "", qty: "1", price: "" }])}>
              {t.invAddLine}
            </button>
            <select aria-label={t.recHowOften} value={form.every} onChange={(e) => setForm({ ...form, every: e.target.value })}>
              {(["monthly", "quarterly", "yearly"] as const).map((k) => <option key={k} value={k}>{t.recEvery[k]}</option>)}
            </select>
            <input aria-label={t.recDay} placeholder={t.recDay} inputMode="numeric" className="tiny" maxLength={2} value={form.day}
              onChange={(e) => setForm({ ...form, day: e.target.value.replace(/\D/g, "") })} />
            <input aria-label={t.invVat} placeholder={`${t.invVat} ${vatShown}`} inputMode="decimal" className="tiny" value={form.vat}
              onChange={(e) => setForm({ ...form, vat: e.target.value })} />
            <select aria-label={t.recDue} value={form.due} onChange={(e) => setForm({ ...form, due: Number(e.target.value) })}>
              {[7, 14, 30, 60].map((d) => <option key={d} value={d}>{t.recDueDays.replace("{n}", String(d))}</option>)}
            </select>
            <select aria-label={t.invLang} value={form.lang} className="lang" onChange={(e) => setForm({ ...form, lang: e.target.value as "en" | "bg" })}>
              <option value="en">English</option>
              <option value="bg">Bulgarian</option>
            </select>
          </div>
          <div className="calrow">
            <label className="small">
              {t.recFirst}{" "}
              <input type="date" aria-label={t.recFirst} min={data.today} value={form.start}
                onChange={(e) => setForm({ ...form, start: e.target.value })} />
            </label>
            <input aria-label={t.recNotes} placeholder={t.recNotes} maxLength={400} value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
          <div className="calrow">
            <p className="billtotal grow">
              {t.recEach}: <b>{money(Math.round(net * (1 + (readNumber(vatShown) || 0) / 100) * 100), data.currency)}</b>
            </p>
            <button type="submit" className="btn" disabled={busy || !client.name.trim() || !lines.some((l) => l.desc.trim() && l.price.trim())}>
              {t.recMake}
            </button>
          </div>
        </form>
      ))}
      {data.may_write && due && (
        <p className="calrow">
          <button type="button" className="btn ghost" disabled={busy} onClick={() => void act({ action: "run" }, "")}>{t.recRunNow}</button>
        </p>
      )}
      {data.plans.length === 0 ? <p className="muted">{t.recNone}</p> : data.plans.map(row)}
    </>
  );
}
