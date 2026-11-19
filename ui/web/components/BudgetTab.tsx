"use client";

import { useCallback, useEffect, useState } from "react";
import { VaelonApi, type BudgetMonth } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";
import { money } from "./BillsPanel";

const pad = (n: number) => String(n).padStart(2, "0");
const thisMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
};
const shift = (ym: string, n: number) => {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1 + n, 1);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
};
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

/** One month of the budget: income, spending per category against its limit, the entries. Paid bills count as
 *  spending by themselves. Nothing here moves money - it is a record you keep. */
export default function BudgetTab(props: { token: string; t: Strings; onNote: (s: string) => void }) {
  const { token, t, onNote } = props;
  const [month, setMonth] = useState(thisMonth());
  const [data, setData] = useState<BudgetMonth | null>(null);
  const [busy, setBusy] = useState(false);
  const [entry, setEntry] = useState({ kind: "expense" as "expense" | "income", amount: "", currency: "", category: "", note: "", date: today() });
  const [limit, setLimit] = useState({ category: "total", amount: "" });
  const [statement, setStatement] = useState<{ path: string; name: string; text: string } | null>(null); // previewed, not imported yet

  const load = useCallback(async () => {
    try {
      setData(await new VaelonApi(token).budget(month));
    } catch {
      onNote(t.budgetFail);
    }
  }, [token, month, onNote, t.budgetFail]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (body: Record<string, unknown>, okNote: string) => {
    setBusy(true);
    let ok = false;
    try {
      const r = await new VaelonApi(token).budgetAct(body);
      ok = r.ok;
      onNote(r.ok ? [okNote, r.warning].filter(Boolean).join(" ") : r.error || t.budgetFail);
      if (r.ok && r.text && body.action === "import") onNote(r.text);
      await load();
    } catch {
      onNote(t.budgetFail);
    }
    setBusy(false);
    return ok;
  };

  // a bank statement: upload it, show what would happen, import only when the user says so
  const pickStatement = async (f: File | undefined) => {
    if (!f) return;
    setBusy(true);
    try {
      const api = new VaelonApi(token);
      const up = await api.upload(f);
      const r = await api.budgetAct({ action: "import", path: up.path, preview: true });
      if (r.ok && r.text) setStatement({ path: up.path, name: up.name, text: r.text });
      else onNote(r.error || t.budgetFail);
    } catch (e) {
      onNote(e instanceof Error ? e.message : t.budgetFail);
    }
    setBusy(false);
  };
  const importStatement = async () => {
    if (!statement) return;
    if (await act({ action: "import", path: statement.path }, t.bankImported)) setStatement(null);
  };

  if (!data) return <p className="muted scan">{t.loading}</p>;
  const cur = data.currency;
  const m = (c: number) => money(c, cur);
  const bar = (spent: number, lim: number | null) => {
    if (!lim) return null;
    const p = Math.round((100 * spent) / lim);
    return (
      <span className={`budbar ${p > 100 ? "over" : p >= 80 ? "near" : ""}`} title={`${p} %`}>
        <i style={{ width: `${Math.min(100, p)}%` }} />
      </span>
    );
  };

  return (
    <>
      <div className="calnav">
        <button type="button" className="btn ghost" onClick={() => setMonth(shift(month, -1))} aria-label={t.calEarlier}>‹</button>
        <button type="button" className="btn ghost" onClick={() => setMonth(thisMonth())}>{data.label}</button>
        <button type="button" className="btn ghost" onClick={() => setMonth(shift(month, 1))} aria-label={t.calLater}>›</button>
        <span className="grow" />
        <select aria-label={t.budgetCurrency} value={cur} disabled={busy} title={t.budgetCurrency}
          onChange={(e) => void act({ action: "currency", currency: e.target.value }, t.budgetSaved)}>
          {data.currencies.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <p className="billtotal">
        {t.budgetIncome}: <b>{m(data.income)}</b> · {t.budgetSpent}: <b>{m(data.spent)}</b> ·{" "}
        <span className={data.left < 0 ? "late" : ""}>{data.left < 0 ? t.budgetShort : t.budgetLeft}: <b>{m(Math.abs(data.left))}</b></span>
      </p>
      {data.total_limit ? (
        <div className="budrow">
          <span className="budcat">{t.budgetTotal}</span>
          {bar(data.spent, data.total_limit)}
          <span className="budsum">{m(data.spent)} / {m(data.total_limit)}</span>
          <button type="button" className="x" aria-label={`${t.budgetNoLimit}: ${t.budgetTotal}`} title={t.budgetNoLimit}
            onClick={() => void act({ action: "limit", category: "total", amount: null }, t.budgetSaved)}>✕</button>
        </div>
      ) : null}

      <form className="calform" onSubmit={(e) => {
        e.preventDefault();
        if (!entry.amount.trim()) return;
        void act({ action: "add", ...entry, currency: entry.currency || cur }, entry.kind === "income" ? t.budgetIncomeAdded : t.budgetExpenseAdded)
          .then((ok) => ok && setEntry((x) => ({ ...x, amount: "", note: "" })));
      }}>
        <div className="calrow">
          <select aria-label={t.budgetKind} className="narrow" value={entry.kind}
            onChange={(e) => setEntry({ ...entry, kind: e.target.value as "expense" | "income" })}>
            <option value="expense">{t.budgetExpense}</option>
            <option value="income">{t.budgetIncomeOne}</option>
          </select>
          <input aria-label={t.billAmount} placeholder={t.billAmount} inputMode="decimal" maxLength={20} className="narrow" value={entry.amount}
            onChange={(e) => setEntry({ ...entry, amount: e.target.value })} />
          <select aria-label={t.billCurrency} className="narrow" value={entry.currency || cur}
            onChange={(e) => setEntry({ ...entry, currency: e.target.value })}>
            {data.currencies.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <input type="date" aria-label={t.calDate} value={entry.date} onChange={(e) => setEntry({ ...entry, date: e.target.value })} />
        </div>
        <div className="calrow">
          <input aria-label={t.budgetNote} placeholder={t.budgetNote} maxLength={200} value={entry.note}
            onChange={(e) => setEntry({ ...entry, note: e.target.value })} />
          {entry.kind === "expense" && (
            <select aria-label={t.billCategory} value={entry.category} onChange={(e) => setEntry({ ...entry, category: e.target.value })}>
              <option value="">{t.billAutoCat}</option>
              {data.categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          )}
          <button type="submit" className="btn" disabled={busy || !entry.amount.trim()}>{t.calAdd}</button>
        </div>
      </form>
      <p className="muted small">{t.budgetSay}</p>

      {data.rows.map((r) => (
        <div key={r.category} className="budrow">
          <span className="budcat">{r.category}</span>
          {bar(r.spent, r.limit)}
          <span className="budsum">{m(r.spent)}{r.limit ? ` / ${m(r.limit)}` : ""}</span>
          {r.limit ? (
            <button type="button" className="x" aria-label={`${t.budgetNoLimit}: ${r.category}`} title={t.budgetNoLimit}
              onClick={() => void act({ action: "limit", category: r.category, amount: null }, t.budgetSaved)}>✕</button>
          ) : (
            <button type="button" className="btn ghost" onClick={() => setLimit({ category: r.category, amount: "" })}>{t.budgetSetLimit}</button>
          )}
        </div>
      ))}
      <form className="calrow budlimit" onSubmit={(e) => {
        e.preventDefault();
        if (!limit.amount.trim()) return;
        void act({ action: "limit", category: limit.category, amount: limit.amount }, t.budgetSaved).then((ok) => ok && setLimit({ ...limit, amount: "" }));
      }}>
        <select aria-label={t.billCategory} value={limit.category} onChange={(e) => setLimit({ ...limit, category: e.target.value })}>
          <option value="total">{t.budgetTotal}</option>
          {data.categories.filter((c) => c !== "other").map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input aria-label={t.budgetLimitAmount} placeholder={`${t.budgetLimitAmount} (${cur})`} inputMode="decimal" className="narrow"
          value={limit.amount} onChange={(e) => setLimit({ ...limit, amount: e.target.value })} />
        <button type="submit" className="btn ghost" disabled={busy || !limit.amount.trim()}>{t.budgetSetLimit}</button>
      </form>
      {Object.keys(data.apart).length > 0 && (
        <p className="muted small">{t.budgetApart}: {Object.entries(data.apart).map(([c, v]) => money(v, c)).join(" + ")}</p>
      )}

      <div className="calnav">
        <label className="btn ghost filepick">
          {t.bankPick}
          <input type="file" accept=".csv,text/csv" disabled={busy} onChange={(e) => { void pickStatement(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
        <span className="muted small grow">{t.bankHint}</span>
      </div>
      {statement && (
        <div className="dealmore">
          <b>{statement.name}</b>
          <pre className="bankpre">{statement.text}</pre>
          <div className="calrow">
            <button type="button" className="btn" disabled={busy} onClick={() => void importStatement()}>{t.bankDo}</button>
            <button type="button" className="btn ghost" onClick={() => setStatement(null)}>{t.chatKeep}</button>
          </div>
        </div>
      )}

      <h4 className="budhead">{t.budgetEntries}</h4>
      {data.entries.length === 0 && data.bills.length === 0 && <p className="muted">{t.budgetNone}</p>}
      {data.entries.map((e) => (
        <div key={e.id} className={`billrow ${e.kind === "income" ? "income" : ""}`}>
          <span className="billwhen left">{e.date.slice(8)}.{e.date.slice(5, 7)}</span>
          <span className="billwho">
            {e.note || e.category}
            {e.note && e.kind === "expense" && <em> · {e.category}</em>}
          </span>
          <span className="billsum">{e.kind === "income" ? "+" : "-"}{money(e.amount, e.currency)}</span>
          <button type="button" className="x" aria-label={`${t.chatDelete}: ${e.note || e.category}`}
            onClick={() => void act({ action: "delete", id: e.id }, t.budgetDeleted)}>✕</button>
        </div>
      ))}
      {data.bills.map((b) => (
        <div key={b.id} className="billrow frombill" title={t.budgetFromBill}>
          <span className="billwhen left">{b.date.slice(8)}.{b.date.slice(5, 7)}</span>
          <span className="billwho">{b.vendor}<em> · {t.budgetBill}</em></span>
          <span className="billsum">-{money(b.amount, b.currency)}</span>
        </div>
      ))}
    </>
  );
}
