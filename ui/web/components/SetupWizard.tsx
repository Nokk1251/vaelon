"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { VaelonApi, type KeyRow, type Settings } from "@/lib/vaelonApi";
import { STRINGS, type Lang } from "@/lib/i18n";
import { KeyField } from "./SettingsPanel";
import ProfilePicker from "./ProfilePicker";
import GetOllama from "./GetOllama";
import ModelPicker from "./ModelPicker";

const STEPS = 5; // name, brain, profiles (optional), extra keys, ready
/** Shown once, on a brand-new installation: a name, where the thinking happens (this PC or a cloud model with the
 *  user's own key), optional extras. Every step can be skipped; everything is in Settings afterwards. */
export default function SetupWizard(props: { token: string; lang: Lang; first: Settings; onDone: (note: string) => void }) {
  const { token, lang, first, onDone } = props;
  const t = STRINGS[lang];
  const [s, setS] = useState<Settings>(first);
  const [step, setStep] = useState(0);
  const [name, setName] = useState(first.address_as);
  const [where, setWhere] = useState<"local" | "cloud">(first.local ? "local" : "cloud");
  const [cloud, setCloud] = useState(first.preset && first.preset !== "local" ? first.preset : "groq");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  // a slow background check must not overwrite what a later save already showed: every request and save gets a
  // number, and an answer that is no longer the newest is dropped
  const gen = useRef(0);

  const refresh = useCallback(
    async (probe = true) => {
      const mine = ++gen.current;
      try {
        const next = await new VaelonApi(token).settings(probe);
        if (mine !== gen.current) return;
        setS((old) => ({ ...next, ollama: next.ollama ?? old.ollama }));
      } catch {
        /* keep what we have */
      }
    },
    [token],
  );

  useEffect(() => {
    void refresh(true);
  }, [refresh]);

  // the model that will really be used (and downloaded): the chosen local one, else the local preset's
  const localModel = s.ollama_used && s.model ? s.model : s.presets.find((p) => p.name === "local")?.model ?? "";
  const ollamaReady = !!s.ollama?.reachable && s.ollama.models.includes(localModel);
  // while the user installs Ollama or downloads the model, look again by itself every 5 s (only on this step)
  const waitingForOllama = step === 1 && where === "local" && !ollamaReady;
  useEffect(() => {
    if (!waitingForOllama) return;
    const id = window.setInterval(() => void refresh(true), 5000);
    return () => window.clearInterval(id);
  }, [waitingForOllama, refresh]);

  const finish = async (note: string) => {
    setBusy(true);
    try {
      await new VaelonApi(token).saveSettings({ setup_done: true });
    } catch {
      /* the setup will simply be offered again next time */
    }
    onDone(note);
  };

  const next = async () => {
    setProblem("");
    setBusy(true);
    try {
      const api = new VaelonApi(token);
      if (step === 0 && name.trim() && name.trim() !== s.address_as) {
        gen.current++;
        const r = await api.saveSettings({ address_as: name.trim() });
        if (!r.ok) throw new Error(r.error || t.settingsFail);
        setS((old) => ({ ...r.settings, ollama: old.ollama }));
      }
      if (step === 1) {
        const want = where === "local" ? "local" : cloud;
        // any Ollama counts as local: switching again would put back the preset's model (and address) and lose the
        // model the user just picked
        if (where === "local" ? !s.ollama_used : want !== s.preset) {
          gen.current++;
          const r = await api.saveSettings({ provider: want });
          if (!r.ok) throw new Error(r.error || t.settingsFail);
          setS((old) => ({ ...r.settings, ollama: old.ollama }));
        }
      }
      if (step === STEPS - 1) return void (await finish(t.setupDoneNote));
      setStep(step + 1);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : t.settingsFail);
    }
    setBusy(false);
  };

  const pickProfiles = async (names: string[]) => {
    setBusy(true);
    setProblem("");
    try {
      gen.current++;
      const r = await new VaelonApi(token).saveSettings({ profiles: names });
      if (!r.ok) throw new Error(r.error || t.settingsFail);
      setS((old) => ({ ...r.settings, ollama: old.ollama }));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : t.settingsFail);
    }
    setBusy(false);
  };

  const onKeys = (keys: KeyRow[]) => {
    setS((old) => ({ ...old, keys }));
    void refresh(false);
  };

  const chosen = s.presets.find((p) => p.name === cloud);
  const chosenKey = s.keys.find((k) => k.name === chosen?.key);
  const blocked = step === 1 && where === "cloud" && !chosen?.key_set;

  return (
    <div className="wizard-wrap">
      <section className="wizard" role="dialog" aria-label={t.setupTitle}>
        <header>
          <span className="panel-title">{t.setupTitle}</span>
          <span className="dots" aria-hidden>
            {Array.from({ length: STEPS }, (_, i) => (
              <i key={i} className={i === step ? "on" : i < step ? "past" : ""} />
            ))}
          </span>
        </header>

        {step === 0 && (
          <div className="wizard-body">
            <h2>{t.setupHello}</h2>
            <p>{t.setupIntro}</p>
            <p className="muted">{t.privacyNote}</p>
            <label className="field wide">
              <span>{t.setupName}</span>
              <input autoFocus maxLength={40} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
          </div>
        )}

        {step === 1 && (
          <div className="wizard-body">
            <h2>{t.setupBrain}</h2>
            <div className="cards two">
              <button type="button" className={`card ${where === "local" ? "on" : ""}`} onClick={() => setWhere("local")}>
                <b>{t.setupLocal}</b>
                <span className="risk safe">{t.local}</span>
                <em>{t.setupLocalNote}</em>
              </button>
              <button type="button" className={`card ${where === "cloud" ? "on" : ""}`} onClick={() => setWhere("cloud")}>
                <b>{t.setupCloud}</b>
                <span className="risk reversible">{t.cloud}</span>
                <em>{t.setupCloudNote}</em>
              </button>
            </div>
            {where === "local" && (
              <>
                {s.ollama?.reachable ? (
                  <>
                    {ollamaReady ? (
                      <p className="small good">{t.ollamaReady} ({localModel})</p>
                    ) : (
                      <p className="small bad">{t.ollamaNoModel}</p>
                    )}
                    <ModelPicker token={token} t={t} isLocal={!!s.ollama_used} current={s.model} onChanged={(fresh) => {
                      gen.current++;
                      setS((old) => ({ ...fresh, ollama: old.ollama }));
                      void refresh(true);
                    }} />
                  </>
                ) : (
                  <>
                    <p className="small bad">{t.ollamaOff}</p>
                    <div className="row-actions">
                      <GetOllama t={t} />
                      <button type="button" className="btn ghost" disabled={busy} onClick={() => void refresh(true)}>
                        {t.checkAgain}
                      </button>
                    </div>
                    <p className="muted small">{t.ollamaWatching}</p>
                  </>
                )}
              </>
            )}
            {where === "cloud" && (
              <>
                <div className="pills">
                  {s.presets.filter((p) => p.cloud).map((p) => (
                    <button key={p.name} type="button" className={`pill ${cloud === p.name ? "on" : ""}`} onClick={() => setCloud(p.name)}>
                      {p.name}
                      {p.key_set ? " ✓" : ""}
                    </button>
                  ))}
                </div>
                {chosen && (
                  <p className="small">
                    <b>{chosen.name}</b>: {chosen.note} · {t.model} <code>{chosen.model}</code>
                  </p>
                )}
                {chosenKey && <KeyField key={chosenKey.name} token={token} row={chosenKey} t={t} onKeys={onKeys} />}
                <p className="muted small">{t.setupCloudWarn}</p>
              </>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="wizard-body">
            <h2>{t.setupProfiles}</h2>
            <p className="muted">{t.profilesNote}</p>
            <ProfilePicker profiles={s.profiles ?? []} busy={busy} onChange={(names) => void pickProfiles(names)} />
          </div>
        )}

        {step === 3 && (
          <div className="wizard-body">
            <h2>{t.setupExtras}</h2>
            <p className="muted">{t.setupExtrasNote}</p>
            <div className="scrollbox">
              {s.keys.filter((k) => !k.provider).map((k) => (
                <KeyField key={k.name} token={token} row={k} t={t} onKeys={onKeys} />
              ))}
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="wizard-body">
            <h2>{t.setupReady}</h2>
            <p>
              {t.model}: <code>{s.model}</code> <span className={`risk ${s.local ? "safe" : "reversible"}`}>{s.local ? t.local : t.cloud}</span>
            </p>
            <p className="muted">{s.local ? t.brainLocal : t.brainCloud}</p>
            <p>{t.setupTry}</p>
            <p className="muted">{t.setupLater}</p>
          </div>
        )}

        {problem && <p className="small bad">{problem}</p>}
        <footer>
          <button type="button" className="btn ghost" disabled={busy} onClick={() => void finish(t.setupSkipped)}>
            {t.setupSkip}
          </button>
          <span className="grow" />
          {step > 0 && (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => setStep(step - 1)}>
              {t.back}
            </button>
          )}
          <button type="button" className="btn" disabled={busy || blocked} title={blocked ? t.needKeyFirst : ""} onClick={() => void next()}>
            {step === STEPS - 1 ? t.setupFinish : t.next}
          </button>
        </footer>
      </section>
    </div>
  );
}
