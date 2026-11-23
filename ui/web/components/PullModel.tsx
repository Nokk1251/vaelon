"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { VaelonApi, type PullStatus } from "@/lib/vaelonApi";

type T = { downloadModel: string; downloadingModel: string; modelReadyNow: string; downloadAgain: string };

const gb = (n: number) => (n / 1e9).toFixed(n >= 1e9 ? 1 : 2);

/** Download the local model with one click: the core asks the user's own Ollama to pull it and this shows the progress.
 *  The model is always the one Vaelon is set to use - this component never names one. */
export default function PullModel({ token, t, onDone }: { token: string; t: T; onDone: () => void }) {
  const [s, setS] = useState<PullStatus | null>(null);
  const [problem, setProblem] = useState("");
  const doneRef = useRef(onDone);
  useEffect(() => {
    doneRef.current = onDone;
  });

  const look = useCallback(async () => {
    try {
      const next = await new VaelonApi(token).pullStatus();
      setS(next);
      return next;
    } catch {
      return null;
    }
  }, [token]);

  useEffect(() => {
    void look(); // a download started earlier (another window, before a restart of the screen) is shown at once
  }, [look]);

  const running = !!s?.running;
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(async () => {
      const next = await look();
      if (next && !next.running && next.done) doneRef.current();
    }, 1000);
    return () => window.clearInterval(id);
  }, [running, look]);

  const start = async () => {
    setProblem("");
    try {
      const r = await new VaelonApi(token).pullModel();
      if (r.error && !r.running) setProblem(r.error);
      setS(r);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "error");
    }
  };

  if (s?.done && !running) return <p className="small good" role="status">{t.modelReadyNow}</p>;
  if (running && s) {
    return (
      <div className="pull">
        <div className="pull-bar" role="progressbar" aria-label={`${t.downloadingModel} ${s.model}`} aria-valuemin={0}
          aria-valuemax={100} aria-valuenow={s.total ? Math.floor(s.percent) : undefined}
          aria-valuetext={s.total ? `${Math.floor(s.percent)}%` : s.status}>
          <i style={{ width: `${s.percent}%` }} />
        </div>
        <p className="muted small">
          {t.downloadingModel} {s.model} · {s.total ? `${gb(s.completed)} / ${gb(s.total)} GB (${Math.floor(s.percent)}%)` : s.status}
        </p>
      </div>
    );
  }
  return (
    <div className="row-actions">
      <button type="button" className="btn" onClick={() => void start()}>
        {s?.error ? t.downloadAgain : t.downloadModel}
      </button>
      {(problem || s?.error) && <span className="small bad" role="status">{problem || s?.error}</span>}
    </div>
  );
}
