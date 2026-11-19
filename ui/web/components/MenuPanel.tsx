"use client";

import { useEffect, useMemo, useState } from "react";
import { VaelonApi, type Catalog } from "@/lib/vaelonApi";
import { STRINGS, type Lang } from "@/lib/i18n";

export type MenuTab = "examples" | "tools" | "skills" | "commands" | "memory" | "keys" | "about";

const TABS: MenuTab[] = ["examples", "tools", "skills", "commands", "memory", "keys", "about"];

const KEY_HELP: Record<string, [string, string]> = {
  GROQ_API_KEY: ["Groq - free, the fastest cloud model", "https://console.groq.com/keys"],
  GEMINI_API_KEY: ["Google Gemini - free tier, very smart", "https://aistudio.google.com/apikey"],
  OPENROUTER_API_KEY: ["OpenRouter - dozens of free models", "https://openrouter.ai/keys"],
  CEREBRAS_API_KEY: ["Cerebras - free tier, very fast", "https://cloud.cerebras.ai"],
  MISTRAL_API_KEY: ["Mistral - free plan, European company", "https://console.mistral.ai/api-keys"],
  OPENAI_API_KEY: ["OpenAI - paid", "https://platform.openai.com/api-keys"],
  ANTHROPIC_API_KEY: ["Anthropic Claude - paid, the smartest", "https://console.anthropic.com/settings/keys"],
  ELEVENLABS_API_KEY: ["ElevenLabs - studio voices (cloud)", "https://elevenlabs.io/app/settings/api-keys"],
  TWILIO_ACCOUNT_SID: ["Twilio - phone calls and SMS", "https://console.twilio.com"],
  TWILIO_AUTH_TOKEN: ["Twilio - phone calls and SMS", "https://console.twilio.com"],
  VAELON_TELEGRAM_TOKEN: ["Telegram bot - control from your phone", "https://t.me/BotFather"],
  GITHUB_TOKEN: ["GitHub - more code research", "https://github.com/settings/tokens"],
  VAELON_SMTP_PASS: ["Gmail app password - send email", "https://myaccount.google.com/apppasswords"],
};

