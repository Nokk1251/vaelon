"use client";

import { useCallback, useEffect, useState } from "react";
import { VaelonApi, type LibraryFolder } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";

/** Settings > Your folders (issue #30): the folders whose documents Vaelon can search and answer from. The index is
 *  made and kept on this computer (encrypted); only folders inside the allowed folders can be added. */
export default function LibraryFolders({ token, t }: { token: string; t: Strings }) {
  const [rows, setRows] = useState<LibraryFolder[] | null>(null);
  const [allowed, setAllowed] = useState<string[]>([]);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await new VaelonApi(token).library();
      setRows(r.folders);
      setAllowed(r.allowed);
    } catch (e) {
      setRows([]);
      setProblem(e instanceof Error ? e.message : "error");
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (action: "add" | "remove" | "refresh", folder = "") => {
    setBusy(action + folder);
    setProblem("");
    setNote("");
    try {
      const r = await new VaelonApi(token).libraryAct(action, folder);
      if (!r.ok) throw new Error(r.error || t.settingsFail);
      setRows(r.folders ?? []);
      if (action === "add") {
        setPath("");
        const res = r.result as { files?: number; skipped?: number } | undefined;
        setNote(t.libAdded.replace("{files}", String(res?.files ?? 0)).replace("{skipped}", String(res?.skipped ?? 0)));
      } else if (action === "refresh") {
        const res = (r.result as { folders?: { folder: string; error?: string }[] } | undefined)?.folders ?? [];
        const bad = res.filter((x) => x.error);
        if (bad.length) setProblem(bad.map((x) => `${x.folder ? `${x.folder}: ` : ""}${x.error}`).join(" · "));
        else setNote(t.libRefreshed);
      }
    } catch (e) {
      setProblem(e instanceof Error ? e.message : t.settingsFail);
    }
    setBusy("");
  };

  return (
    <>
      <p className="muted small">{t.libIntro}</p>
      {rows === null ? (
        <p className="muted small" role="status">{t.pickerLooking}</p>
      ) : rows.length ? (
        rows.map((r) => (
          <div key={r.path} className="row">
            <code className="url">{r.path}</code>
            <p className="small">
              {t.libCounts.replace("{files}", String(r.files)).replace("{passages}", String(r.passages))
                .replace("{updated}", r.updated || "-")}
              {r.skipped ? ` · ${t.libSkipped.replace("{n}", String(r.skipped))}` : ""}
              {r.hidden ? ` · ${t.libHidden.replace("{n}", String(r.hidden))}` : ""}
            </p>
            {r.unavailable && <p className="small bad">{t.libUnavailable} {r.unavailable}</p>}
            {r.skipped_sample.length > 0 && (
              <details className="small muted">
                <summary>{t.libWhySkipped}</summary>
                <ul>{r.skipped_sample.map((s) => <li key={s}>{s}</li>)}</ul>
              </details>
            )}
            <button type="button" className="btn ghost" disabled={!!busy} onClick={() => void act("remove", r.path)}
              aria-label={`${t.libRemove} ${r.path}`}>
              {t.libRemove}
            </button>
          </div>
        ))
      ) : (
        <p className="muted small">{t.libEmpty}</p>
      )}
      <form className="keyform" onSubmit={(e) => { e.preventDefault(); if (path.trim()) void act("add", path.trim()); }}>
        <input value={path} onChange={(e) => setPath(e.target.value)} placeholder={allowed[0] ? `${allowed[0]}${allowed[0].includes("\\") ? "\\" : "/"}...` : t.libPath}
          aria-label={t.libPath} spellCheck={false} disabled={!!busy} />
        <button type="submit" className="btn" disabled={!!busy || !path.trim()}>
          {busy === "add" + path.trim() ? t.libReading : t.libAdd}
        </button>
      </form>
      {!!rows?.length && (
        <div className="row-actions">
          <button type="button" className="btn ghost" disabled={!!busy} onClick={() => void act("refresh")}>
            {busy === "refresh" ? t.libReading : t.libRefresh}
          </button>
        </div>
      )}
      {problem && <p className="small bad" role="status">{problem}</p>}
      {note && !problem && <p className="small good" role="status">{note}</p>}
      <p className="muted small">{t.libPrivacy}</p>
    </>
  );
}
