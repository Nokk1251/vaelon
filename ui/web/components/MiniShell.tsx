"use client";

// The companion: a small always-on-top window you can drag anywhere. It listens, answers aloud, can be interrupted,
// and - when you switch the eye on - may look at your screen to answer questions about what you see.

import { useEffect, useRef, useState } from "react";
import { createSwarm, type SwarmApi, type SwarmMode } from "@/lib/swarm";
import { setVoiceFx, voiceLevel } from "@/lib/voiceFx";
import { listenLoop, isGhost, isEcho, isStop, isBackchannel, ENDPOINT_MS, type LoopHandle } from "@/lib/mic";
import { EarlyText, Stopwatch, speedOn, warmUp } from "@/lib/speed";
import { Speaker, speakable } from "@/lib/speech";
import { startLive, type LiveHandle } from "@/lib/live";
import { API_BASE, VaelonApi, type JobState } from "@/lib/vaelonApi";
import { STRINGS } from "@/lib/i18n";

const TOKEN_KEY = "vaelon_api_token";
const LIVE_KEY = "vaelon_live_on";
type Phase = "start" | "listen" | "hear" | "think" | "see" | "speak" | "muted" | "ask";

type Desk = { pywebview?: { api?: { mini?: (on: boolean) => Promise<boolean> } } };

