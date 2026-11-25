"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { VaelonApi, type LocalModel, type LocalModels, type PullStatus, type Settings } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";
import GetOllama from "./GetOllama";

const gb = (n: number) => (n / 1e9).toFixed(n >= 1e9 ? 1 : 2);

/** Pick the local model: a short curated list, this computer's memory / processor / graphics, and for each model what
 *  it is good for, how much it needs, whether it fits and roughly how fast it will feel. Download and switch in place.
 *  The core decides what may be downloaded (only models from this list); nothing here names another model. */
export default function ModelPicker({ token, t, isLocal, current, onChanged }: {
  token: string; t: Strings; isLocal: boolean; current: string; onChanged: (fresh: Settings) => void;
}) {
  const [data, setData] = useState<LocalModels | null>(null);
  const [pull, setPull] = useState<PullStatus | null>(null);
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const [note, setNote] = useState("");
  const handled = useRef("");
  const changedRef = useRef(onChanged);
  useEffect(() => {
    changedRef.current = onChanged;
  });

  const load = useCallback(async () => {
    try {
      const next = await new VaelonApi(token).localModels();
      setData(next);
      return next;
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "error");
      return null;
    }
  }, [token]);

  useEffect(() => {
    void load(); // again whenever the model in use changes elsewhere (the model box in Settings)
  }, [load, current]);

  useEffect(() => {
    void new VaelonApi(token).pullStatus().then((s) => s.running && setPull(s)).catch(() => undefined);
  }, [token]);

  const use = useCallback(async (name: string) => {
    setBusy(name);
    setProblem("");
    setNote("");
    try {
      // switching from a cloud model also switches to the local provider; an explicit model wins after the provider
      const r = await new VaelonApi(token).saveSettings(isLocal ? { model: name } : { provider: "local", model: name });
      if (!r.ok) throw new Error(r.error || t.settingsFail);
      await load();
      changedRef.current(r.settings);
      setNote(t.pickerNowUsing.replace("{name}", name));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : t.settingsFail);
    }
    setBusy("");
  }, [token, isLocal, load, t.settingsFail, t.pickerNowUsing]);

  const running = pull?.running ? pull.model : "";
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(async () => {
      try {
        const s = await new VaelonApi(token).pullStatus(running);
        if (!s.running) {
          if (handled.current === running) return; // a slow earlier tick already took care of this download
          handled.current = running;
        }
        setPull(s);
        if (!s.running) {
          const fresh = await load();
          // switch only when nothing local works yet (the model in use - any name, also one outside the list - is
          // missing, or a cloud model is in use); otherwise the download is just there to choose later
          if (s.done && fresh && (!isLocal || !fresh.in_use_installed)) await use(running);
          else if (s.error) setProblem(s.error);
        }
      } catch {
        /* try again on the next tick */
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [running, token, load, use, isLocal]);

  const download = async (name: string) => {
    setProblem("");
    setNote("");
    handled.current = "";
    try {
      const r = await new VaelonApi(token).pullModel(name);
      if (r.error && !r.running) setProblem(r.error);
      setPull(r);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "error");
    }
  };

  if (!data) {
    return problem ? <p className="small bad" role="status">{problem}</p>
      : <p className="muted small" role="status">{t.pickerLooking}</p>;
  }
  const m = data.machine;
  const gfx = m.graphics.map((g) => `${g.name}${g.kind === "integrated" ? ` (${t.pickerBuiltIn})` : g.vram_gb >= 1 ? ` (${g.vram_gb} GB)` : ""}`);

  return (
    <div className="picker">
      {data.remote ? <p className="muted small">{t.pickerRemote}</p> : (
        <p className="muted small">
          {t.pickerThisComputer}: {m.memory_gb} GB {t.pickerMemory} ({m.free_gb} GB {t.pickerFree}) · {m.processor}
          {gfx.length ? ` · ${gfx.join(", ")}` : ""}
        </p>
      )}
      {!data.ollama.reachable && (
        <div className="row-actions">
          <span className="small bad">{t.ollamaOff}</span>
          <GetOllama t={t} />
        </div>
      )}
      <ul className="picker-list">
        {data.models.map((x) => (
          <ModelRow key={x.name} x={x} t={t} pull={pull} busy={busy} reachable={data.ollama.reachable} remote={data.remote}
            onDownload={() => void download(x.name)} onUse={() => void use(x.name)} anotherRunning={!!running && running !== x.name} />
        ))}
      </ul>
      {problem && <p className="small bad" role="status">{problem}</p>}
      {note && !problem && <p className="small good" role="status">{note}</p>}
      {!data.remote && <p className="muted small">{t.pickerEstimate.replace("{gb}", String(data.overhead_gb))}</p>}
    </div>
  );
}

function ModelRow({ x, t, pull, busy, reachable, remote, onDownload, onUse, anotherRunning }: {
  x: LocalModel; t: Strings; pull: PullStatus | null; busy: string; reachable: boolean; remote: boolean;
  onDownload: () => void; onUse: () => void; anotherRunning: boolean;
}) {
  const mine = pull?.running && pull.model === x.name ? pull : null;
  const fit = x.fit === "too_big" ? t.fitTooBig : x.fit === "tight" ? t.fitTight : t.fitOk;
  const speed = { fast: t.speedFast, usable: t.speedUsable, slow: t.speedSlow, very_slow: t.speedVerySlow }[x.speed];
  return (
    <li className={`picker-row ${x.in_use ? "on" : ""}`}>
      <div className="picker-head">
        <b>{x.name}</b>
        {x.recommended && !remote && <span className="risk safe">{t.pickerRecommended}</span>}
        {x.in_use && <span className="risk reversible">{t.pickerInUse}</span>}
        {x.vision && <span className="pill-tag">{t.pickerPictures}</span>}
      </div>
      <p className="small">{x.good_for}</p>
      <p className="muted small">
        {t.pickerSize.replace("{size}", String(x.size_gb)).replace("{need}", String(x.need_gb))}
        {!remote && <> · <span className={x.fit === "ok" ? "good" : "bad"}>{fit}</span> · {speed}</>}
      </p>
      {mine ? (
        <div className="pull">
          <div className="pull-bar" role="progressbar" aria-label={`${t.downloadingModel} ${x.name}`} aria-valuemin={0}
            aria-valuemax={100} aria-valuenow={mine.total ? Math.floor(mine.percent) : undefined}
            aria-valuetext={mine.total ? `${Math.floor(mine.percent)}%` : mine.status}>
            <i style={{ width: `${mine.percent}%` }} />
          </div>
          <p className="muted small">
            {t.downloadingModel} · {mine.total ? `${gb(mine.completed)} / ${gb(mine.total)} GB (${Math.floor(mine.percent)}%)` : mine.status}
          </p>
        </div>
      ) : x.in_use && x.installed ? null : x.installed ? (
        <button type="button" className="btn ghost" disabled={!!busy} onClick={onUse} aria-label={`${t.pickerUse} ${x.name}`}>
          {t.pickerUse}
        </button>
      ) : (
        <button type="button" className="btn" disabled={!reachable || anotherRunning || (!remote && x.fit === "too_big")}
          onClick={onDownload} aria-label={`${t.downloadModel} ${x.name}`}
          title={!remote && x.fit === "too_big" ? t.fitTooBig : undefined}>
          {t.downloadModel}
        </button>
      )}
    </li>
  );
}
