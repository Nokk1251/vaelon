"use client";

import { useCallback, useEffect, useState } from "react";
import { VaelonApi, readNumber, type Bill, type BillsOverview, type CompanyState, type Invoice, type MadeFile } from "@/lib/vaelonApi";
import { STRINGS, type Lang } from "@/lib/i18n";
import FileCard from "./FileCard";
import BudgetTab from "./BudgetTab";
import DealsTab from "./DealsTab";
import CashFlowTab from "./CashFlowTab";
import QuotesTab from "./QuotesTab";
import CompanyTab from "./CompanyTab";

export type MoneyTab = "budget" | "cashflow" | "due" | "paid" | "deals" | "quotes" | "invoices" | "business" | "company";
type Tab = MoneyTab;
const TABS: Tab[] = ["budget", "cashflow", "due", "paid", "deals", "quotes", "invoices", "business", "company"];
// company mode: a tab shows only when the role may read it
const NEEDS: Record<Tab, string> = { budget: "budget.read", cashflow: "bills.read,invoices.read,budget.read", due: "bills.read", paid: "bills.read", deals: "deals.read", quotes: "quotes.read",
  invoices: "invoices.read", business: "profile.write", company: "" };
const pad = (n: number) => String(n).padStart(2, "0");
const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const inDays = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return isoDay(d);
};

/** 4520, "EUR" -> "45.20 EUR" in the reader's number style. */
export function money(cents: number, cur: string): string {
  return `${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${cur}`;
}
const sums = (t: Record<string, number>) =>
  Object.entries(t)
    .sort()
    .map(([cur, c]) => money(c, cur))
    .join(" + ") || money(0, "EUR");

type Line = { desc: string; qty: string; price: string };
const PROFILE: [string, "text" | "area"][] = [
  ["name", "text"], ["address", "text"], ["company_id", "text"], ["vat_id", "text"], ["person", "text"],
  ["bank", "area"], ["email", "text"], ["phone", "text"],
];

/** Bills to pay, paid bills, the invoices you issue, your business details. Vaelon never pays anything:
 *  "Paid" only marks a bill in the list. Everything is stored encrypted on this computer. */
