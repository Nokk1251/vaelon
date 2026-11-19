"use client";

import { useEffect, useState } from "react";
import { VaelonApi, type VoiceEngines, type VoiceProfile } from "@/lib/vaelonApi";
import { STRINGS, type Lang } from "@/lib/i18n";

const KNOBS: (keyof Omit<VoiceProfile, "preset">)[] = ["pitch", "speed", "metal", "robot", "radio", "echo", "space"];

export default function VoicePanel(props: {
  token: string;
  lang: Lang;
  onPlay: (blob: Blob) => void;
  onClose: () => void;
  onNote: (text: string) => void;
}) {
  const { token, lang, onPlay, onClose, onNote } = props;
  const t = STRINGS[lang];
  const [v, setV] = useState<VoiceProfile | null>(null);
  const [presets, setPresets] = useState<Record<string, Omit<VoiceProfile, "preset">>>({});
  const [limits, setLimits] = useState<Record<string, [number, number]>>({});
  const [busy, setBusy] = useState(false);
  const [engines, setEngines] = useState<VoiceEngines | null>(null);
  const [engine, setEngine] = useState("auto");
  const [sample, setSample] = useState(t.sample);
  useEffect(() => setSample(STRINGS[lang].sample), [lang]);

  useEffect(() => {
    new VaelonApi(token)
      .voice()
      .then((r) => {
        setV(r.voice);
        setPresets(r.presets);
        setLimits(r.limits);
        setEngines(r.engines);
        setEngine(r.engine);
      })
      .catch(() => onNote(STRINGS[lang].voiceFail));
  }, [token, onNote, lang]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const preview = async () => {
    if (!v) return;
    setBusy(true);
    try {
      onPlay(await new VaelonApi(token).preview(sample, v));
    } catch {
      onNote(t.noServerVoice);
    }
    setBusy(false);
  };

  const save = async () => {
    if (!v) return;
    try {
      await new VaelonApi(token).saveVoice(v, engine);
      onNote(t.saved);
      onClose();
    } catch {
      onNote(t.settingsFail);
    }
  };

  return (
    <div className="panel-wrap" onClick={onClose}>
      <aside className="panel voice" role="dialog" aria-label={t.voiceDesigner} onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <span className="panel-title">{t.voiceDesigner}</span>
          <span className="panel-sub">{t.designerSub}</span>
          <button className="x" onClick={onClose} aria-label={t.close}>
            ✕
          </button>
        </div>
        {!v ? (
          <p className="muted scan">{t.loading}</p>
        ) : (
          <div className="panel-body">
            <h3>{t.engine}</h3>
            <div className="pills">
              {(
                [
                  ["auto", t.engineAuto, true],
                  ["elevenlabs", t.engineEleven, !!engines?.elevenlabs],
                  ["piper", t.enginePiper, !!engines?.piper],
                  ["sapi", t.engineWindows, !!engines?.windows],
                ] as [string, string, boolean][]
              ).map(([id, label, ok]) => (
                <button
                  key={id}
                  disabled={!ok}
                  className={`pill ${engine === id ? "on" : ""}`}
                  onClick={async () => {
                    setEngine(id);
                    try {
                      if (v) setEngines((await new VaelonApi(token).saveVoice(v, id)).engines);
                    } catch {
                      onNote(t.settingsFail);
                    }
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            {engines && (
              <p className="muted">
                {t.nowSpeaking}: <b>{engines.speaking === "elevenlabs" ? t.engineEleven : engines.speaking === "piper" ? t.enginePiper : t.engineWindows}</b>
                {" · "}
                {engines.elevenlabs
                  ? `${t.elevenUsage}: ${engines.elevenlabs_used} / ${engines.elevenlabs_cap}`
                  : `ElevenLabs: ${t.elevenNoKey}`}
              </p>
            )}
            {engines?.speaking === "elevenlabs" && <p className="muted">{t.cleanTip}</p>}
            <h3>Style</h3>
            <div className="pills">
              {Object.keys(presets).map((name) => (
                <button
                  key={name}
                  className={`pill ${v.preset === name ? "on" : ""}`}
                  onClick={() => setV({ preset: name, ...presets[name] } as VoiceProfile)}
                >
                  {(t.presets as Record<string, string>)[name] ?? name}
                </button>
              ))}
            </div>
            {KNOBS.map((k) => {
              const [lo, hi] = limits[k] ?? [0, 1];
              const [label, hint] = t.knobs[k];
              return (
                <label key={k} className="knob">
                  <span>
                    {label} <em>{hint}</em>
                  </span>
                  <input
                    type="range"
                    min={lo}
                    max={hi}
                    step={0.01}
                    value={Number(v[k])}
                    onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })}
                  />
                  <b>{Number(v[k]).toFixed(2)}</b>
                </label>
              );
            })}
            <textarea className="sample" value={sample} onChange={(e) => setSample(e.target.value)} rows={2} />
            <div className="verdict-actions">
              <button className="deny" disabled={busy} onClick={() => void preview()}>
                {busy ? "…" : t.hear}
              </button>
              <button className="allow" onClick={() => void save()}>
                {t.save}
              </button>
            </div>
            <p className="muted">
              {t.cloudVoice} <code>vaelon key set ELEVENLABS_API_KEY</code> {t.and}{" "}
              <code>vaelon config tts_engine elevenlabs</code> {t.cloudVoiceNote}
            </p>
          </div>
        )}
      </aside>
    </div>
  );
}