export default function MenuPanel(props: {
  token: string;
  lang: Lang;
  tab: MenuTab;
  onTab: (t: MenuTab) => void;
  onPick: (text: string) => void;
  onClose: () => void;
}) {
  const { token, lang, tab, onTab, onPick, onClose } = props;
  const t = STRINGS[lang];
  const RISK = t.risk as Record<string, string>;
  const [cat, setCat] = useState<Catalog | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    new VaelonApi(token)
      .catalog(lang)
      .then(setCat)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : "error"));
  }, [token, lang]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const ql = q.trim().toLowerCase();
  const has = (...xs: string[]) => !ql || xs.some((x) => x.toLowerCase().includes(ql));

  const toolGroups = useMemo(() => {
    const g: Record<string, Catalog["tools"]> = {};
    for (const t of cat?.tools ?? []) (g[t.group] ??= []).push(t);
    return g;
  }, [cat]);

  return (
    <div className="panel-wrap" onClick={onClose}>
      <aside className="panel" role="dialog" aria-label={t.capabilities} onClick={(e) => e.stopPropagation()}>
        <div className="panel-head">
          <span className="panel-title">{t.capabilities}</span>
          {cat && (
            <span className="panel-sub">
              {cat.tools.length} {t.toolsN} · {cat.skills.length} {t.skillsN} · {t.model} {cat.model.model} (
              {cat.model.local ? t.local : t.cloud})
            </span>
          )}
          <button className="x" onClick={onClose} aria-label={t.close}>
            ✕
          </button>
        </div>
        <nav className="tabs">
          {TABS.map((id) => (
            <button key={id} className={tab === id ? "on" : ""} onClick={() => onTab(id)}>
              {t.tabs[id]}
            </button>
          ))}
        </nav>
        {tab !== "memory" && tab !== "keys" && tab !== "about" && (
          <input className="search" placeholder={t.search} value={q} onChange={(e) => setQ(e.target.value)} />
        )}
        <div className="panel-body">
          {err && <p className="muted">{t.catalogFail}: {err}</p>}
          {!cat && !err && <p className="muted scan">{t.loading}</p>}

          {cat && tab === "examples" && (
            <>
              <p className="muted">{t.pickHint}</p>
              {Object.entries(cat.examples).map(([group, items]) => {
                const shown = items.filter((x) => has(x, group));
                if (!shown.length) return null;
                return (
                  <section key={group}>
                    <h3>{group}</h3>
                    <div className="pills">
                      {shown.map((x) => (
                        <button key={x} className="pill" onClick={() => onPick(x)}>
                          {x}
                        </button>
                      ))}
                    </div>
                  </section>
                );
              })}
            </>
          )}

          {cat && tab === "tools" &&
            Object.entries(toolGroups).map(([group, tools]) => {
              const shown = tools.filter((t) => has(t.name, t.description, group));
              if (!shown.length) return null;
              return (
                <section key={group}>
                  <h3>{group}</h3>
                  {shown.map((t) => (
                    <div key={t.name} className="row">
                      <code>{t.name}</code>
                      <span className={`risk ${t.risk}`}>{RISK[t.risk] ?? t.risk}</span>
                      <p>{t.description}</p>
                    </div>
                  ))}
                </section>
              );
            })}

          {cat && tab === "skills" && (
            <>
              <p className="muted">{t.skillsHint}</p>
              {cat.skills
                .filter((s) => has(s.name, s.description, ...s.triggers))
                .map((s) => (
                  <div key={s.name} className="row">
                    <code>{s.name}</code>
                    {s.learned && <span className="risk learned">{t.learnedTag}</span>}
                    <p>{s.description}</p>
                    <p className="trig">
                      {t.words}: {s.triggers.join(", ")}
                    </p>
                  </div>
                ))}
            </>
          )}

          {cat && tab === "commands" && (
            <>
              <h3>{t.inChat}</h3>
              {cat.slash
                .filter(([c, d]) => has(c, d))
                .map(([c, d]) => (
                  <div key={c} className="row">
                    <button className="pill" onClick={() => onPick(c)}>
                      {c}
                    </button>
                    <p>{d}</p>
                  </div>
                ))}
              <h3>{t.inTerminal}</h3>
              {cat.cli
                .filter(([c, d]) => has(c, d))
                .map(([c, d]) => (
                  <div key={c} className="row">
                    <code>{c}</code>
                    <p>{d}</p>
                  </div>
                ))}
            </>
          )}

          {cat && tab === "memory" && (
            <>
              <h3>{t.aboutYou}</h3>
              {Object.keys(cat.memory.profile).length ? (
                Object.entries(cat.memory.profile).map(([k, v]) => (
                  <div key={k} className="row">
                    <code>{k}</code>
                    <p>{Array.isArray(v) ? v.join(", ") : v}</p>
                  </div>
                ))
              ) : (
                <p className="muted">{t.nothingYet}</p>
              )}
              {cat.memory.recent.length > 0 && (
                <>
                  <h3>{t.facts}</h3>
                  {cat.memory.recent.map((t, i) => (
                    <p key={i} className="fact">
                      {t}
                    </p>
                  ))}
                </>
              )}
              <h3>{t.memoryTotal}</h3>
              <p className="muted">
                {Object.entries(cat.memory.facts)
                  .map(([k, n]) => `${k}: ${n}`)
                  .join(" · ") || t.empty}{" "}
                · {t.historyMsgs}: {cat.memory.conversation} · {t.learnedSkills}: {cat.memory.learned_skills}
              </p>
              <p className="muted">{t.encrypted}</p>
            </>
          )}

          {cat && tab === "keys" && (
            <>
              <p className="muted">{t.keysHint}</p>
              <pre className="cmd">vaelon key set GROQ_API_KEY{"\n"}vaelon provider groq</pre>
              {Object.entries(cat.keys).map(([name, ok]) => (
                <div key={name} className="row">
                  <span className={`risk ${ok ? "safe" : ""}`}>{ok ? t.keySet : t.keyMissing}</span>
                  <code>{name}</code>
                  <p>
                    {KEY_HELP[name]?.[0] ?? ""} <span className="url">{KEY_HELP[name]?.[1] ?? ""}</span>
                  </p>
                </div>
              ))}
              <p className="muted">{t.cloudNote}</p>
            </>
          )}

          {cat && tab === "about" && (
            <>
              {/* the legal notices: who made Vaelon and under which license. They must stay visible (see NOTICE). */}
              <h3>{t.aboutTitle}</h3>
              <div className="row">
                <code>{t.createdBy}</code>
                <p className="credit">
                  {cat.about?.author ?? "-"}
                  {cat.about?.author_url && <span className="url"> {cat.about.author_url}</span>}
                </p>
              </div>
              <div className="row">
                <code>{t.version}</code>
                <p>{cat.about?.version ?? "-"}</p>
              </div>
              <div className="row">
                <code>{t.license}</code>
                <p>{cat.about?.license ?? "GPL-3.0-or-later"}</p>
              </div>
              <div className="row">
                <code>{t.source}</code>
                <p>{cat.about?.source ? <span className="url">{cat.about.source}</span> : t.sourceSoon}</p>
              </div>
              <p className="muted">{t.licenseText}</p>
              <p className="muted">{t.noWarranty}</p>
              <p className="muted">{t.privacyNote}</p>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
