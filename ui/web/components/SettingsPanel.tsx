"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { VaelonApi, type KeyRow, type ModelPreset, type Settings, type SettingsChange } from "@/lib/vaelonApi";
import { STRINGS, type Lang, type Strings } from "@/lib/i18n";
import GetOllama from "./GetOllama";
import ProfilePicker from "./ProfilePicker";
import { readPrefs, writePrefs, type Prefs } from "@/lib/prefs";

/** A small "?" that opens the Help page at one section (the screens stay short, the details live there). */
export function HelpLink({ section, t }: { section: string; t: Strings }) {
  return (
    <button type="button" className="helplink" title={t.helpMore} aria-label={t.helpMore}
      onClick={() => window.dispatchEvent(new CustomEvent("vaelon-help", { detail: section }))}>
      ?
    </button>
  );
}

/** One API key: a password box that hands the key to the core and forgets it at once. Nothing is ever read back. */
export function KeyField(props: { token: string; row: KeyRow; t: Strings; onKeys: (keys: KeyRow[]) => void;
  plain?: string }) {
  const { token, row, t, onKeys, plain } = props; // plain: an address or number, not a secret - typed visibly
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const save = async () => {
    const key = value;
    setValue(""); // the key leaves this page's memory whether or not the core accepts it
    if (!key.trim()) return;
    setBusy(true);
    try {
      const r = await new VaelonApi(token).setKey(row.name, key);
      setMsg(r.ok ? { ok: true, text: t.keySaved } : { ok: false, text: r.error || t.keyFail });
      if (r.keys) onKeys(r.keys);
    } catch {
      setMsg({ ok: false, text: t.keyFail });
    }
    setBusy(false);
  };

  const remove = async () => {
    if (!window.confirm(`${t.keyRemove} ${row.name}?`)) return; // a stored key cannot be shown or brought back
    setBusy(true);
    try {
      const r = await new VaelonApi(token).deleteKey(row.name);
      setMsg(r.ok ? { ok: true, text: t.keyRemoved } : { ok: false, text: t.keyFail });
      if (r.keys) onKeys(r.keys);
    } catch {
      setMsg({ ok: false, text: t.keyFail });
    }
    setBusy(false);
  };

  return (
    <div className="keyrow">
      <div className="keyhead">
        <span className={`risk ${row.set ? "safe" : ""}`}>{row.set ? t.keySet : t.keyMissing}</span>
        <code>{row.name}</code>
        {row.age_days !== null && row.age_days >= 90 && <span className="risk reversible">{t.keyOld}</span>}
      </div>
      <p>
        {row.what} <span className="url">{row.url}</span>
      </p>
      <form
        className="keyform"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <input
          type={plain ? "text" : "password"}
          name={`vaelon-${row.name.toLowerCase()}`}
          autoComplete="new-password"
          data-lpignore="true"
          data-1p-ignore="true"
          spellCheck={false}
          aria-label={row.name}
          placeholder={plain ?? (row.set ? t.keyReplace : t.keyPaste)}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button type="submit" className="btn" disabled={busy || !value.trim()}>
          {t.save}
        </button>
        {row.stored && (
          <button type="button" className="btn ghost" disabled={busy} onClick={() => void remove()}>
            {t.keyRemove}
          </button>
        )}
      </form>
      {row.set && !row.stored && <p className="muted small">{t.keyFromEnv}</p>}
      {msg && <p className={`small ${msg.ok ? "good" : "bad"}`}>{msg.text}</p>}
    </div>
  );
}

/** The model providers as cards. A cloud one can be picked only when its key is stored. */
export function BrainCards(props: { presets: ModelPreset[]; current: string | null; t: Strings; busy: boolean;
  onPick: (name: string) => void }) {
  const { presets, current, t, busy, onPick } = props;
  return (
    <div className="cards">
      {presets.map((p) => (
        <button
          key={p.name}
          type="button"
          className={`card ${current === p.name ? "on" : ""}`}
          disabled={busy || (p.cloud && !p.key_set)}
          title={p.cloud && !p.key_set ? t.needKeyFirst : ""}
          onClick={() => onPick(p.name)}
        >
          <b>{p.name}</b>
          <span className={`risk ${p.cloud ? "reversible" : "safe"}`}>{p.cloud ? t.cloud : t.local}</span>
          <em>{p.note}</em>
          {p.cloud && !p.key_set && <i>{t.needKey}: {p.key}</i>}
        </button>
      ))}
    </div>
  );
}

