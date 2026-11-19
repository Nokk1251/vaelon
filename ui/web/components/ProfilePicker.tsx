"use client";

import type { Profile } from "@/lib/vaelonApi";
import Icon from "./Icon";

const MARK: Record<string, string> = { business: "money", learning: "book", coding: "code", creator: "examples", life: "sun" };

/** Optional profiles: click any number of cards (or none). `onChange` gets the new list of names. */
export default function ProfilePicker(props: { profiles: Profile[]; busy?: boolean; onChange: (names: string[]) => void }) {
  const { profiles, busy, onChange } = props;
  const on = profiles.filter((p) => p.on).map((p) => p.name);
  const flip = (name: string) => onChange(on.includes(name) ? on.filter((n) => n !== name) : [...on, name]);
  return (
    <div className="cards profiles">
      {profiles.map((p) => (
        <button key={p.name} type="button" className={`card ${p.on ? "on" : ""}`} disabled={busy} aria-pressed={p.on}
          onClick={() => flip(p.name)}>
          <span className="pmark" aria-hidden><Icon name={MARK[p.name] ?? "examples"} size={20} /></span>
          <b>{p.title}</b>
          <em>{p.blurb}</em>
          {p.on && <span className="risk safe">✓</span>}
        </button>
      ))}
    </div>
  );
}
