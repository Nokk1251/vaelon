"use client";

import { useCallback, useEffect, useState } from "react";
import { VaelonApi, type CalDay, type CalEvent } from "@/lib/vaelonApi";
import { STRINGS, type Lang } from "@/lib/i18n";

const pad = (n: number) => String(n).padStart(2, "0");
const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00`);
  d.setDate(d.getDate() + n);
  return isoDay(d);
};
function nextHour(): string {
  const d = new Date();
  d.setHours(d.getHours() + 1, 0, 0, 0);
  return `${pad(d.getHours())}:00`;
}

/** The calendar: the next two weeks, a quick way to add an appointment, cancel, export as .ics.
 *  Everything is stored encrypted on this computer; Vaelon reminds you before each appointment. */
export default function CalendarPanel(props: { token: string; lang: Lang; onClose: () => void; onNote: (s: string) => void }) {
  const { token, lang, onClose, onNote } = props;
  const t = STRINGS[lang];
  const [from, setFrom] = useState(isoDay(new Date()));
  const [days, setDays] = useState<CalDay[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState<string | null>(null); // "id|start" of the event whose cancel is being confirmed
  const [form, setForm] = useState({ title: "", date: isoDay(new Date()), time: nextHour(), minutes: 60, remind: 15 as number | null,
    repeat: "", place: "" });

  const load = useCallback(async () => {
    try {
      setDays((await new VaelonApi(token).calendar(from, 14)).days);
    } catch {
      onNote(t.calFail);
    }
  }, [token, from, onNote, t.calFail]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const add = async () => {
    if (!form.title.trim()) return;
    setBusy(true);
    try {
      const allDay = form.minutes === 0;
      const r = await new VaelonApi(token).calendarAct({ action: "add", title: form.title, date: form.date,
        time: allDay ? "" : form.time, minutes: allDay ? undefined : form.minutes, remind: form.remind, repeat: form.repeat,
        place: form.place });
      if (!r.ok) onNote(r.error || t.calFail);
      else {
        const clash = r.clashes?.length ? ` ${t.calClash}: ${r.clashes.map((c) => `${c.start.slice(11)} ${c.title}`).join(", ")}` : "";
        onNote(`${t.calAdded}${clash}`);
        setForm((f) => ({ ...f, title: "", place: "" }));
        await load();
      }
    } catch {
      onNote(t.calFail);
    }
    setBusy(false);
  };

  const cancel = async (ev: CalEvent, onlyThis: boolean) => {
    setBusy(true);
    try {
      const r = await new VaelonApi(token).calendarAct(onlyThis ? { action: "skip", id: ev.id, start: ev.start } : { action: "cancel", id: ev.id });
      onNote(r.ok ? (onlyThis ? t.calSkipped : t.calCancelled) : r.error || t.calFail);
      await load();
    } catch {
      onNote(t.calFail);
    }
    setAsking(null);
    setBusy(false);
  };

  const exportIcs = async () => {
    setBusy(true);
    try {
      const r = await new VaelonApi(token).calendarAct({ action: "export" });
      onNote(r.ok ? `${t.calExported}: ${r.path}` : r.error || t.calFail);
    } catch {
      onNote(t.calFail);
    }
    setBusy(false);
  };

  const when = (ev: CalEvent) => {
    if (ev.all_day) return t.calAllDay;
    const s = new Date(ev.start);
    const e = new Date(s.getTime() + ev.minutes * 60000);
    return `${pad(s.getHours())}:${pad(s.getMinutes())}–${pad(e.getHours())}:${pad(e.getMinutes())}`;
  };
  const today = isoDay(new Date());
  const label = (d: CalDay) => {
    if (d.date === today) return t.today;
    if (d.date === addDays(today, 1)) return t.tomorrow;
    return new Date(`${d.date}T12:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  };

  return (
    <div className="panel-wrap" onClick={onClose}>
      <aside className="panel calendar" role="dialog" aria-label={t.calendar} onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <span className="panel-title">{t.calendar}</span>
          <span className="panel-sub">{t.calPrivate}</span>
          <button className="x" onClick={onClose} aria-label={t.close}>
            ✕
          </button>
        </div>
        <div className="panel-body">
          <form
            className="calform"
            onSubmit={(e) => {
              e.preventDefault();
              void add();
            }}
          >
            <input aria-label={t.calWhat} placeholder={t.calWhat} maxLength={200} value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <div className="calrow">
              <input type="date" aria-label={t.calDate} value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
              <input type="time" aria-label={t.calTime} value={form.time} disabled={form.minutes === 0}
                onChange={(e) => setForm({ ...form, time: e.target.value })} />
              <select aria-label={t.calLength} value={form.minutes} onChange={(e) => setForm({ ...form, minutes: Number(e.target.value) })}>
                {[15, 30, 45, 60, 90, 120, 180].map((m) => (
                  <option key={m} value={m}>{m < 60 ? `${m} min` : `${m / 60} h`}</option>
                ))}
                <option value={0}>{t.calAllDay}</option>
              </select>
            </div>
            <div className="calrow">
              <select aria-label={t.calRemind} value={form.remind ?? -1}
                onChange={(e) => setForm({ ...form, remind: Number(e.target.value) < 0 ? null : Number(e.target.value) })}>
                <option value={-1}>{t.calNoRemind}</option>
                {[5, 15, 30, 60, 1440].map((m) => (
                  <option key={m} value={m}>{m === 1440 ? t.calDayBefore : `${t.calRemind} ${m < 60 ? `${m} min` : `${m / 60} h`}`}</option>
                ))}
              </select>
              <select aria-label={t.calRepeat} value={form.repeat} onChange={(e) => setForm({ ...form, repeat: e.target.value })}>
                <option value="">{t.calOnce}</option>
                <option value="daily">{t.calDaily}</option>
                <option value="weekly">{t.calWeekly}</option>
                <option value="monthly">{t.calMonthly}</option>
                <option value="yearly">{t.calYearly}</option>
              </select>
            </div>
            <div className="calrow">
              <input aria-label={t.calPlace} placeholder={t.calPlace} maxLength={200} value={form.place}
                onChange={(e) => setForm({ ...form, place: e.target.value })} />
              <button type="submit" className="btn" disabled={busy || !form.title.trim()}>
                {t.calAdd}
              </button>
            </div>
          </form>
          <p className="muted small">{t.calSay}</p>

          <div className="calnav">
            <button type="button" className="btn ghost" onClick={() => setFrom(addDays(from, -7))} aria-label={t.calEarlier}>‹</button>
            <button type="button" className="btn ghost" onClick={() => setFrom(today)}>{t.today}</button>
            <button type="button" className="btn ghost" onClick={() => setFrom(addDays(from, 7))} aria-label={t.calLater}>›</button>
            <span className="grow" />
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void exportIcs()}>{t.calExport}</button>
          </div>

          {!days && <p className="muted scan">{t.loading}</p>}
          {days?.map((d) => (
            <section key={d.date} className={`calday ${d.events.length ? "" : "empty"} ${d.date === today ? "today" : ""}`}>
              <h4>{label(d)}</h4>
              {d.events.map((ev) => {
                const key = `${ev.id}|${ev.start}`;
                return (
                  <div key={key} className="calevent">
                    <span className="calwhen">{when(ev)}</span>
                    <span className="caltitle">
                      {ev.title}
                      {ev.repeat && <i title={ev.repeat}> ↻</i>}
                      {ev.place && <em> · {ev.place}</em>}
                    </span>
                    {asking === key ? (
                      <span className="chatask">
                        {ev.repeat && (
                          <button type="button" className="btn ghost" disabled={busy} onClick={() => void cancel(ev, true)}>{t.calOnlyThis}</button>
                        )}
                        <button type="button" className="btn" disabled={busy} onClick={() => void cancel(ev, false)}>
                          {ev.repeat ? t.calAllOfThem : t.chatDelete}
                        </button>
                        <button type="button" className="btn ghost" onClick={() => setAsking(null)}>{t.chatKeep}</button>
                      </span>
                    ) : (
                      <button type="button" className="x" aria-label={`${t.chatDelete}: ${ev.title}`} onClick={() => setAsking(key)}>✕</button>
                    )}
                  </div>
                );
              })}
            </section>
          ))}
        </div>
      </aside>
    </div>
  );
}