export default function SettingsPanel(props: { token: string; lang: Lang; onClose: () => void; onNote: (s: string) => void }) {
  const { token, lang, onClose, onNote } = props;
  const t = STRINGS[lang];
  const [s, setS] = useState<Settings | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [models, setModels] = useState<string[] | null>(null);
  const [cap, setCap] = useState("");
  const [prefs, setPrefs] = useState<Prefs>(() => readPrefs());
  const flip = (k: keyof Prefs) => {
    const next = { ...prefs, [k]: !prefs[k] };
    setPrefs(next);
    writePrefs(next);
  };

  const saved = useRef<Settings | null>(null);

  const take = useCallback((next: Settings) => {
    const old = saved.current;
    saved.current = next;
    setS((prev) => ({ ...next, ollama: next.ollama ?? prev?.ollama }));
    // a refresh (after another setting or a key was saved) must not wipe what is being typed right now
    setName((cur) => (old && cur !== old.address_as && next.address_as === old.address_as ? cur : next.address_as));
    setCap((cur) => (old && cur !== String(old.elevenlabs_monthly_chars)
      && next.elevenlabs_monthly_chars === old.elevenlabs_monthly_chars ? cur : String(next.elevenlabs_monthly_chars)));
  }, []);

  useEffect(() => {
    new VaelonApi(token)
      .settings(true)
      .then(take)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : "error"));
  }, [token, take]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const change = async (changes: SettingsChange, done?: string) => {
    setBusy(true);
    try {
      const r = await new VaelonApi(token).saveSettings(changes);
      if (r.ok) {
        take(r.settings);
        if ("provider" in changes) setModels(null);
        onNote(done ?? t.settingsSaved);
      } else onNote(r.error || t.settingsFail);
    } catch {
      onNote(t.settingsFail);
    }
    setBusy(false);
  };

  const onKeys = (keys: KeyRow[]) => {
    // a new key may unlock a provider or a voice: read the whole state again
    setS((old) => (old ? { ...old, keys } : old));
    void new VaelonApi(token).settings().then(take).catch(() => undefined);
  };

  const loadModels = async () => {
    setBusy(true);
    try {
      const r = await new VaelonApi(token).models();
      setModels(r.models);
      if (r.error) onNote(r.error);
    } catch {
      onNote(t.settingsFail);
    }
    setBusy(false);
  };

  const providerKeys = s?.keys.filter((k) => k.provider) ?? [];
  const COMM = ["VAELON_SMTP_USER", "VAELON_SMTP_PASS", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"];
  const otherKeys = s?.keys.filter((k) => !k.provider && !COMM.includes(k.name)) ?? [];
  const commKey = (name: string) => s?.keys.find((k) => k.name === name);
  const pick = (provider: string) => {
    const p = s?.presets.find((x) => x.name === provider);
    void change({ provider }, p?.cloud ? `${t.nowCloud} ${provider}.` : t.nowLocal);
  };

  return (
    <div className="panel-wrap" onClick={onClose}>
      <aside className="panel settings" role="dialog" aria-label={t.settings} onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <span className="panel-title">{t.settings}</span>
          {s && (
            <span className="panel-sub">
              {t.model} {s.model} ({s.local ? t.local : t.cloud}) · v{s.version}
            </span>
          )}
          <button className="x" onClick={onClose} aria-label={t.close}>
            ✕
          </button>
        </div>
        <div className="panel-body">
          {err && <p className="muted">{t.settingsFail}: {err}</p>}
          {!s && !err && <p className="muted scan">{t.loading}</p>}
          {s && (
            <>
              <h3>{t.setYou}</h3>
              <form
                className="keyform"
                onSubmit={(e) => {
                  e.preventDefault();
                  void change({ address_as: name });
                }}
              >
                <input aria-label={t.setName} maxLength={40} value={name} onChange={(e) => setName(e.target.value)} />
                <button type="submit" className="btn" disabled={busy || !name.trim() || name.trim() === s.address_as}>
                  {t.save}
                </button>
              </form>

              <h3>{t.setProfiles} <HelpLink section="profiles" t={t} /></h3>
              <p className="muted">{t.profilesNote}</p>
              <ProfilePicker profiles={s.profiles} busy={busy}
                onChange={(names) => void change({ profiles: names }, names.length ? t.profilesSaved : t.profilesNone)} />

              <h3>{t.setLook}</h3>
              <label className="check">
                <input type="checkbox" checked={prefs.glitchVisual} onChange={() => flip("glitchVisual")} />
                <span>{t.lookGlitchVisual}</span>
              </label>
              <label className="check">
                <input type="checkbox" checked={prefs.glitchVoice} onChange={() => flip("glitchVoice")} />
                <span>{t.lookGlitchVoice}</span>
              </label>
              <label className="check">
                <input type="checkbox" checked={prefs.avatarDot} onChange={() => flip("avatarDot")} />
                <span>{t.lookDot}</span>
              </label>

              <h3>{t.setBrain} <HelpLink section="models" t={t} /></h3>
              <p className="muted">{s.local ? t.brainLocal : t.brainCloud}</p>
              <BrainCards presets={s.presets} current={s.preset} t={t} busy={busy} onPick={pick} />
              {s.preset === "local" && s.ollama && !s.ollama.reachable && (
                <>
                  <p className="small bad">{t.ollamaOff}</p>
                  <div className="row-actions">
                    <GetOllama t={t} />
                  </div>
                </>
              )}
              {s.preset === "local" && s.ollama?.reachable && !s.ollama.models.includes(s.model) && (
                <p className="small bad">
                  {t.ollamaNoModel} <code>ollama pull {s.model}</code>
                </p>
              )}
              <div className="keyform">
                {models ? (
                  <select aria-label={t.model} value={s.model} disabled={busy} onChange={(e) => void change({ model: e.target.value })}>
                    {[...new Set([s.model, ...models])].map((m) => (
                      <option key={m}>{m}</option>
                    ))}
                  </select>
                ) : (
                  <code className="grow">{s.model}</code>
                )}
                <button type="button" className="btn ghost" disabled={busy} onClick={() => void loadModels()}>
                  {t.otherModels}
                </button>
              </div>

              <h3>{t.setKeysModels}</h3>
              <p className="muted">{t.keysSafe}</p>
              {providerKeys.map((k) => (
                <KeyField key={k.name} token={token} row={k} t={t} onKeys={onKeys} />
              ))}

              <h3>{t.setKeysExtra}</h3>
              {otherKeys.map((k) => (
                <KeyField key={k.name} token={token} row={k} t={t} onKeys={onKeys} />
              ))}

              <h3>{t.setComms} <HelpLink section="comms" t={t} /></h3>
              <p className="muted">{t.commsNote}</p>
              <div className="row">
                <span className={`risk ${s.comms.email_ready ? "safe" : ""}`}>{s.comms.email_ready ? t.ready : t.notYet}</span>
                <code>{t.commsEmail}</code>
              </div>
              <label className="field">
                <span>{t.mailProvider}</span>
                <select value={s.comms.provider} disabled={busy}
                  onChange={(e) => e.target.value && e.target.value !== "custom" && void change({ mail_provider: e.target.value })}>
                  <option value="">-</option>
                  {s.comms.providers.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                  {s.comms.provider === "custom" && <option value="custom">{s.comms.smtp_host}</option>}
                </select>
              </label>
              {commKey("VAELON_SMTP_USER") && <KeyField token={token} row={commKey("VAELON_SMTP_USER")!} t={t} onKeys={onKeys} plain="you@example.com" />}
              {commKey("VAELON_SMTP_PASS") && <KeyField token={token} row={commKey("VAELON_SMTP_PASS")!} t={t} onKeys={onKeys} />}
              <p className="muted small">{t.mailHelp}</p>
              <div className="row">
                <span className={`risk ${s.comms.phone_ready ? "safe" : ""}`}>{s.comms.phone_ready ? t.ready : t.notYet}</span>
                <code>{t.commsPhone}</code>
              </div>
              {commKey("TWILIO_ACCOUNT_SID") && <KeyField token={token} row={commKey("TWILIO_ACCOUNT_SID")!} t={t} onKeys={onKeys} />}
              {commKey("TWILIO_AUTH_TOKEN") && <KeyField token={token} row={commKey("TWILIO_AUTH_TOKEN")!} t={t} onKeys={onKeys} />}
              {commKey("TWILIO_FROM") && <KeyField token={token} row={commKey("TWILIO_FROM")!} t={t} onKeys={onKeys} plain="+1 555 0100" />}
              <div className="row">
                <code>{t.contacts}</code>
                <p>{s.comms.contacts} · {t.contactsHint}</p>
              </div>

              <h3>{t.setVoice} <HelpLink section="voice" t={t} /></h3>
              <label className="field">
                <span>{t.engine}</span>
                <select value={s.tts_engine} disabled={busy} onChange={(e) => void change({ tts_engine: e.target.value })}>
                  <option value="auto">{t.engineAuto}</option>
                  <option value="piper">{t.enginePiper}</option>
                  <option value="sapi">{t.engineWindows}</option>
                  <option value="elevenlabs">{t.engineEleven}</option>
                </select>
              </label>
              <label className="field">
                <span>{t.setStt}</span>
                <select value={s.stt_engine} disabled={busy} onChange={(e) => void change({ stt_engine: e.target.value })}>
                  <option value="auto">{t.engineAuto}</option>
                  <option value="local">{t.sttLocal}</option>
                  <option value="groq">{t.sttGroq}</option>
                </select>
              </label>
              <form
                className="field"
                onSubmit={(e) => {
                  e.preventDefault();
                  const n = Number(cap);
                  if (Number.isInteger(n)) void change({ elevenlabs_monthly_chars: n });
                }}
              >
                <span>{t.setElevenCap}</span>
                <input inputMode="numeric" value={cap} onChange={(e) => setCap(e.target.value.replace(/\D/g, "").slice(0, 7))} />
                <button type="submit" className="btn ghost" disabled={busy || cap === String(s.elevenlabs_monthly_chars) || !cap}>
                  {t.save}
                </button>
              </form>
              <p className="muted small">{t.voiceCloudNote}</p>

              <h3>{t.setLearning} <HelpLink section="memory" t={t} /></h3>
              <label className="check">
                <input type="checkbox" checked={s.auto_learn} disabled={busy} onChange={(e) => void change({ auto_learn: e.target.checked })} />
                <span>{t.setLearnHint}</span>
              </label>

              <h3>{t.setData}</h3>
              <div className="row">
                <code>{t.setSearch}</code>
                <p>{s.search_sources.join(" → ")}</p>
              </div>
              <div className="row">
                <code>{t.setStocks}</code>
                <p>{s.stock_sources.join(" → ")}</p>
              </div>
              <div className="row">
                <code>{t.setFiles}</code>
                <p className="url">{s.output_dir}</p>
              </div>

              <h3>{t.setMcp} <HelpLink section="mcp" t={t} /></h3>
              {s.mcp.length ? (
                s.mcp.map((m) => (
                  <div key={m.name} className="row">
                    <span className={`risk ${m.trusted && m.enabled ? "safe" : m.trusted ? "" : "dangerous"}`}>
                      {!m.trusted ? t.mcpIgnored : m.enabled ? t.mcpOn : t.mcpOff}
                    </span>
                    <code>{m.name}</code>
                    <p>
                      {m.tools} {t.toolsN}
                    </p>
                  </div>
                ))
              ) : (
                <p className="muted">{t.mcpNone}</p>
              )}
              <p className="muted small">{t.mcpHint}</p>
              <pre className="cmd">vaelon mcp add files -- npx -y @modelcontextprotocol/server-filesystem C:\Users\you\Documents</pre>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
