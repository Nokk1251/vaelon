"use client";

import { useState } from "react";
import { VaelonApi, type UpdateInfo } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";

/** Vaelon's own repository - the same as `__source__` in the core (a test keeps the two equal). */
export const REPO = "Nokk1251/vaelon";
const RELEASE_RX = new RegExp(`^https://github\\.com/${REPO.split(".").join("\\.")}/releases/tag/v[0-9]{1,4}\\.[0-9]{1,4}\\.[0-9]{1,4}$`);
/** Only a link to Vaelon's own Releases page is ever shown (the core builds it; checked again here). */
export const safeReleaseLink = (url: string) => (RELEASE_RX.test(url) ? url : "");

/** Settings > Updates: an opt-in daily check and a "Check now" button. Nothing is downloaded or installed here - the
 *  user opens the official download page and runs the installer over this version (data and settings stay). */
export default function UpdateCheck({ token, t, on, busy, onToggle }: {
  token: string; t: Strings; on: boolean; busy: boolean; onToggle: (on: boolean) => void;
}) {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [checking, setChecking] = useState(false);

  const now = async () => {
    setChecking(true);
    try {
      setInfo(await new VaelonApi(token).updateCheck(true));
    } catch (e) {
      setInfo({ enabled: true, current: "", latest: "", newer: false, url: "", error: e instanceof Error ? e.message : "error" });
    }
    setChecking(false);
  };

  const link = info?.newer ? safeReleaseLink(info.url) : "";
  return (
    <>
      <label className="check">
        <input type="checkbox" checked={on} disabled={busy} onChange={(e) => onToggle(e.target.checked)} />
        <span>{t.updateDaily}</span>
      </label>
      <p className="muted small">{t.updatePrivacy}</p>
      <div className="row-actions">
        <button type="button" className="btn ghost" disabled={checking} onClick={() => void now()}>
          {checking ? t.updateChecking : t.updateNow}
        </button>
      </div>
      {info && (
        <p className={`small ${info.checking ? "muted" : info.error ? "bad" : info.newer ? "good" : "muted"}`} role="status">
          {info.checking
            ? t.updateSlow
            : info.error
            ? `${t.updateFailed} ${info.error}`
            : !info.enabled
              ? t.updateNoSource
              : info.newer
                ? t.updateAvailable.replace("{latest}", info.latest).replace("{current}", info.current)
                : t.updateNewest.replace("{current}", info.current)}
        </p>
      )}
      {link && (
        <>
          <div className="row-actions">
            <a className="btn" href={link} target="_blank" rel="noopener noreferrer">{t.updateOpenPage}</a>
          </div>
          <p className="muted small">{t.updateHow}</p>
        </>
      )}
    </>
  );
}