export default function BillsPanel(props: { token: string; lang: Lang; tab?: MoneyTab; perms?: string[] | null;
  onCompany?: (s: CompanyState) => void; onClose: () => void; onNote: (s: string) => void }) {
  const { token, lang, onClose, onNote } = props;
  const t = STRINGS[lang];
  const allowed = (id: Tab) => !props.perms || !NEEDS[id] || NEEDS[id].split(",").every((p) => props.perms!.includes(p));
  // a role opens on a tab it may see (a viewer of deals only must not land on bills it cannot read)
  const [tab, setTab] = useState<Tab>(() => {
    const want = props.tab ?? "budget";
    return allowed(want) ? want : TABS.find(allowed) ?? "company";
  });
  const mayReadBills = !props.perms || props.perms.includes("bills.read") || props.perms.includes("invoices.read");
  const [data, setData] = useState<BillsOverview | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState<string | null>(null); // id of the bill / invoice whose delete / void is being confirmed
  const [made, setMade] = useState<MadeFile | null>(null);
  const [bill, setBill] = useState({ vendor: "", amount: "", currency: "EUR", due: inDays(7), category: "", repeat: "", remind: 3 as number | null });
  const [client, setClient] = useState({ name: "", address: "", company_id: "", vat_id: "" });
  const [lines, setLines] = useState<Line[]>([{ desc: "", qty: "1", price: "" }]);
  const [inv, setInv] = useState({ vat: "", days: 14, currency: "", lang: "en" as "en" | "bg" });
  const [me, setMe] = useState<Record<string, string>>({});
  const [meDirty, setMeDirty] = useState(false);

  const api = useCallback(() => new VaelonApi(token), [token]);
  const load = useCallback(async () => {
    if (!mayReadBills) return; // no error message every time the panel opens for a role without bills
    try {
      const o = await api().bills();
      setData(o);
      setMe((cur) => (meDirty ? cur : { ...o.me, next: o.next }));
    } catch {
      onNote(t.billsFail);
    }
  }, [api, meDirty, onNote, t.billsFail, mayReadBills]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const act = async (body: Record<string, unknown>, okNote: string) => {
    setBusy(true);
    let ok = false;
    try {
      const r = await api().billsAct(body);
      ok = r.ok;
      onNote(r.ok ? okNote : r.error || t.billsFail);
      if (r.ok && r.path) setMade({ path: r.path, name: r.path.split(/[\\/]/).pop() || r.path, kb: r.kb ?? 1 });
      await load();
    } catch {
      onNote(t.billsFail);
    }
    setAsking(null);
    setBusy(false);
    return ok;
  };

  const addBill = async () => {
    if (!bill.vendor.trim() || !bill.amount.trim()) return;
    if (await act({ action: "add", ...bill }, t.billAdded)) setBill((b) => ({ ...b, vendor: "", amount: "" }));
  };

  const makeInvoice = async () => {
    const items = lines.filter((l) => l.desc.trim() && l.price.trim());
    if (!client.name.trim() || !items.length) return;
    const done = await act({ action: "invoice", client, items, vat_rate: inv.vat, due_days: inv.days, currency: inv.currency,
      lang: inv.lang }, t.invMade);
    if (done) {
      setClient({ name: "", address: "", company_id: "", vat_id: "" });
      setLines([{ desc: "", qty: "1", price: "" }]);
    }
  };

  const saveMe = async () => {
    const fields: Record<string, string> = {};
    for (const [k] of PROFILE) fields[k] = me[k] ?? "";
    if (me.vat_rate !== undefined && me.vat_rate !== "") fields.vat_rate = me.vat_rate;
    if (me.currency) fields.currency = me.currency;
    if (me.next && data && me.next !== data.next) fields.next = me.next;
    setMeDirty(false);
    await act({ action: "profile", fields }, t.bizSaved);
  };

  const dueText = (b: { due: string; overdue: boolean }) => {
    if (!b.due) return t.billNoDate;
    const today = data?.today ?? isoDay(new Date());
    if (b.due === today) return t.billToday;
    const d = new Date(`${b.due}T12:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: b.due.slice(0, 4) === today.slice(0, 4) ? undefined : "numeric" });
    return b.overdue ? `${t.billOverdue} ${d}` : `${t.billDue} ${d}`;
  };
  // the category, unless it says nothing new ("other", or "Rent" filed under rent)
  const cat = (b: Bill) => (b.category === "other" || b.vendor.toLowerCase().includes(b.category.split(" ")[0]) ? "" : b.category);
  const lineTotal = lines.reduce((s, l) => s + (readNumber(l.price) || 0) * (readNumber(l.qty) || 0), 0); // as the core reads them
  const vatShown = inv.vat !== "" ? inv.vat : me.vat_rate || (me.vat_id ? "20" : "0");

  const billRow = (b: Bill) => (
    <div key={b.id} className={`billrow ${b.overdue ? "late" : ""}`}>
      <span className="billwho">
        {b.vendor}
        {cat(b) && <em> · {b.category}</em>}
        {b.repeat && <i title={b.repeat}> ↻</i>}
      </span>
      <span className="billsum">
        {b.estimate && <i title={t.billEstimate}>~</i>}
        {money(b.amount, b.currency)}
      </span>
      <span className="billwhen">{b.status === "paid" ? `${t.billPaidOn} ${b.paid_on}` : dueText(b)}</span>
      {asking === b.id ? (
        <span className="chatask">
          <button type="button" className="btn" disabled={busy} onClick={() => void act({ action: "delete", id: b.id }, t.billDeleted)}>
            {t.chatDelete}
          </button>
          <button type="button" className="btn ghost" onClick={() => setAsking(null)}>{t.chatKeep}</button>
        </span>
      ) : b.status === "unpaid" ? (
        <span className="billacts">
          <button type="button" className="btn ghost" disabled={busy} title={t.billPaidHint}
            onClick={() => void act({ action: "paid", id: b.id }, t.billMarked)}>{t.billPaid}</button>
          <button type="button" className="x" aria-label={`${t.chatDelete}: ${b.vendor}`} onClick={() => setAsking(b.id)}>✕</button>
        </span>
      ) : (
        <button type="button" className="btn ghost" disabled={busy} onClick={() => void act({ action: "unpaid", id: b.id }, t.billUnmarked)}>
          {t.billNotPaid}
        </button>
      )}
    </div>
  );

  const invRow = (i: Invoice) => (
    <div key={i.id} className={`billrow ${i.overdue ? "late" : ""} ${i.status === "void" ? "void" : ""}`}>
      <span className="billwho">
        <b className="mono">{i.number}</b> {i.client}
      </span>
      <span className="billsum">{money(i.total, i.currency)}</span>
      <span className="billwhen">
        {i.status === "paid" ? `${t.billPaidOn} ${i.paid_on}` : i.status === "void" ? t.invVoid : dueText(i)}
      </span>
      {asking === i.id ? (
        <span className="chatask">
          <button type="button" className="btn" disabled={busy} onClick={() => void act({ action: "invoice_void", id: i.id }, t.invVoided)}>
            {t.invVoidIt}
          </button>
          <button type="button" className="btn ghost" onClick={() => setAsking(null)}>{t.chatKeep}</button>
        </span>
      ) : (
        <span className="billacts">
          {i.file && (
            <button type="button" className="btn ghost" onClick={() => void api().open(i.file).catch(() => onNote(t.fileOpenFail))}>
              PDF
            </button>
          )}
          {i.status === "unpaid" && (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act({ action: "invoice_paid", id: i.id }, t.invPaid)}>
              {t.billPaid}
            </button>
          )}
          {i.status === "paid" && (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act({ action: "invoice_unpaid", id: i.id }, t.billUnmarked)}>
              {t.billNotPaid}
            </button>
          )}
          {i.status !== "void" && (
            <button type="button" className="x" aria-label={`${t.invVoidIt}: ${i.number}`} title={t.invVoidHint} onClick={() => setAsking(i.id)}>
              ✕
            </button>
          )}
        </span>
      )}
    </div>
  );

  const owed: Record<string, number> = {};
  for (const i of data?.invoices ?? []) if (i.status === "unpaid") owed[i.currency] = (owed[i.currency] ?? 0) + i.total;

  return (
    <div className="panel-wrap" onClick={onClose}>
      <aside className="panel bills" role="dialog" aria-label={t.bills} onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <span className="panel-title">{t.bills}</span>
          <span className="panel-sub">{t.billsPrivate}</span>
          <button className="x" onClick={onClose} aria-label={t.close}>
            ✕
          </button>
        </div>
        <nav className="tabs">
          {TABS.filter(allowed).map((id) => (
            <button key={id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>
              {t.billTabs[id]}
              {id === "due" && data && data.totals.overdue > 0 && <span className="badge">{data.totals.overdue}</span>}
            </button>
          ))}
        </nav>
        <div className="panel-body">
          {!data && !["budget", "cashflow", "deals", "quotes", "company"].includes(tab) && <p className="muted scan">{t.loading}</p>}
          {made && (
            <div className="billmade">
              <FileCard file={made} token={token} t={t} onNote={onNote} />
            </div>
          )}

          {tab === "budget" && <BudgetTab token={token} t={t} onNote={onNote} />}
          {tab === "cashflow" && <CashFlowTab token={token} t={t} onNote={onNote} />}
          {tab === "company" && <CompanyTab token={token} t={t} onNote={onNote} onState={(s) => props.onCompany?.(s)} />}
          {tab === "deals" && <DealsTab token={token} t={t} onNote={onNote} onFile={(f) => { setMade(f); void load(); }} />}
          {tab === "quotes" && (
            <QuotesTab token={token} t={t} onNote={onNote} onFile={(f) => { setMade(f); void load(); }} onBusiness={() => setTab("business")} />
          )}

          {data && tab === "due" && (
            <>
              <p className="billtotal">
                {t.billUnpaid}: <b>{sums(data.totals.unpaid)}</b>
                {data.totals.overdue > 0 && <span className="late"> · {data.totals.overdue} {t.billOverdueCount}</span>}
              </p>
              <form className="calform" onSubmit={(e) => { e.preventDefault(); void addBill(); }}>
                <div className="calrow">
                  <input aria-label={t.billWho} placeholder={t.billWho} maxLength={120} value={bill.vendor}
                    onChange={(e) => setBill({ ...bill, vendor: e.target.value })} />
                  <input aria-label={t.billAmount} placeholder={t.billAmount} inputMode="decimal" maxLength={20} value={bill.amount}
                    className="narrow" onChange={(e) => setBill({ ...bill, amount: e.target.value })} />
                  <select aria-label={t.billCurrency} value={bill.currency} className="narrow" onChange={(e) => setBill({ ...bill, currency: e.target.value })}>
                    {data.currencies.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div className="calrow">
                  <input type="date" aria-label={t.billDueDate} value={bill.due} onChange={(e) => setBill({ ...bill, due: e.target.value })} />
                  <select aria-label={t.billCategory} value={bill.category} onChange={(e) => setBill({ ...bill, category: e.target.value })}>
                    <option value="">{t.billAutoCat}</option>
                    {data.categories.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div className="calrow">
                  <select aria-label={t.calRepeat} value={bill.repeat} onChange={(e) => setBill({ ...bill, repeat: e.target.value })}>
                    <option value="">{t.calOnce}</option>
                    <option value="monthly">{t.calMonthly}</option>
                    <option value="quarterly">{t.billQuarterly}</option>
                    <option value="yearly">{t.calYearly}</option>
                  </select>
                  <select aria-label={t.calRemind} value={bill.remind ?? -1}
                    onChange={(e) => setBill({ ...bill, remind: Number(e.target.value) < 0 ? null : Number(e.target.value) })}>
                    <option value={-1}>{t.calNoRemind}</option>
                    {[1, 3, 7].map((d) => <option key={d} value={d}>{d === 1 ? t.billRemindDay : t.billRemindDays.replace("{n}", String(d))}</option>)}
                  </select>
                  <button type="submit" className="btn" disabled={busy || !bill.vendor.trim() || !bill.amount.trim()}>{t.calAdd}</button>
                </div>
              </form>
              <p className="muted small">{t.billSay}</p>
              {data.unpaid.length === 0 ? <p className="muted">{t.billNone}</p> : data.unpaid.map(billRow)}
            </>
          )}

          {data && tab === "paid" && (
            <>
              <div className="calnav">
                <p className="billtotal grow">
                  {t.billPaidYear.replace("{y}", String(data.totals.year))}: <b>{sums(data.totals.paid_year)}</b>
                </p>
                <button type="button" className="btn ghost" disabled={busy} onClick={() => void act({ action: "export" }, t.billExported)}>
                  {t.billExport}
                </button>
              </div>
              {Object.entries(data.totals.by_category).length > 0 && (
                <div className="billcats">
                  {Object.entries(data.totals.by_category).map(([c, tot]) => (
                    <span key={c} className="billcat"><em>{c}</em> {sums(tot)}</span>
                  ))}
                </div>
              )}
              {data.paid.length === 0 ? <p className="muted">{t.billNonePaid}</p> : data.paid.map(billRow)}
            </>
          )}

          {data && tab === "invoices" && (
            <>
              <p className="billtotal">{t.invOwed}: <b>{sums(owed)}</b></p>
              {!data.me.name ? (
                <p className="muted">
                  {t.invNeedBiz}{" "}
                  <button type="button" className="btn ghost" onClick={() => setTab("business")}>{t.billTabs.business}</button>
                </p>
              ) : (
                <form className="calform" onSubmit={(e) => { e.preventDefault(); void makeInvoice(); }}>
                  <div className="calrow">
                    <input aria-label={t.invClient} placeholder={t.invClient} maxLength={120} value={client.name}
                      onChange={(e) => setClient({ ...client, name: e.target.value })} />
                    <input aria-label={t.invClientAddr} placeholder={t.invClientAddr} maxLength={200} value={client.address}
                      onChange={(e) => setClient({ ...client, address: e.target.value })} />
                  </div>
                  <div className="calrow">
                    <input aria-label={t.bizField.company_id} placeholder={t.bizField.company_id} maxLength={30} value={client.company_id}
                      onChange={(e) => setClient({ ...client, company_id: e.target.value })} />
                    <input aria-label={t.bizField.vat_id} placeholder={t.bizField.vat_id} maxLength={30} value={client.vat_id}
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
                    <input aria-label={t.invVat} placeholder={`${t.invVat} ${vatShown}`} inputMode="decimal" className="tiny" value={inv.vat}
                      onChange={(e) => setInv({ ...inv, vat: e.target.value })} />
                    <select aria-label={t.invDays} value={inv.days} onChange={(e) => setInv({ ...inv, days: Number(e.target.value) })}>
                      {[0, 7, 14, 30, 60].map((d) => <option key={d} value={d}>{d === 0 ? t.invOnReceipt : t.invDaysN.replace("{n}", String(d))}</option>)}
                    </select>
                    <select aria-label={t.invLang} value={inv.lang} className="lang" onChange={(e) => setInv({ ...inv, lang: e.target.value as "en" | "bg" })}>
                      <option value="en">English</option>
                      <option value="bg">Bulgarian</option>
                    </select>
                  </div>
                  <div className="calrow">
                    <p className="billtotal grow">
                      {t.invTotal}: <b>{money(Math.round(lineTotal * (1 + (readNumber(vatShown) || 0) / 100) * 100), inv.currency || me.currency || "EUR")}</b>
                      <span className="muted small"> · {t.invNext} {data.next}</span>
                    </p>
                    <button type="submit" className="btn" disabled={busy || !client.name.trim() || !lines.some((l) => l.desc.trim() && l.price.trim())}>
                      {t.invMake}
                    </button>
                  </div>
                </form>
              )}
              <p className="muted small">{t.invSay}</p>
              {data.invoices.length === 0 ? <p className="muted">{t.invNone}</p> : data.invoices.map(invRow)}
            </>
          )}

          {data && tab === "business" && (
            <form className="calform" onSubmit={(e) => { e.preventDefault(); void saveMe(); }}>
              <p className="muted small">{t.bizNote}</p>
              {PROFILE.map(([k, kind]) => (
                <label key={k} className="bizfield">
                  <span>{t.bizField[k as keyof typeof t.bizField]}</span>
                  {kind === "area" ? (
                    <textarea rows={2} maxLength={300} value={me[k] ?? ""} onChange={(e) => { setMeDirty(true); setMe({ ...me, [k]: e.target.value }); }} />
                  ) : (
                    <input maxLength={200} value={me[k] ?? ""} autoComplete="off" onChange={(e) => { setMeDirty(true); setMe({ ...me, [k]: e.target.value }); }} />
                  )}
                </label>
              ))}
              <div className="calrow">
                <label className="bizfield">
                  <span>{t.bizField.vat_rate}</span>
                  <input inputMode="decimal" value={me.vat_rate ?? ""} placeholder={me.vat_id ? "20" : "0"}
                    onChange={(e) => { setMeDirty(true); setMe({ ...me, vat_rate: e.target.value }); }} />
                </label>
                <label className="bizfield">
                  <span>{t.bizField.currency}</span>
                  <select value={me.currency || "EUR"} onChange={(e) => { setMeDirty(true); setMe({ ...me, currency: e.target.value }); }}>
                    {data.currencies.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </label>
                <label className="bizfield">
                  <span>{t.bizField.next}</span>
                  <input inputMode="numeric" value={me.next ?? ""} onChange={(e) => { setMeDirty(true); setMe({ ...me, next: e.target.value }); }} />
                </label>
              </div>
              <div className="calrow">
                <span className="grow" />
                <button type="submit" className="btn" disabled={busy || !meDirty}>{t.save}</button>
              </div>
            </form>
          )}
        </div>
      </aside>
    </div>
  );
}
