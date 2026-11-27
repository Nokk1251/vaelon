"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { VaelonApi, type CashFlow } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";
import { money } from "./BillsPanel";

const HORIZONS = [30, 60, 90];
const short = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

/** Money > Cash flow (issue #42): what comes in and goes out, week by week, from what Vaelon already knows (unpaid
 *  invoices and bills, repeating bills, the usual income and spending of the last 3 months). Deals are shown apart and
 *  never counted. Nothing here moves money; the balance is a number the user types in. */
export default function CashFlowTab(props: { token: string; t: Strings; onNote: (s: string) => void }) {
  const { token, t, onNote } = props;
  const [days, setDays] = useState(90);
  const [data, setData] = useState<CashFlow | null>(null);
  const [balance, setBalance] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const req = useRef(0); // only the newest answer is shown (quick clicks on 30 / 60 / 90)

  const load = useCallback(async () => {
    const n = ++req.current;
    setLoading(true);
    try {
      const f = await new VaelonApi(token).cashflow(days);
      if (n !== req.current) return;
      setData(f);
      setFailed(false);
    } catch {
      if (n !== req.current) return;
      setFailed(true);
    }
    setLoading(false);
  }, [token, days]);

  useEffect(() => {
    void load();
  }, [load]);

  const saveBalance = async (value: string) => {
    setBusy(true);
    try {
      const r = await new VaelonApi(token).budgetAct({ action: "balance", amount: value });
      onNote(r.ok ? (value ? t.cfBalanceSaved : t.cfBalanceRemoved) : r.error || t.budgetFail);
      if (r.ok) setBalance("");
      await load();
    } catch {
      onNote(t.budgetFail);
    }
    setBusy(false);
  };

  if (!data) return <p className="muted small" role="status">{failed ? t.cfFail : t.cfLoading}</p>;
  const cur = data.currency;
  const known = data.balance !== null;
  const peak = Math.max(1, ...data.weeks.map((w) => Math.max(w.in, w.out)));
  const possible = data.possible.reduce((s, p) => s + p.weighted, 0);

  return (
    <div className="cashflow">
      <div className="row-actions">
        {HORIZONS.map((n) => (
          <button key={n} type="button" className={`btn ghost ${days === n ? "on" : ""}`} aria-pressed={days === n}
            onClick={() => setDays(n)}>
            {t.cfDays.replace("{n}", String(n))}
          </button>
        ))}
      </div>

      <form className="keyform" onSubmit={(e) => { e.preventDefault(); if (balance.trim()) void saveBalance(balance.trim()); }}>
        <input value={balance} onChange={(e) => setBalance(e.target.value)} inputMode="decimal" disabled={busy}
          placeholder={known ? `${t.cfBalanceNow}: ${money(data.balance ?? 0, cur)}` : t.cfBalancePlaceholder.replace("{cur}", cur)}
          aria-label={t.cfBalanceNow} />
        <button type="submit" className="btn" disabled={busy || !balance.trim()}>{t.cfBalanceSave}</button>
        {known && (
          <button type="button" className="btn ghost" disabled={busy} onClick={() => void saveBalance("")}>{t.cfBalanceClear}</button>
        )}
      </form>
      <p className="muted small">{known ? t.cfBalanceAsOf.replace("{date}", data.balance_on) : t.cfNoBalance}</p>

      {data.short_week && (
        <p className="small bad" role="alert">{t.cfShort.replace("{week}", short(data.short_week))}</p>
      )}
      <p className="small">
        {t.cfIn} <b className="good">{money(data.in_total, cur)}</b> · {t.cfOut} <b className="bad">{money(data.out_total, cur)}</b>
        {known && data.lowest ? ` · ${t.cfLowest} ${money(data.lowest.balance, cur)} (${short(data.lowest.week)})` : ""}
      </p>

      {failed && <p className="small bad" role="alert">{t.cfFail}</p>}
      <table className="cf-table" aria-label={t.cfTable} aria-busy={loading} style={{ opacity: loading ? 0.6 : 1 }}>
        <thead>
          <tr><th>{t.cfWeek}</th><th>{t.cfIn}</th><th>{t.cfOut}</th><th>{known ? t.cfBalance : t.cfChange}</th></tr>
        </thead>
        <tbody>
          {data.weeks.map((w) => (
            <tr key={w.from} className={known && w.balance < 0 ? "neg" : ""}>
              <td>{short(w.from)}</td>
              <td>
                <span className="cf-bar in" style={{ width: `${(w.in / peak) * 100}%` }} />
                {w.in ? money(w.in, cur) : "-"}
              </td>
              <td>
                <span className="cf-bar out" style={{ width: `${(w.out / peak) * 100}%` }} />
                {w.out ? money(w.out, cur) : "-"}
              </td>
              <td className={w.balance < 0 ? "bad" : ""}>{money(w.balance, cur)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {(data.late_in > 0 || data.late_out > 0 || data.undated_out > 0) && (
        <ul className="small">
          {data.late_in > 0 && <li>{t.cfLateIn} {money(data.late_in, cur)}</li>}
          {data.late_out > 0 && <li className="bad">{t.cfLateOut} {money(data.late_out, cur)}</li>}
          {data.undated_out > 0 && <li>{t.cfUndated} {money(data.undated_out, cur)}</li>}
        </ul>
      )}
      {possible > 0 && (
        <details className="small">
          <summary>{t.cfPossible.replace("{sum}", money(possible, cur))}</summary>
          <ul>
            {data.possible.map((p, i) => (
              <li key={`${i}-${p.client}`}>{p.client}{p.title ? ` - ${p.title}` : ""}: {money(p.weighted, cur)} ({short(p.close)})</li>
            ))}
          </ul>
        </details>
      )}
      {Object.keys(data.apart).length > 0 && (
        <p className="muted small">
          {t.cfApart} {Object.entries(data.apart).map(([k, v]) => `${money(Math.abs(v), k)} ${v < 0 ? t.cfOutShort : t.cfInShort}`).join(", ")}
        </p>
      )}
      <p className="muted small">{t.cfHow}</p>
    </div>
  );
}
