"use client";

import { useCallback, useEffect, useState } from "react";
import { VaelonApi, type CompanyState, type JournalEntry, type Person } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";

/** Company mode: turn it on, companies (each with its own money data), people with roles and PINs, the journal. */
export default function CompanyTab(props: { token: string; t: Strings; onNote: (s: string) => void; onState: (s: CompanyState) => void }) {
  const { token, t, onNote, onState } = props;
  const [state, setState] = useState<CompanyState | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [journal, setJournal] = useState<{ entries: JournalEntry[]; intact: boolean; check: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [on, setOn] = useState({ name: "", pin: "", pin2: "" });
  const [ws, setWs] = useState("");
  const [person, setPerson] = useState({ name: "", role: "member", pin: "", workspaces: [] as string[] });
  const [off, setOff] = useState("");

  const api = useCallback(() => new VaelonApi(token), [token]);
  const load = useCallback(async () => {
    try {
      const s = await api().company();
      setState(s);
      onState(s);
      if (s.enabled && s.perms.includes("users.manage")) {
        const r = await api().companyAct({ action: "people" });
        if (r.ok && r.people) setPeople(r.people);
      }
      if (s.enabled && s.perms.includes("journal.read")) setJournal(await api().journal());
    } catch {
      onNote(t.companyFail);
    }
  }, [api, onNote, onState, t.companyFail]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (body: Record<string, unknown>, okNote: string) => {
    setBusy(true);
    let ok = false;
    try {
      const r = await api().companyAct(body);
      ok = r.ok;
      onNote(r.ok ? okNote : r.error || t.companyFail);
      await load();
    } catch {
      onNote(t.companyFail);
    }
    setBusy(false);
    return ok;
  };

  if (!state) return <p className="muted scan">{t.loading}</p>;

  if (!state.enabled)
    return (
      <form className="calform" onSubmit={(e) => {
        e.preventDefault();
        if (on.pin !== on.pin2) return onNote(t.companyPinsDiffer);
        void act({ action: "enable", name: on.name, pin: on.pin }, t.companyOnNote).then((ok) => ok && setOn({ name: "", pin: "", pin2: "" }));
      }}>
        <p className="small">{t.companyIntro}</p>
        <p className="muted small">{t.companyLimit}</p>
        <input aria-label={t.companyYourName} placeholder={t.companyYourName} maxLength={60} value={on.name}
          onChange={(e) => setOn({ ...on, name: e.target.value })} />
        <div className="calrow">
          <input type="password" inputMode="numeric" autoComplete="new-password" maxLength={8} aria-label={t.companyPin}
            placeholder={t.companyPin} value={on.pin} onChange={(e) => setOn({ ...on, pin: e.target.value.replace(/\D/g, "") })} />
          <input type="password" inputMode="numeric" autoComplete="new-password" maxLength={8} aria-label={t.companyPin2}
            placeholder={t.companyPin2} value={on.pin2} onChange={(e) => setOn({ ...on, pin2: e.target.value.replace(/\D/g, "") })} />
          <button type="submit" className="btn" disabled={busy || on.pin.length < 4 || !on.name.trim()}>{t.companyTurnOn}</button>
        </div>
      </form>
    );

  const manage = state.perms.includes("users.manage");
  const roleName = (r: string) => t.roles[r as keyof typeof t.roles] ?? r;
  const companies = state.workspaces;
  return (
    <>
      <p className="billtotal">
        {t.companySignedIn}: <b>{state.user?.name}</b> ({roleName(state.user?.role ?? "")}) · {t.companyOpen}: <b>{state.workspace.name}</b>
      </p>

      <h4 className="budhead">{t.companyCompanies}</h4>
      {companies.map((w) => (
        <div key={w.id} className={`billrow ${w.id === state.workspace.id ? "" : "void-not"}`}>
          <span className="billwho">{w.id === "personal" ? t.companyPersonal : w.name}</span>
          {w.id === state.workspace.id ? (
            <span className="muted small">{t.companyIsOpen}</span>
          ) : (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act({ action: "switch", id: w.id }, t.companyOpened)}>
              {t.companyOpenIt}
            </button>
          )}
        </div>
      ))}
      {manage && (
        <form className="calrow budlimit" onSubmit={(e) => {
          e.preventDefault();
          if (!ws.trim()) return;
          void act({ action: "add_workspace", name: ws }, t.companyAdded).then((ok) => ok && setWs(""));
        }}>
          <input aria-label={t.companyNewName} placeholder={t.companyNewName} maxLength={80} value={ws} onChange={(e) => setWs(e.target.value)} />
          <button type="submit" className="btn ghost" disabled={busy || !ws.trim()}>{t.companyAdd}</button>
        </form>
      )}

      {manage && (
        <>
          <h4 className="budhead">{t.companyPeople}</h4>
          {people.map((p) => (
            <div key={p.id} className="billrow">
              <span className="billwho">{p.name}<em> · {roleName(p.role)}</em></span>
              <span className="muted small">
                {p.workspaces.includes("*") ? t.companyAll : p.workspaces.map((id) => companies.find((w) => w.id === id)?.name ?? "?").join(", ")}
              </span>
              {p.role !== "owner" && (
                <button type="button" className="x" aria-label={`${t.chatDelete}: ${p.name}`}
                  onClick={() => void act({ action: "remove_user", id: p.id }, t.companyRemoved)}>✕</button>
              )}
            </div>
          ))}
          <form className="calform" onSubmit={(e) => {
            e.preventDefault();
            void act({ action: "add_user", ...person }, t.companyPersonAdded).then((ok) => ok && setPerson({ name: "", role: "member", pin: "", workspaces: [] }));
          }}>
            <div className="calrow">
              <input aria-label={t.companyPersonName} placeholder={t.companyPersonName} maxLength={60} value={person.name}
                onChange={(e) => setPerson({ ...person, name: e.target.value })} />
              <select aria-label={t.companyRole} value={person.role} onChange={(e) => setPerson({ ...person, role: e.target.value })}>
                {state.roles.filter((r) => r !== "owner").map((r) => <option key={r} value={r}>{roleName(r)}</option>)}
              </select>
              <input type="password" inputMode="numeric" autoComplete="new-password" maxLength={8} className="narrow"
                aria-label={t.companyPin} placeholder={t.companyPin} value={person.pin}
                onChange={(e) => setPerson({ ...person, pin: e.target.value.replace(/\D/g, "") })} />
            </div>
            <div className="calrow wrap">
              {companies.filter((w) => w.id !== "personal").map((w) => (
                <label key={w.id} className="check">
                  <input type="checkbox" checked={person.workspaces.includes(w.id)} onChange={(e) =>
                    setPerson({ ...person, workspaces: e.target.checked ? [...person.workspaces, w.id] : person.workspaces.filter((x) => x !== w.id) })} />
                  {w.name}
                </label>
              ))}
              <span className="grow" />
              <button type="submit" className="btn" disabled={busy || !person.name.trim() || person.pin.length < 4 || !person.workspaces.length}>
                {t.companyAddPerson}
              </button>
            </div>
            <p className="muted small">{t.companyRolesHelp}</p>
          </form>
          <label className="check">
            <input type="checkbox" checked={state.lock_on_start} disabled={busy}
              onChange={(e) => void act({ action: "lock_on_start", on: e.target.checked }, t.saved)} />
            {t.companyLockOnStart}
          </label>
        </>
      )}

      {journal && (
        <>
          <h4 className="budhead">{t.journal}</h4>
          <p className={`small ${journal.intact ? "good" : "bad"}`}>{journal.intact ? t.journalIntact : t.journalBroken}: {journal.check}</p>
          <div className="journal">
            {journal.entries.slice(0, 150).map((e, i) => (
              <div key={i} className="jrow">
                <span className="mono">{e.t.slice(5, 16)}</span>
                <span>{e.who}</span>
                <b>{e.action}</b>
                <span className="muted">{e.detail}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {state.user?.role === "owner" && (
        <form className="calrow budlimit" onSubmit={(e) => {
          e.preventDefault();
          void act({ action: "disable", pin: off }, t.companyOffNote).then(() => setOff(""));
        }}>
          <input type="password" inputMode="numeric" autoComplete="off" maxLength={8} className="narrow" aria-label={t.companyPin}
            placeholder={t.companyPin} value={off} onChange={(e) => setOff(e.target.value.replace(/\D/g, ""))} />
          <button type="submit" className="btn ghost" disabled={busy || off.length < 4}>{t.companyTurnOff}</button>
        </form>
      )}
    </>
  );
}