export default function MiniShell() {
  const t = STRINGS.en;
  const orbRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLElement>(null);
  const swarmRef = useRef<SwarmApi | null>(null);
  const speaker = useRef<Speaker | null>(null);
  const loopRef = useRef<LoopHandle | null>(null);
  const tokenRef = useRef("");
  const jobRef = useRef(""); // the answer being written / spoken right now
  const heldRef = useRef(false);
  const eyeRef = useRef(false);
  const mutedRef = useRef(false);
  const micLevel = useRef(0);
  const hearingRef = useRef(false);
  const workRef = useRef<"" | "think" | "see">("");
  const bus = useRef<BroadcastChannel | null>(null);
  const liveRef = useRef<LiveHandle | null>(null); // real-time voice session, when the LIVE switch is on
  const livePort = useRef(0);
  const liveText = useRef({ you: "", say: "" });
  const watch = useRef(new Stopwatch()); // where the time of the last exchange went (/speed in the big window)
  const earlyText = useRef<EarlyText | null>(null);

  const [ready, setReady] = useState(false); // false = the first click is still needed (audio is locked until then)
  const [phase, setPhase] = useState<Phase>("start");
  const [you, setYou] = useState("");
  const [answer, setAnswer] = useState("");
  const [eye, setEye] = useState(false);
  const [muted, setMuted] = useState(false);
  const [cloud, setCloud] = useState(false);
  const [approval, setApproval] = useState<{ job: string; text: string; card: string } | null>(null);
  const [error, setError] = useState("");
  const [liveOk, setLiveOk] = useState(false); // the core can do Live (bridge running + Gemini key stored)
  const [live, setLive] = useState(false);

  const say = (who: "you" | "vaelon", text: string) => bus.current?.postMessage({ type: "line", who, text });

  /** One request: send, follow, speak. A newer request cancels the one still running. */
  const askSeq = useRef(0);
  const heardSeq = useRef(0);
  const starting = useRef<Promise<void> | null>(null);
  const liveStarting = useRef<Promise<boolean> | null>(null);
  const ask = async (text: string) => {
    const mine = ++askSeq.current; // a newer request makes this one stale, even before it has a job number
    const api = new VaelonApi(tokenRef.current);
    const sp = speaker.current;
    if (jobRef.current) void api.cancel(jobRef.current).catch(() => undefined);
    sp?.cancel();
    setYou(text);
    setAnswer("");
    say("you", text);
    workRef.current = "think";
    const tell = (done: boolean) => {
      if (!speedOn()) return;
      const line = watch.current.report(done, true, { heard: t.speedHeard, first: t.speedFirst, voice: t.speedVoice });
      if (line) bus.current?.postMessage({ type: "line", who: "sys", text: `⏱ ${line} (${t.speedTail})` });
    };
    if (sp) {
      sp.onSound = () => {
        watch.current.mark("voice");
        tell(false);
      };
    }
    let job = "";
    try {
      job = await api.send(text, true, eyeRef.current);
      if (askSeq.current !== mine) {  // something newer was asked while this one was being sent
        void api.cancel(job).catch(() => undefined);
        return;
      }
      jobRef.current = job;
      let rev = -1;
      for (let i = 0; i < 2000 && jobRef.current === job; i++) {
        const st: JobState = await api.job(job, rev);
        rev = st.rev;
        if (jobRef.current !== job) break;
        workRef.current = st.partial ? "" : st.tool === "see_screen" ? "see" : "think";
        setApproval(st.status === "approval" && st.approval ? { job, text: st.approval.summary, card: st.approval.id } : null);
        if (st.partial) setAnswer(speakable(st.partial));
        if (st.partial || st.answer) watch.current.mark("words");
        if (st.status !== "done") sp?.feed(st.partial);
        else {
          if (!st.cancelled) {
            setAnswer(speakable(st.answer));
            sp?.finish(st.answer);
            say("vaelon", st.answer);
            tell(true);
            setTimeout(() => tell(true), 2500); // the voice may start a moment after the text
          }
          break;
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "error");
    } finally {
      if (jobRef.current === job) {
        jobRef.current = "";
        workRef.current = "";
        setApproval(null);
      }
    }
  };

  const stopAll = () => {
    liveRef.current?.interrupt();
    speaker.current?.cancel();
    heldRef.current = false;
    if (jobRef.current) void new VaelonApi(tokenRef.current).cancel(jobRef.current).catch(() => undefined);
    jobRef.current = "";
    workRef.current = "";
    setApproval(null);
  };

  const heard = async (wav: Blob, ms: number, over: boolean, early = false) => {
    const sp = speaker.current;
    const wasHeld = heldRef.current;
    const said = sp?.recent ?? "";
    const resume = () => {
      if (wasHeld) {
        sp?.hold(false);
        heldRef.current = false;
      }
    };
    let text = "";
    const phrase = ++heardSeq.current; // transcriptions can finish out of order: only the newest phrase counts
    watch.current.start(ENDPOINT_MS); // you stopped talking that long ago: the microphone waited to be sure
    try {
      const api = new VaelonApi(tokenRef.current);
      text = earlyText.current ? await earlyText.current.final(wav, early) : (await api.transcribe(wav, "audio/wav")).trim();
      if (phrase !== heardSeq.current) return;
    } catch (e) {
      resume();
      return setError(e instanceof Error ? e.message : t.micNoEngine);
    }
    watch.current.mark("heard");
    const interrupting = over || wasHeld;
    if (isGhost(text, ms) || (interrupting && isEcho(text, said))) return resume();
    if (isStop(text, interrupting)) return stopAll();
    if (interrupting && isBackchannel(text)) return resume();
    heldRef.current = false;
    setError("");
    void ask(text);
  };

  const start = async () => {
    if (loopRef.current) return;
    if (starting.current) return starting.current; // a click while the microphone is still opening: the same start
    starting.current = startLoop().finally(() => {
      starting.current = null;
    });
    return starting.current;
  };

  const startLoop = async () => {
    setVoiceFx(true);
    const handle = await listenLoop({
      onLevel: (l) => {
        micLevel.current = mutedRef.current ? 0 : l;
        rootRef.current?.style.setProperty("--mic", micLevel.current.toFixed(3));
      },
      loud: () => !!speaker.current?.speaking,
      onSpeech: (on) => {
        hearingRef.current = on && !mutedRef.current;
        if (on && !mutedRef.current) warmUp(new VaelonApi(tokenRef.current)); // connections open by the time you finish
        if (on && !mutedRef.current && speaker.current?.speaking) {
          speaker.current.hold(true);
          heldRef.current = true;
        }
      },
      onError: (msg) => setError(msg),
      onEarly: (wav) => {
        if (!mutedRef.current) earlyText.current?.early(wav);
      },
      onUtterance: (wav, ms, over, early) => {
        if (!mutedRef.current) void heard(wav, ms, over, early);
        else earlyText.current?.drop();
      },
    });
    if (!handle) return;
    loopRef.current = handle;
    setError("");
    // a window opened by a script may have its sound locked until the first click: then we ask for that click
    const ok = await handle.resume();
    setReady(ok);
  };

  /** Real-time voice: the microphone streams to the core's bridge, the voice streams back. */
  const startLiveMode = async (): Promise<boolean> => {
    if (liveRef.current || !livePort.current) return false;
    if (liveStarting.current) return liveStarting.current;
    liveStarting.current = openLive().finally(() => {
      liveStarting.current = null;
    });
    return liveStarting.current;
  };

  const openLive = async (): Promise<boolean> => {
    loopRef.current?.stop();
    loopRef.current = null;
    speaker.current?.cancel();
    liveText.current = { you: "", say: "" };
    const handle = await startLive({
      port: livePort.current,
      token: tokenRef.current,
      screen: eyeRef.current,
      onMicLevel: (l) => {
        micLevel.current = l;
        hearingRef.current = l > 0.14 && !mutedRef.current;
        rootRef.current?.style.setProperty("--mic", l.toFixed(3));
      },
      onYou: (text) => {
        if (liveText.current.say) liveText.current = { you: "", say: "" }; // a new exchange begins
        liveText.current.you += text;
        setYou(liveText.current.you.trim());
        setError("");
      },
      onSay: (text) => {
        liveText.current.say += text;
        setAnswer(liveText.current.say.trim());
      },
      onTurn: () => {
        const { you: said, say: reply } = liveText.current;
        if (said.trim()) say("you", said.trim());
        if (reply.trim()) say("vaelon", reply.trim());
        workRef.current = "";
      },
      onInterrupted: () => {
        liveText.current.say = "";
      },
      onTask: () => {
        workRef.current = "think";
      },
      onTool: (name) => {
        workRef.current = name === "see_screen" ? "see" : "think";
      },
      onTaskDone: () => {
        workRef.current = "";
        setApproval(null);
      },
      onApproval: (job, summary, card) => setApproval({ job, text: summary, card }),
      onError: (msg) => setError(msg),
      onClose: () => {
        liveRef.current = null;
        setLive(false);
        void start(); // the line dropped: fall back to the normal voice
      },
    });
    if (!handle) return false;
    liveRef.current = handle;
    handle.setMuted(mutedRef.current);
    setLive(true);
    setError("");
    setReady(await handle.resume());
    return true;
  };

  const toggleLive = async () => {
    const on = !liveRef.current;
    try {
      localStorage.setItem(LIVE_KEY, on ? "1" : "0");
    } catch {
      /* private mode */
    }
    if (on) {
      if (await startLiveMode()) setYou(t.liveStarted);
      return;
    }
    liveRef.current?.stop();
    liveRef.current = null;
    setLive(false);
    workRef.current = "";
    setYou(t.liveEnded);
    setAnswer("");
    await start();
  };

  useEffect(() => {
    const handed = new URLSearchParams(window.location.hash.slice(1)).get("k");
    if (handed) {
      try {
        sessionStorage.setItem(TOKEN_KEY, handed);
      } catch {
        /* private mode: the key stays in memory */
      }
      history.replaceState(null, "", window.location.pathname);
    }
    let stored = "";
    try {
      stored = sessionStorage.getItem(TOKEN_KEY) ?? "";
    } catch {
      /* ignore */
    }
    tokenRef.current = handed || stored;
    bus.current = "BroadcastChannel" in window ? new BroadcastChannel("vaelon") : null;
    const s = new Speaker();
    speaker.current = s;
    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then((h: { tts?: boolean }) => (s.serverToken = h.tts ? tokenRef.current : null))
      .catch(() => undefined);
    new VaelonApi(tokenRef.current)
      .catalog()
      .then((c) => setCloud(!c.model.local))
      .catch(() => undefined);
    const swarm = orbRef.current ? createSwarm(orbRef.current, { compact: true }) : null;
    swarmRef.current = swarm;
    swarm?.setEnergy(0.4);
    // Live was left on last time and is still possible: go straight to it; otherwise the normal voice
    new VaelonApi(tokenRef.current)
      .voice()
      .then(async (v) => {
        const ok = !!v.live?.available;
        // transcribing early pays off with a fast cloud engine; a local one on this CPU would only be slowed down
        earlyText.current = v.stt === "groq" ? new EarlyText((w) => new VaelonApi(tokenRef.current).transcribe(w, "audio/wav")) : null;
        livePort.current = v.live?.port ?? 0;
        setLiveOk(ok);
        let wanted = false;
        try {
          wanted = localStorage.getItem(LIVE_KEY) === "1";
        } catch {
          /* ignore */
        }
        if (!(ok && wanted && (await startLiveMode()))) await start();
      })
      .catch(() => void start());

    let current: Phase = "start";
    const tick = () => {
      const now = performance.now();
      const lv = liveRef.current;
      const speaking = lv ? lv.speaking() : !!speaker.current?.speaking;
      let level = lv ? lv.level() : voiceLevel();
      if (speaking && level === 0) level = 0.35 + 0.25 * Math.sin(now / 90) * Math.sin(now / 37);
      const next: Phase = !loopRef.current && !lv
        ? "start"
        : speaking
          ? "speak"
          : workRef.current === "see"
            ? "see"
            : workRef.current === "think"
              ? "think"
              : mutedRef.current
                ? "muted"
                : hearingRef.current
                  ? "hear"
                  : "listen";
      if (next !== current) {
        current = next;
        setPhase(next);
        const mode: SwarmMode = next === "speak" ? "speak" : next === "think" ? "think" : next === "see" ? "tool"
          : next === "muted" || next === "start" ? "idle" : "listen";
        swarm?.setMode(mode);
      }
      swarm?.setVoice(speaking ? level : 0);
      swarm?.setMic(next === "listen" || next === "hear" ? micLevel.current : 0);
    };
    const timer = setInterval(tick, 80);
    return () => {
      clearInterval(timer);
      liveRef.current?.stop();
      liveRef.current = null;
      loopRef.current?.stop();
      loopRef.current = null;
      s.cancel();
      swarm?.dispose();
      bus.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const unlock = async () => {
    setVoiceFx(true);
    if (liveRef.current) setReady(await liveRef.current.resume());
    else if (!loopRef.current) await start();
    else setReady(await loopRef.current.resume());
  };

  const toggleEye = () => {
    const on = !eyeRef.current;
    eyeRef.current = on;
    setEye(on);
    liveRef.current?.setScreen(on);
  };

  const toggleMute = () => {
    const on = !mutedRef.current;
    mutedRef.current = on;
    setMuted(on);
    liveRef.current?.setMuted(on);
    if (on) hearingRef.current = false;
  };

  const expand = async () => {
    stopAll();
    liveRef.current?.stop();
    liveRef.current = null;
    loopRef.current?.stop();
    loopRef.current = null;
    bus.current?.postMessage({ type: "mini-closed" });
    const api = (window as unknown as Desk).pywebview?.api;
    if (api?.mini) await api.mini(false);
    else window.close();
  };

  const decide = async (allow: boolean) => {
    if (!approval) return;
    await new VaelonApi(tokenRef.current).approve(approval.job, allow, approval.card).catch(() => undefined);
    setApproval(null);
  };

  const label = {
    start: t.miniStart, listen: t.listening, hear: t.hearing, think: t.miniThinking, see: t.miniSeeing,
    speak: t.speaking, muted: t.miniMuted, ask: t.approvalTitle,
  }[approval ? "ask" : phase];

  return (
    <main ref={rootRef} className={`mini phase-${approval ? "ask" : phase} ${eye ? "eye-on" : ""} ${live ? "live-on" : ""}`}>
      <div ref={orbRef} className="mini-orb" />
      <div className="mini-body">
        <div className="mini-state">
          <span className="dot" /> {label}
          {live && <em className="live-tag" title={t.liveOn}>{t.liveTag}</em>}
          {eye && <em title={live ? t.liveEyeOn : cloud ? t.eyeCloud : t.eyeLocal}>{t.miniEye}</em>}
        </div>
        {approval ? (
          <div className="mini-ask">
            <p>{approval.text}</p>
            <button className="deny" onClick={() => void decide(false)}>
              {t.deny}
            </button>
            <button className="allow" onClick={() => void decide(true)}>
              {t.allow}
            </button>
          </div>
        ) : (
          <>
            <p className="mini-you">{error || you || (ready ? t.miniHint : t.miniClick)}</p>
            <p className="mini-answer">{answer}</p>
          </>
        )}
      </div>
      <div className="mini-tools">
        {liveOk && (
          <button className={`live ${live ? "on" : ""}`} onClick={() => void toggleLive()} title={live ? t.liveOn : t.liveOff} aria-pressed={live} aria-label={t.liveOff}>
            <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
              <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" fill="currentColor" />
            </svg>
          </button>
        )}
        <button className={eye ? "on" : ""} onClick={toggleEye} title={eye ? (live ? t.liveEyeOn : cloud ? t.eyeCloud : t.eyeLocal) : t.eyeOff} aria-pressed={eye} aria-label={t.eyeOff}>
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" fill="none" stroke="currentColor" strokeWidth="1.8" />
            <circle cx="12" cy="12" r="3" fill="currentColor" />
          </svg>
        </button>
        <button className={muted ? "on" : ""} onClick={toggleMute} title={muted ? t.miniUnmute : t.miniMute} aria-pressed={muted} aria-label={t.miniMute}>
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z" fill="currentColor" />
            <path d="M18 11a6 6 0 0 1-12 0M12 17v4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            {muted && <path d="M4 4l16 16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />}
          </svg>
        </button>
        <button onClick={stopAll} title={t.miniStop} aria-label={t.miniStop}>
          <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
            <rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor" />
          </svg>
        </button>
        <button onClick={() => void expand()} title={t.miniExpand} aria-label={t.miniExpand}>
          <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
            <path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      {!ready && (
        <button className="mini-unlock" onClick={() => void unlock()}>
          {t.miniClick}
        </button>
      )}
    </main>
  );
}
