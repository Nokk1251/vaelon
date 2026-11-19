"use client";

import { useState } from "react";
import { VaelonApi, type CompanyState } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";

/** Company mode, locked: who are you, and your PIN. Nothing else of Vaelon answers until someone signs in. */
export default function SignIn(props: { token: string; t: Strings; state: CompanyState; onDone: (s: CompanyState) => void }) {
  const { token, t, state, onDone } = props;
  const [who, setWho] = useState(state.people[0]?.id ?? "");
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const go = async () => {
    if (!who || !pin) return;
    setBusy(true);
    setError("");
    try {
      const r = await new VaelonApi(token).companyAct({ action: "sign_in", user: who, pin });
      setPin("");
      if (r.ok && r.state) onDone(r.state);
      else setError(r.error || t.signInFail);
    } catch {
      setError(t.signInFail);
    }
    setBusy(false);
  };

  return (
    <div className="signin-wrap" role="dialog" aria-label={t.signInTitle}>
      <form className="signin" onSubmit={(e) => { e.preventDefault(); void go(); }}>
        <h2>VAELON</h2>
        <p className="muted small">{t.signInTitle}</p>
        <div className="signin-people" role="radiogroup" aria-label={t.signInWho}>
          {state.people.map((p) => (
            <button type="button" key={p.id} role="radio" aria-checked={who === p.id} className={`btn ${who === p.id ? "" : "ghost"}`}
              onClick={() => setWho(p.id)}>{p.name}</button>
          ))}
        </div>
        <input type="password" inputMode="numeric" autoComplete="off" maxLength={8} aria-label="PIN" placeholder="PIN" value={pin}
          autoFocus onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} />
        {error && <p className="small bad">{error}</p>}
        <button type="submit" className="btn" disabled={busy || !pin || !who}>{t.signIn}</button>
      </form>
    </div>
  );
}
