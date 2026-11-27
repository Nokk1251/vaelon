"use client";

import { useCallback, useEffect, useState } from "react";
import { VaelonApi, readNumber, type MadeFile, type Quote, type QuotesOverview } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";
import { money } from "./BillsPanel";

type Line = { desc: string; qty: string; price: string };
const sums = (t: Record<string, number>) =>
  Object.entries(t)
    .sort()
    .map(([cur, c]) => money(c, cur))
    .join(" + ") || money(0, "EUR");
const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

/** Money > Quotes (issue #43): offers to clients with their own Q-000001 numbers. Sent / declined mark the state;
 *  "Accept" makes the invoice with the same lines (asked here first) and moves a linked deal to won. */
export default function QuotesTab(props: { token: string; t: Strings; onNote: (s: string) => void; onFile: (f: MadeFile) => void;
  onBusiness: () => void }) {
  const { token, t, onNote, onFile } = props;
  const [data, setData] = useState<QuotesOverview | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState<{ id: string; what: "accept" | "delete" } | null>(null);
  const [client, setClient] = useState({ name: "", address: "" });
  const [lines, setLines] = useState<Line[]>([{ desc: "", qty: "1", price: "" }]);
  const [form, setForm] = useState({ vat: "", days: 30, deal: "", lang: "en" as "en" | "bg" });

  const load = useCallback(async () => {
    try {
      setData(await new VaelonApi(token).quotes());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (body: Record<string, unknown>, okNote: string) => {
    setBusy(true);
    let ok = false;
    try {
      const r = await new VaelonApi(token).quotesAct(body);
      ok = r.ok;
      onNote(r.ok ? (r.number ? okNote.replace("{n}", r.number) : okNote) : r.error || t.quoteActFail);
      if (r.ok && r.path) onFile({ path: r.path, name: r.path.split(/[\\/]/).pop() || r.path, kb: r.kb ?? 1 });
      await load();
    } catch {
      onNote(t.quoteActFail);
    }
    setAsking(null);
    setBusy(false);
    return ok;
  };

  const make = async () => {
    const items = lines.filter((l) => l.desc.trim() && l.price.trim());
    if ((!client.name.trim() && !form.deal) || !items.length) return;
    const done = await act({ action: "add", client, items, vat_rate: form.vat, valid_days: form.days, deal: form.deal,
      lang: form.lang }, t.quoteMade);
    if (done) {
      setClient({ name: "", address: "" });
      setLines([{ desc: "", qty: "1", price: "" }]);
      setForm((f) => ({ ...f, deal: "" }));
    }
  };

  if (!data) return <p className="muted small" role="status">{failed ? t.quoteFail : t.loading}</p>;
  const vatShown = form.vat !== "" ? form.vat : data.vat_rate;
  const net = lines.reduce((s, l) => s + (readNumber(l.price) || 0) * (readNumber(l.qty) || 0), 0); // as the core reads them
  const cur = data.deals.find((d) => d.id === form.deal)?.currency || data.currency;
  const state = (q: Quote) =>
    q.status === "accepted" ? t.quoteAcceptedInv.replace("{n}", q.invoice)
      : q.status === "expired" ? t.quoteExpiredOn.replace("{d}", day(q.valid_until))
        : q.status === "declined" ? t.quoteStates.declined
          : `${t.quoteStates[q.status as "draft" | "sent"]} · ${t.quoteValid} ${day(q.valid_until)}`;

  const row = (q: Quote) => (
    <div key={q.id} className={`billrow quoterow ${q.status === "expired" ? "late" : ""} ${q.status === "declined" ? "void" : ""}`}>
      <span className="billwho">
        <b className="mono">{q.number}</b> {q.client}
        {q.deal_label && <em> · {q.deal_label}</em>}
      </span>
      <span className="billsum">{money(q.total, q.currency)}</span>
      <span className="billwhen">{state(q)}</span>
      {asking?.id === q.id ? (
        <span className="chatask">
          {asking.what === "accept" && <span className="small">{t.quoteAcceptAsk}</span>}
          <button type="button" className="btn" disabled={busy}
            onClick={() => void (asking.what === "accept" ? act({ action: "accept", id: q.id }, t.quoteAccepted)
              : act({ action: "delete", id: q.id }, t.quoteDeleted))}>
            {asking.what === "accept" ? t.quoteAcceptYes : t.chatDelete}
          </button>
          <button type="button" className="btn ghost" onClick={() => setAsking(null)}>{t.chatKeep}</button>
        </span>
      ) : (
        <span className="billacts">
          {q.file && (
            <button type="button" className="btn ghost" onClick={() => void new VaelonApi(token).open(q.file).catch(() => onNote(t.fileOpenFail))}>
              PDF
            </button>
          )}
          {data.may_write && q.status === "draft" && (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act({ action: "status", id: q.id, status: "sent" }, t.quoteSent)}>
              {t.quoteMarkSent}
            </button>
          )}
          {q.may_accept && ["draft", "sent", "expired"].includes(q.status) && (
            <button type="button" className="btn ghost" disabled={busy} title={t.quoteAcceptHint} onClick={() => setAsking({ id: q.id, what: "accept" })}>
              {t.quoteAccept}
            </button>
          )}
          {data.may_write && ["draft", "sent", "expired"].includes(q.status) && (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act({ action: "status", id: q.id, status: "declined" }, t.quoteDeclinedNote)}>
              {t.quoteDecline}
            </button>
          )}
          {data.may_write && q.status === "declined" && (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act({ action: "status", id: q.id, status: "sent" }, t.quoteSent)}>
              {t.quoteReopen}
            </button>
          )}
          {data.may_write && q.status !== "accepted" && (
            <button type="button" className="x" disabled={busy} aria-label={`${t.chatDelete}: ${q.number}`} onClick={() => setAsking({ id: q.id, what: "delete" })}>
              ✕
            </button>
          )}
        </span>
      )}
    </div>
  );

  return (
    <>
      <p className="billtotal">{t.quoteOpen}: <b>{sums(data.open)}</b></p>
      {data.may_write && (!data.has_business ? (
        <p className="muted">
          {t.invNeedBiz}{" "}
          <button type="button" className="btn ghost" onClick={props.onBusiness}>{t.billTabs.business}</button>
        </p>
      ) : (
        <form className="calform" onSubmit={(e) => { e.preventDefault(); void make(); }}>
          <div className="calrow">
            <input aria-label={t.invClient} placeholder={form.deal ? t.quoteClientFromDeal : t.invClient} maxLength={120}
              value={client.name} onChange={(e) => setClient({ ...client, name: e.target.value })} />
            <input aria-label={t.invClientAddr} placeholder={t.invClientAddr} maxLength={200} value={client.address}
              onChange={(e) => setClient({ ...client, address: e.target.value })} />
          </div>
          {data.deals.length > 0 && (
            <div className="calrow">
              <select aria-label={t.quoteDeal} value={form.deal} onChange={(e) => setForm({ ...form, deal: e.target.value })}>
                <option value="">{t.quoteNoDeal}</option>
                {data.deals.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
              </select>
            </div>
          )}
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
            <input aria-label={t.invVat} placeholder={`${t.invVat} ${vatShown}`} inputMode="decimal" className="tiny" value={form.vat}
              onChange={(e) => setForm({ ...form, vat: e.target.value })} />
            <select aria-label={t.quoteValid} value={form.days} onChange={(e) => setForm({ ...form, days: Number(e.target.value) })}>
              {[7, 14, 30, 60, 90].map((d) => <option key={d} value={d}>{t.quoteValidDays.replace("{n}", String(d))}</option>)}
            </select>
            <select aria-label={t.invLang} value={form.lang} className="lang" onChange={(e) => setForm({ ...form, lang: e.target.value as "en" | "bg" })}>
              <option value="en">English</option>
              <option value="bg">Bulgarian</option>
            </select>
          </div>
          <div className="calrow">
            <p className="billtotal grow">
              {t.invTotal}: <b>{money(Math.round(net * (1 + (readNumber(vatShown) || 0) / 100) * 100), cur)}</b>
              <span className="muted small"> · {t.invNext} {data.next}</span>
            </p>
            <button type="submit" className="btn" disabled={busy || (!client.name.trim() && !form.deal) || !lines.some((l) => l.desc.trim() && l.price.trim())}>
              {t.quoteMake}
            </button>
          </div>
        </form>
      ))}
      <p className="muted small">{t.quoteSay}</p>
      {data.quotes.length === 0 ? <p className="muted">{t.quoteNone}</p> : data.quotes.map(row)}
    </>
  );
}
