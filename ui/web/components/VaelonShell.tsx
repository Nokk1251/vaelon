"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createSwarm, TASK_COLORS, type SwarmApi, type SwarmMode } from "@/lib/swarm";
import { GlitchDirector, type CssFx } from "@/lib/glitchDirector";
import { triggerVoiceGlitch, setVoiceFx, setVoiceGlitch, voiceLevel } from "@/lib/voiceFx";
import { watchPrefs } from "@/lib/prefs";
import { recordCommand, listenLoop, isGhost, isEcho, isStop, isBackchannel, ENDPOINT_MS, type MicHandle, type LoopHandle } from "@/lib/mic";
import { EarlyText, Stopwatch, setSpeed, speedOn, warmUp } from "@/lib/speed";
import { Speaker } from "@/lib/speech";
import { API_BASE, VaelonApi, apiReachable, type Attachment, type ChatMessage, type JobState, type MadeFile, type Settings } from "@/lib/vaelonApi";
import FileCard from "./FileCard";
import MenuPanel, { type MenuTab } from "./MenuPanel";
import { STRINGS, type Strings } from "@/lib/i18n";
import VoicePanel from "./VoicePanel";
import SettingsPanel from "./SettingsPanel";
import HelpPanel from "./HelpPanel";
import Icon, { Mark } from "./Icon";
import ChatsPanel from "./ChatsPanel";
import CalendarPanel from "./CalendarPanel";
import BillsPanel, { type MoneyTab } from "./BillsPanel";
import SignIn from "./SignIn";
import type { CompanyState } from "@/lib/vaelonApi";
import SetupWizard from "./SetupWizard";
import TaskPanel, { taskStatus, type Task } from "./TaskPanel";
import Rich from "./Rich";

type Line = { id: number; who: "you" | "vaelon" | "sys"; text: string; re?: string; slot?: number; files?: MadeFile[];
  clips?: string[] };

const TOKEN_KEY = "vaelon_api_token";
const VOICE_KEY = "vaelon_voice_on";
const MAX_TASKS = 4; // tasks that may run at the same time (one swarm cluster each)

// what Vaelon is doing, in words (shown under the name, in the thinking halo and on task labels)
const TOOL_WORDS: [RegExp, keyof Strings["tools"]][] = [
  [/^create_/, "create"],
  [/^research_(plan|write)/, "research"],
  [/remind|schedule/, "plan"],
  [/look_at_image|read_document|see_screen/, "see"],
  [/stock|crypto|exchange/, "market"],
  [/weather/, "weather"],
  [/wiki|book|science|country|economy/, "knowledge"],
  [/web|fetch|download|news/, "web"],
  [/^fs_|document/, "files"],
  [/code|check_file|research_code|self_/, "code"],
  [/email|sms|call|contact/, "comms"],
  [/scan|audit|url|vuln|cve/, "security"],
  [/remember|recall|learn|skill/, "learn"],
  [/process|app|command|system/, "system"],
  [/screen|image/, "see"],
];

function toolWord(tool: string, t: Strings): string {
  for (const [rx, w] of TOOL_WORDS) if (rx.test(tool)) return t.tools[w];
  return tool.replace(/_/g, " ");
}

function short(text: string, n = 34): string {
  const s = text.replace(/\s+/g, " ").trim();
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function store(kind: "session" | "local", key: string, value?: string): string {
  try {
    const s = kind === "session" ? sessionStorage : localStorage;
    if (value !== undefined) s.setItem(key, value);
    return s.getItem(key) ?? "";
  } catch {
    return "";
  }
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function greeting(t: { greetMorning: string; greetDay: string; greetEvening: string }): string {
  const h = new Date().getHours();
  return h < 5 ? t.greetEvening : h < 12 ? t.greetMorning : h < 18 ? t.greetDay : t.greetEvening;
}

export default function VaelonShell() {
  const stageRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLElement>(null);
  const swarmRef = useRef<SwarmApi | null>(null);
  const directorRef = useRef<GlitchDirector | null>(null);
  const speaker = useRef<Speaker | null>(null);
  const voiceRef = useRef(false);
  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const nextId = useRef(1);
  const startedRef = useRef(false); // something was already said in this window
  const watch = useRef(new Stopwatch()); // where the time of the last exchange went (/speed)
  const earlyText = useRef<EarlyText | null>(null);

  const [fx, setFx] = useState<CssFx>({ body: "", overlay: "" });
  const [noDot, setNoDot] = useState(false); // Settings > Look and sound: no dot in front of Vaelon's answers
  const [online, setOnline] = useState<boolean | null>(null);
  const [token, setToken] = useState("");
  const tokenRef = useRef("");
  tokenRef.current = token;
  const [tokenDraft, setTokenDraft] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [input, setInput] = useState("");
  const [voiceOn, setVoiceOn] = useState(false);
  const [ttsMode, setTtsMode] = useState<"NEURAL" | "BROWSER">("BROWSER");
  const [mode, setMode] = useState<SwarmMode>("idle");
  const lang = "en" as const;
  const t = STRINGS[lang];
  const tRef = useRef<Strings>(t);
  tRef.current = t;
  const [thinkIdx, setThinkIdx] = useState(0);
  const thinkWord = t.think[thinkIdx % t.think.length];
  const [menu, setMenu] = useState<MenuTab | null>(null);
  const [help, setHelp] = useState<string | null>(null); // open Help page: the section shown first
  const [voicePanel, setVoicePanel] = useState(false);
  const [settingsPanel, setSettingsPanel] = useState(false);
  const [chatsPanel, setChatsPanel] = useState(false);
  const [calendarPanel, setCalendarPanel] = useState(false);
  const [billsPanel, setBillsPanel] = useState<MoneyTab | null>(null);
  const [company, setCompany] = useState<CompanyState | null>(null); // company mode: who is here, which company
  // the personal parts (voice designer, calendar, chats, settings) are the owner's; unknown yet = not shown
  const isOwner = !!company && (!company.enabled || company.user?.role === "owner");
  const genRef = useRef(0); // a lock / another person: every answer still on its way belongs to the one before
  const [setup, setSetup] = useState<Settings | null>(null); // a brand-new installation: the first-run setup
  const [toast, setToast] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);

  // tasks: every request is its own job; up to MAX_TASKS run at the same time
  const [tasks, setTasks] = useState<Task[]>([]);
  const tasksRef = useRef<Task[]>([]);
  const mutate = (fn: (list: Task[]) => Task[]) => {
    tasksRef.current = fn(tasksRef.current);
    setTasks(tasksRef.current);
  };
  const [inspect, setInspect] = useState<string | null>(null);
  const inspectRef = useRef<string | null>(null);
  inspectRef.current = inspect;
  const [finished, setFinished] = useState<Task | null>(null); // the inspected task, kept after it ended
  const tagRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const ownerRef = useRef(""); // the task whose answer is read aloud while it streams
  const silentRef = useRef(new Set<string>()); // tasks you interrupted by voice: no "cancelled" note
  const [, setClock] = useState(0);

  // microphone: one spoken command, or the hands-free conversation loop
  const [mic, setMic] = useState<"off" | "listening" | "transcribing">("off");
  const micRef = useRef<MicHandle | null>(null);
  const micStateRef = useRef("off");
  micStateRef.current = mic;
  const speakOnce = useRef(false); // a spoken question gets a spoken answer
  const [conv, setConv] = useState(false);
  const convRef = useRef(false);
  const loopRef = useRef<LoopHandle | null>(null);
  const [hearing, setHearing] = useState(false);
  const heldRef = useRef(false); // Vaelon's voice is paused because you started talking over it
  const micLevel = useRef(0);

  // files you attach to the next request (paperclip, paste, or drop)
  const [clips, setClips] = useState<Attachment[]>([]);
  const clipsRef = useRef<Attachment[]>([]);
  clipsRef.current = clips;
  const [dropping, setDropping] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const busy = tasks.length > 0;
  const solo = tasks.length === 1 ? tasks[0] : null;
  const soloTool = solo?.state?.tool && !solo.state.partial ? solo.state.tool : "";
  const pending = tasks.find((k) => k.state?.status === "approval") ?? null;

  // body: the swarm + the glitch director that tears it (and the voice) at random moments
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const swarm = createSwarm(stage);
    if (process.env.NODE_ENV !== "production") (window as unknown as { __swarm?: unknown }).__swarm = swarm; // dev checks only
    swarmRef.current = swarm;
    const d = new GlitchDirector(() => swarmRef.current, setFx);
    d.onFire = (ms) => triggerVoiceGlitch(ms);
    directorRef.current = d;
    // the owner's choices: glitches of the swarm and of the voice can each be switched off; so can the answer dot
    const unwatch = watchPrefs((p) => {
      if (p.glitchVisual) d.start();
      else d.stop(); // stop() also clears any effect that is showing right now
      setVoiceGlitch(p.glitchVoice);
      setNoDot(!p.avatarDot);
    });
    return () => {
      unwatch();
      d.stop();
      swarm.dispose();
      swarmRef.current = null;
    };
  }, []);

  useEffect(() => {
    swarmRef.current?.setEnergy(busy ? 1 : 0);
    directorRef.current?.setBusy(busy);
  }, [busy]);

  // two or more tasks: the swarm splits into one cluster per task; back to one body when they finish
  useEffect(() => {
    swarmRef.current?.setTasks(
      tasks.length >= 2
        ? tasks.map((k) => ({
            id: k.id,
            slot: k.slot,
            mode: !k.state || k.state.queued ? "wait" : k.state.tool && !k.state.partial ? "tool" : "think",
          }))
        : [],
    );
  }, [tasks]);

  // a new tool fires: a shockwave runs through the swarm
  const toolSig = tasks.map((k) => k.state?.tool ?? "").join("|");
  useEffect(() => {
    if (toolSig.replace(/\|/g, "")) swarmRef.current?.pulse(tasksRef.current.length > 1 ? 0.25 : 0.5);
  }, [toolSig]);

  // the life loop: decides the swarm's state, feeds it the voices and keeps the task labels on their clusters
  useEffect(() => {
    let raf = 0;
    let last = 0;
    let current: SwarmMode = "idle";
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      const sw = swarmRef.current;
      const list = tasksRef.current;
      if (sw) {
        for (const k of list) {
          const el = tagRefs.current[k.slot];
          if (!el) continue;
          const p = sw.taskScreen(k.slot);
          if (p) {
            el.style.transform = `translate(${p.x.toFixed(1)}px, ${(p.y + p.r + 12).toFixed(1)}px) translate(-50%, 0)`;
            el.dataset.on = "1";
          } else if (el.style.transform) el.style.transform = "";
        }
      }
      if (now - last < 50) return;
      last = now;
      const sp = speaker.current;
      const speaking = !!sp && sp.speaking;
      let level = voiceLevel();
      if (speaking && level === 0) level = 0.35 + 0.25 * Math.sin(now / 90) * Math.sin(now / 37); // browser voice: no meter
      const one = list.length === 1 ? list[0].state : null;
      const listening = convRef.current || micStateRef.current === "listening";
      const next: SwarmMode = speaking
        ? "speak"
        : list.length
          ? one?.tool && !one.partial ? "tool" : "think"
          : listening ? "listen" : "idle";
      if (next !== current) {
        current = next;
        sw?.setMode(next);
        setMode(next);
      }
      sw?.setVoice(speaking ? level : 0);
      sw?.setMic(listening ? micLevel.current : 0);
      shellRef.current?.style.setProperty("--lvl", (speaking ? level : 0).toFixed(3));
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // thinking words rotate while it works; task labels count seconds
  useEffect(() => {
    if (mode !== "think") return;
    const id = setInterval(() => setThinkIdx((i) => i + 1), 1800);
    return () => clearInterval(id);
  }, [mode]);
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => setClock((c) => c + 1), 1000);
    return () => clearInterval(id);
  }, [busy]);

  // link to the local core
  useEffect(() => {
    // desktop app hands over the access key in the URL fragment (never sent to any server); take it and wipe it
    const handed = new URLSearchParams(window.location.hash.slice(1)).get("k");
    if (handed) {
      store("session", TOKEN_KEY, handed);
      history.replaceState(null, "", window.location.pathname);
    }
    setToken(handed || store("session", TOKEN_KEY));
    const on = store("local", VOICE_KEY) === "1";
    voiceRef.current = on;
    setVoiceOn(on);
    const s = new Speaker();
    s.onNoVoice = () => push("sys", tRef.current.noVoice);
    speaker.current = s;
    void apiReachable().then(setOnline);
    // what is said in the companion window also lands in this window's conversation
    const bus = "BroadcastChannel" in window ? new BroadcastChannel("vaelon") : null;
    if (bus) {
      bus.onmessage = (e: MessageEvent<{ type?: string; who?: "you" | "vaelon" | "sys"; text?: string }>) => {
        if (e.data?.type === "line" && e.data.text && e.data.who) push(e.data.who, e.data.text);
      };
    }
    return () => {
      bus?.close();
      s.cancel();
      loopRef.current?.stop();
      micRef.current?.stop();
    };
  }, []);

  useEffect(() => {
    if (!token || !speaker.current) return;
    const sp = speaker.current;
    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then((h: { tts?: boolean }) => {
        sp.serverToken = h.tts ? token : null;
        setTtsMode(h.tts ? "NEURAL" : "BROWSER");
      })
      .catch(() => (sp.serverToken = null));
  }, [token]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [lines, tasks]);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(""), 3600);
    return () => clearTimeout(id);
  }, [toast]);

  const push = (who: Line["who"], text: string, extra?: { re?: string; slot?: number; files?: MadeFile[]; clips?: string[] }) => {
    startedRef.current = true;
    setLines((p) => [...p.slice(-40), { id: nextId.current++, who, text, ...extra }]);
  };

  const note = useCallback((text: string) => setToast(text), []);

  // put a stored conversation on the screen (after opening one from the list, and when the window starts)
  const showChat = useCallback((messages: ChatMessage[]) => {
    setLines(
      messages.slice(-40).map((m) => ({
        id: nextId.current++,
        who: m.role === "user" ? ("you" as const) : ("vaelon" as const),
        text: m.role === "user" ? m.content.replace(/\[Attached file: [^\]]*\]\n?/g, "").trim() : m.content,
      })),
    );
  }, []);

  const newChat = async () => {
    try {
      const r = await new VaelonApi(tokenRef.current).chatAction("new");
      if (r.ok) {
        setLines([]);
        note(tRef.current.chatStarted);
      } else note(r.error === "wait for the running tasks to finish first" ? tRef.current.chatBusy : r.error || tRef.current.chatsFail);
    } catch {
      note(tRef.current.chatsFail);
    }
  };

  const toggleVoice = () => {
    const next = !voiceRef.current;
    voiceRef.current = next;
    setVoiceOn(next);
    setVoiceFx(next);
    if (!next) speaker.current?.cancel();
    store("local", VOICE_KEY, next ? "1" : "0");
  };

  const attach = async (files: FileList | File[] | null) => {
    for (const f of Array.from(files ?? []).slice(0, 4)) {
      try {
        const saved = await new VaelonApi(tokenRef.current).upload(f);
        setClips((c) => [...c, saved].slice(-4));
      } catch (e) {
        note(`${tRef.current.attachFail}: ${e instanceof Error ? e.message : ""}`);
      }
    }
  };

  // the window opens on the conversation that was open last time
  useEffect(() => {
    if (!token) return;
    const api = new VaelonApi(token);
    api
      .chats()
      .then((rows) => {
        const open = rows.find((r) => r.current);
        return open && open.count ? api.chat(open.id) : [];
      })
      .then((messages) => {
        if (messages.length && !startedRef.current) showChat(messages); // not over something already said in this window
      })
      .catch(() => undefined);
  }, [token, showChat]);

  // a brand-new installation gets the first-run setup once
  useEffect(() => {
    if (!token) return;
    new VaelonApi(token)
      .settings()
      .then((s) => {
        if (s.first_run) setSetup(s);
        setWarnings(s.warnings ?? []); // code or security settings changed outside Vaelon: the owner must see it
        if (s.update_check) {
          // the user turned the daily check on: say so once when a newer version exists (details in Settings)
          void new VaelonApi(token).updateCheck()
            .then((u) => u.newer && note(tRef.current.updateNote.replace("{latest}", u.latest)))
            .catch(() => undefined);
        }
      })
      .catch(() => undefined);
  }, [token, note]);

  // reminders that fired and results of scheduled tasks: shown, and read aloud when the voice is on
  useEffect(() => {
    if (!token) return;
    let last = -1;
    let stop = false;
    const poll = async () => {
      try {
        const api = new VaelonApi(token);
        if (last < 0) {
          const old = await api.notices(0); // skip what fired before this window opened
          last = old.reduce((m, n) => Math.max(m, n.id), 0);
          return;
        }
        for (const n of await api.notices(last)) {
          last = Math.max(last, n.id);
          const label = n.kind === "reminder" ? tRef.current.reminder : tRef.current.scheduledResult;
          push("vaelon", `**${label}:** ${n.text}`);
          setToast(`${label}: ${n.text.slice(0, 80)}`);
          swarmRef.current?.pulse(1);
          if (voiceRef.current || convRef.current) speaker.current?.announce(`${label}. ${n.text}`);
        }
      } catch {
        /* the core is restarting: try again next time */
      }
    };
    void poll();
    const id = setInterval(() => !stop && void poll(), 8000);
    return () => {
      stop = true;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const cancelTask = (task: Task, silent = false) => {
    if (silent) silentRef.current.add(task.id);
    if (!task.id.startsWith("local-")) void new VaelonApi(tokenRef.current).cancel(task.id).catch(() => undefined);
  };

  const stopAll = () => {
    speaker.current?.cancel();
    heldRef.current = false;
    for (const k of tasksRef.current) cancelTask(k, true);
    note(tRef.current.stoppedAll);
  };

  useEffect(() => {
    const open = (e: Event) => setHelp(String((e as CustomEvent).detail || "start"));
    window.addEventListener("vaelon-help", open);
    return () => window.removeEventListener("vaelon-help", open);
  }, []);

  const slash = async (cmd: string): Promise<boolean> => {
    const c = cmd.toLowerCase();
    const personal = ["/memory", "/keys", "/settings", "/setup", "/voice", "/calendar", "/chats", "/new", "/clear", "/talk",
      "/talk here", "/feedback"];
    if (!isOwner && personal.includes(c)) {
      note(t.ownerOnly);
      return true;
    }
    if (["/help", "/guide", "/feedback"].includes(c)) setHelp(c === "/feedback" ? "feedback" : "start");
    else if (["/menu", "/examples"].includes(c)) setMenu("examples");
    else if (c === "/memory") setMenu("memory");
    else if (["/keys", "/settings", "/setup"].includes(c)) setSettingsPanel(true);
    else if (c === "/about") setMenu("about");
    else if (c === "/talk") void toggleConv();
    else if (c === "/talk here") void toggleConv(true);
    else if (c === "/stop") stopAll();
    else if (c === "/voice") {
      setVoiceFx(true);
      setVoicePanel(true);
    } else if (c === "/speed") {
      setSpeed(!speedOn());
      note(speedOn() ? t.speedOnNote : t.speedOffNote);
    } else if (c === "/chats") setChatsPanel(true);
    else if (["/calendar", "/agenda"].includes(c)) setCalendarPanel(true);
    else if (["/bills", "/invoices"].includes(c)) setBillsPanel(c === "/bills" ? "due" : "invoices");
    else if (["/budget", "/money"].includes(c)) setBillsPanel("budget");
    else if (c === "/cashflow") setBillsPanel("cashflow");
    else if (["/deals", "/pipeline"].includes(c)) setBillsPanel("deals");
    else if (["/company", "/journal"].includes(c)) setBillsPanel("company");
    else if (c === "/new") void newChat();
    else if (c === "/clear") {
      try {
        await new VaelonApi(token).clearHistory();
        setLines([]);
        note(t.cleared);
      } catch {
        note(t.clearFail);
      }
    } else return false;
    return true;
  };

  /** Start a task. It runs next to any task that is already working (each gets its own swarm cluster). */
  const send = async (given?: string, how?: { spoken?: boolean; timed?: boolean }) => {
    const typed = (given ?? input).trim();
    const attached = given === undefined ? clipsRef.current : [];
    if (!typed && !attached.length) return;
    if (given === undefined) setInput("");
    if (typed.startsWith("/") && !attached.length && (await slash(typed))) return;
    if (tasksRef.current.length >= MAX_TASKS) return note(t.tooMany);
    // the core reads "[Attached file: <path>]" lines: it looks at the picture / reads the document first
    const text = [typed || "Describe this.", ...attached.map((a) => `[Attached file: ${a.path}]`)].join("\n");
    if (attached.length) setClips([]);
    push("you", typed || "Describe this.", attached.length ? { clips: attached.map((a) => a.name) } : undefined);
    const used = tasksRef.current.map((k) => k.slot);
    const slot = [0, 1, 2, 3].find((s) => !used.includes(s)) ?? 0;
    const talk = voiceRef.current || speakOnce.current || convRef.current;
    speakOnce.current = false;
    let id = `local-${nextId.current++}`;
    const alone = tasksRef.current.every((k) => silentRef.current.has(k.id));
    if (alone || how?.spoken) {
      // the newest question owns the voice: its answer is read while it is being written
      speaker.current?.cancel();
      ownerRef.current = id;
    }
    mutate((list) => [...list, { id, slot, text, state: null, started: Date.now(), talk }]);
    const api = new VaelonApi(tokenRef.current);
    const clocked = ownerRef.current === id; // the stopwatch follows the newest question
    if (clocked && !how?.timed) watch.current.start(); // a spoken phrase started it when you stopped talking
    const tell = (done: boolean) => {
      if (!clocked || !speedOn()) return;
      const w = tRef.current;
      const line = watch.current.report(done, talk, { heard: w.speedHeard, first: w.speedFirst, voice: w.speedVoice });
      if (line) push("sys", `⏱ ${line} (${w.speedTail})`);
    };
    if (clocked && speaker.current) {
      speaker.current.onSound = () => {
        watch.current.mark("voice");
        tell(false);
      };
    }
    let shared = tasksRef.current.length > 1;
    let last: JobState | null = null;
    const gen = genRef.current;
    try {
      const job = await api.send(text, !!how?.spoken);
      const local = id;
      id = job;
      if (ownerRef.current === local) ownerRef.current = job;
      if (silentRef.current.delete(local)) cancelTask({ id: job } as Task, true); // stopped before it had a number
      mutate((list) => list.map((k) => (k.id === local ? { ...k, id: job } : k)));
      setInspect((cur) => (cur === local ? job : cur));
      let rev = -1;
      let seenLearned = 0;
      for (let i = 0; i < 4000; i++) {
        const st = await api.job(job, rev);
        if (genRef.current !== gen) break; // someone else is at the keyboard now: never show them this answer
        rev = st.rev;
        last = st;
        if (tasksRef.current.length > 1) shared = true;
        mutate((list) => list.map((k) => (k.id === job ? { ...k, state: st } : k)));
        const learned = st.learned ?? [];
        if (learned.length > seenLearned) {
          const lw = t.learnWords as Record<string, string>;
          note(t.learned + ": " + learned.slice(seenLearned).map((k) => lw[k] ?? k).join(", "));
          swarmRef.current?.pulse(1);
          seenLearned = learned.length;
        }
        const mine = ownerRef.current === job;
        if (clocked && (st.partial || st.answer)) watch.current.mark("words");
        if (talk && mine && st.status !== "done") speaker.current?.feed(st.partial);
        if (st.status === "done") {
          if (st.cancelled) {
            if (!silentRef.current.has(job)) push("sys", t.cancelledNote);
          } else {
            push("vaelon", st.answer, { ...(shared ? { re: typed, slot } : {}), files: st.files?.length ? st.files : undefined });
            if (talk) {
              if (mine) speaker.current?.finish(st.answer);
              else speaker.current?.announce(st.answer); // a side task: read it after what is being said now
            }
          }
          swarmRef.current?.burst(slot);
          tell(true);
          if (clocked && talk) setTimeout(() => tell(true), 2500); // the voice may start a moment after the text
          break;
        }
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "error";
      if (genRef.current !== gen) {
        /* locked meanwhile: nothing to say */
      } else if (msg === "BAD TOKEN") {
        setToken("");
        push("sys", t.keyRejected);
      } else if (msg === "HTTP 429") note(t.tooManyServer);
      else push("sys", `${t.linkLost}: ${msg}`);
    } finally {
      const mineNow = tasksRef.current.find((k) => k.id === id);
      if (mineNow && inspectRef.current === id) setFinished({ ...mineNow, state: last, done: true });
      mutate((list) => list.filter((k) => k.id !== id));
      silentRef.current.delete(id);
      if (!convRef.current) inputRef.current?.focus();
    }
  };
  const sendRef = useRef(send);
  sendRef.current = send;

  /** One spoken command: press, talk, it stops by itself. */
  const toggleMic = async () => {
    if (convRef.current) return void toggleConv();
    if (mic === "listening") {
      micRef.current?.stop();
      return;
    }
    if (mic !== "off") return;
    setVoiceFx(true); // the click also unlocks audio playback for the spoken answer
    speaker.current?.cancel();
    setMic("listening");
    micRef.current = await recordCommand({
      onLevel: (l) => {
        micLevel.current = l;
        shellRef.current?.style.setProperty("--mic", l.toFixed(3));
      },
      onError: (msg) => {
        setMic("off");
        note(msg);
      },
      onDone: async (blob, mime) => {
        setMic("transcribing");
        try {
          const text = await new VaelonApi(tokenRef.current).transcribe(blob, mime);
          setMic("off");
          if (!text) return note(t.micNoEngine);
          speakOnce.current = true;
          void sendRef.current(text);
        } catch (e) {
          setMic("off");
          note(e instanceof Error ? e.message : t.micNoEngine);
        }
      },
    });
    if (!micRef.current) setMic("off");
  };

  /** A phrase was cut out of the open microphone: decide whether it is a command, an interruption, or nothing. */
  const heardSeq = useRef(0);
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
      const plain = (w: Blob) => api.transcribe(w, "audio/wav");
      text = earlyText.current ? await earlyText.current.final(wav, early) : (await plain(wav)).trim();
      if (phrase !== heardSeq.current) return;
    } catch (e) {
      resume();
      return note(e instanceof Error ? e.message : tRef.current.micNoEngine);
    }
    watch.current.mark("heard");
    // silence, a cough, or Vaelon's own sentence coming back through the speakers: carry on as if nothing happened
    const interrupting = over || wasHeld;
    if (isGhost(text, ms) || (interrupting && isEcho(text, said))) return resume();
    if (isStop(text, interrupting)) {
      heldRef.current = false;
      return stopAll();
    }
    if (interrupting && isBackchannel(text)) return resume(); // "yes", "ok", "mhm" while it talks: keep talking
    heldRef.current = false;
    if (wasHeld || sp?.speaking) {
      // a real interruption: stop talking, and stop the answer that was still being written
      sp?.cancel();
      const owner = tasksRef.current.find((k) => k.id === ownerRef.current);
      if (owner) cancelTask(owner, true);
    }
    void sendRef.current(text, { spoken: true, timed: true });
  };

  /** The companion: a small always-on-top window that takes over the conversation (desktop app: a real second
   *  window and this one hides; in a browser: a popup). Returns false when it cannot be opened. */
  const openMini = async (): Promise<boolean> => {
    type Desk = { pywebview?: { api?: { mini?: (on: boolean) => Promise<boolean> } } };
    try {
      const api = (window as unknown as Desk).pywebview?.api;
      if (api?.mini) {
        speaker.current?.cancel();
        await api.mini(true);
        return true;
      }
      const w = window.open(`/mini/#k=${encodeURIComponent(tokenRef.current)}`, "vaelon-mini", "popup=yes,width=380,height=148");
      if (w) speaker.current?.cancel();
      return !!w;
    } catch {
      return false;
    }
  };

  /** Hands-free conversation on/off: the microphone stays open, every phrase becomes a request. */
  const toggleConv = async (inWindow = false) => {
    if (!convRef.current && !inWindow && (await openMini())) {
      note(tRef.current.miniOpened);
      return;
    }
    if (convRef.current) {
      loopRef.current?.stop();
      loopRef.current = null;
      convRef.current = false;
      setConv(false);
      setHearing(false);
      note(tRef.current.talkEnded);
      return;
    }
    micRef.current?.stop();
    setVoiceFx(true); // this click also unlocks audio playback
    const handle = await listenLoop({
      onLevel: (l) => {
        micLevel.current = l;
        shellRef.current?.style.setProperty("--mic", l.toFixed(3));
      },
      loud: () => !!speaker.current?.speaking,
      onSpeech: (on) => {
        setHearing(on);
        if (on) warmUp(new VaelonApi(tokenRef.current)); // connections open by the time you finish the sentence
        if (on && speaker.current?.speaking) {
          speaker.current.hold(true); // pause at once; resumed if it was only noise
          heldRef.current = true;
        }
      },
      onError: (msg) => note(msg),
      onEarly: (wav) => earlyText.current?.early(wav),
      onUtterance: (wav, ms, over, early) => void heard(wav, ms, over, early),
    });
    if (!handle) return;
    loopRef.current = handle;
    convRef.current = true;
    setConv(true);
    note(tRef.current.talkStarted);
    // privacy: say where the speech is turned into text - on this PC, or in the cloud you already use
    new VaelonApi(tokenRef.current)
      .voice()
      .then((v) => {
        // transcribing early pays off with a fast cloud engine; a local one on this CPU would only be slowed down
        earlyText.current = v.stt === "groq" ? new EarlyText((w) => new VaelonApi(tokenRef.current).transcribe(w, "audio/wav")) : null;
        push("sys", v.stt === "groq" ? tRef.current.talkCloud : v.stt ? tRef.current.talkLocal : tRef.current.micNoEngine);
      })
      .catch(() => undefined);
  };

  const decide = async (allow: boolean) => {
    if (!pending) return;
    try {
      await new VaelonApi(token).approve(pending.id, allow, pending.state?.approval?.id ?? "");
      push("sys", allow ? t.allowed : t.denied);
    } catch {
      push("sys", t.approveFail);
    }
  };

  const word = (tool: string) => toolWord(tool, t);
  const state =
    online === false
      ? t.offline
      : mode === "speak"
        ? t.speaking
        : tasks.length > 1
          ? `${tasks.length} ${t.tasksRunning}`
          : solo
            ? cap(soloTool ? word(soloTool) : thinkWord)
            : hearing
              ? t.hearing
              : conv || mic === "listening"
                ? t.listening
                : t.awake;
  const inspected = tasks.find((k) => k.id === inspect) ?? (finished && finished.id === inspect ? finished : null);
  const split = tasks.length > 1;

  const owner = isOwner; // the personal parts are the owner's alone
  // locked, or another person signed in: the screen, the voice and every open panel of the one before go away
  const person = !company ? null : !company.enabled ? "owner" : company.locked ? "" : company.user?.id ?? "";
  const personRef = useRef<string | null>(null);
  useEffect(() => {
    if (person === null) return;
    const before = personRef.current;
    personRef.current = person;
    if (before === null || before === person) return;
    genRef.current += 1;
    for (const k of tasksRef.current) silentRef.current.add(k.id);
    mutate(() => []);
    setLines([]);
    speaker.current?.cancel();
    loopRef.current?.stop();
    loopRef.current = null;
    micRef.current?.stop();
    convRef.current = false;
    setConv(false);
    setHearing(false);
    setFinished(null);
    setInspect(null);
    setMenu(null);
    setHelp(null);
    setVoicePanel(false);
    setSettingsPanel(false);
    setChatsPanel(false);
    setCalendarPanel(false);
    setBillsPanel(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [person]);
  const refreshCompany = useCallback(() => {
    if (!token) return;
    new VaelonApi(token).company().then(setCompany).catch(() => undefined);
  }, [token]);
  useEffect(() => {
    refreshCompany();
    const again = () => refreshCompany();
    window.addEventListener("vaelon-locked", again);
    return () => window.removeEventListener("vaelon-locked", again);
  }, [refreshCompany]);
  const lockNow = () => {
    new VaelonApi(token).companyAct({ action: "sign_out" }).then((r) => {
      if (r.ok && r.state) setCompany(r.state);
      else note(r.error || t.companyFail);
    }).catch(() => note(t.companyFail));
  };

  return (
    <main ref={shellRef} className={`shell ${fx.body} mode-${mode} ${split ? "split" : ""} ${conv ? "conv" : ""} ${noDot ? "no-dot" : ""}`}>
      <div ref={stageRef} className="stage" />
      <div className="sky" />
      <div className={`tear ${fx.overlay ? "on " + fx.overlay : ""}`} />

      {/* halo: rings that wake up while Vaelon thinks or works (one body); split tasks carry their own labels */}
      <div className={`halo ${split ? "" : mode}`} aria-hidden>
        <i className="r1" />
        <i className="r2" />
        <i className="r3" />
        <span className="halo-word">{solo ? (soloTool ? word(soloTool) : thinkWord) : ""}</span>
      </div>

      <header className="topbar">
        <div className="brand">
          <Mark size={26} />
          <span className="brand-name">Vaelon</span>
        </div>
        <div className={`pulse-line ${busy ? "busy" : ""} ${mode} ${hearing ? "hear" : ""}`}>
          <span className="dot" /> {state}
          {busy && <span className="dots" />}
        </div>
        <span className="grow" />
        {company?.enabled && company.user && (
          <div className="company-chip">
            <span>{company.workspace.id === "personal" ? t.companyPersonal : company.workspace.name}</span>
            <em>{company.user.name} · {t.roles[company.user.role as keyof typeof t.roles] ?? company.user.role}</em>
            <button type="button" className="btn ghost" title={t.lockHint} onClick={lockNow}>
              <Icon name="lock" size={14} /> {t.lock}
            </button>
          </div>
        )}
      </header>

      {/* one label per running task: on its own cluster when the swarm is split. Click = inspect that task. */}
      {token && busy && (
        <div className={`tags ${split ? "split" : "solo"}`}>
          {tasks.map((k) => (
            <button
              key={k.slot}
              ref={(el) => {
                tagRefs.current[k.slot] = el;
              }}
              className={`tag ${k.state?.status === "approval" ? "ask" : ""}`}
              style={{ ["--task" as string]: TASK_COLORS[k.slot] }}
              title={t.taskInspect}
              onClick={() => setInspect(k.id)}
            >
              <i className="task-dot" />
              <span className="tag-title">{short(k.text)}</span>
              <span className="tag-state">
                {taskStatus(k, t, word)} · {Math.max(0, Math.round((Date.now() - k.started) / 1000))} s
              </span>
            </button>
          ))}
        </div>
      )}

      {token && (
        <nav className="rail" aria-label={t.menu}>
          {owner && (
            <button className={`nav ${chatsPanel ? "on" : ""}`} data-tip={`${t.chats}  /chats`} aria-label={t.chats}
              onClick={() => setChatsPanel(true)}>
              <Icon name="chats" />
            </button>
          )}
          <button className={`nav ${billsPanel ? "on" : ""}`} data-tip={`${t.bills}  /budget`} aria-label={t.bills}
            onClick={() => setBillsPanel("budget")}>
            <Icon name="money" />
          </button>
          {owner && (
            <button className={`nav ${calendarPanel ? "on" : ""}`} data-tip={`${t.calendar}  /calendar`} aria-label={t.calendar}
              onClick={() => setCalendarPanel(true)}>
              <Icon name="calendar" />
            </button>
          )}
          {owner && (
            <button
              className={`nav ${voicePanel ? "on" : ""}`}
              data-tip={`${t.voiceDesigner}  /voice`}
              aria-label={t.voiceDesigner}
              onClick={() => {
                setVoiceFx(true);
                setVoicePanel(true);
              }}
            >
              <Icon name="voice" />
            </button>
          )}
          <button className={`nav ${menu ? "on" : ""}`} data-tip={`${t.menuShort}  /menu`} aria-label={t.menu} onClick={() => setMenu("examples")}>
            <Icon name="examples" />
          </button>
          <span className="grow" />
          <button className={`nav ${help ? "on" : ""}`} data-tip={`${t.help}  /help`} aria-label={t.help} onClick={() => setHelp("start")}>
            <Icon name="help" />
          </button>
          {owner && (
            <button className={`nav ${settingsPanel ? "on" : ""}`} data-tip={`${t.settings}  /settings`} aria-label={t.settings}
              onClick={() => setSettingsPanel(true)}>
              <Icon name="settings" />
            </button>
          )}
        </nav>
      )}

      {owner && warnings.length > 0 && (
        <div className="notice alarm" role="alert">
          {warnings.map((w) => (
            <p key={w}>⚠ {w}</p>
          ))}
          <button type="button" className="btn ghost" onClick={() => setWarnings([])}>{t.close}</button>
        </div>
      )}

      {online === false && (
        <div className="notice">
          {t.coreOff} <code>vaelon daemon</code> {t.thenReload}
        </div>
      )}

      {online && !token && (
        <form
          className="gate"
          onSubmit={(e) => {
            e.preventDefault();
            const key = tokenDraft.trim();
            if (key) {
              store("session", TOKEN_KEY, key);
              setToken(key);
              setTokenDraft("");
            }
          }}
        >
          <label htmlFor="key">{t.accessKey}</label>
          <input
            id="key"
            type="password"
            autoComplete="off"
            placeholder={t.keyHint}
            value={tokenDraft}
            onChange={(e) => setTokenDraft(e.target.value)}
          />
          <button type="submit">{t.link}</button>
        </form>
      )}

      {token && (
        <>
          <section className="stream" ref={logRef} aria-live="polite">
            {lines.length === 0 && !busy && (
              <div className="welcome">
                <h2>{greeting(t)}</h2>
                <p>{t.hint}</p>
                <div className="suggest">
                  {t.suggestions.map((s) => (
                    <button key={s} type="button" onClick={() => {
                      setInput(s);
                      setTimeout(() => inputRef.current?.focus(), 0);
                    }}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {lines.map((l) =>
              l.who === "vaelon" ? (
                <div
                  key={l.id}
                  className={`msg vaelon md ${l.re ? "tinted" : ""}`}
                  style={l.re ? { ["--task" as string]: TASK_COLORS[l.slot ?? 0] } : undefined}
                >
                  {l.re && <span className="re">↳ {short(l.re, 60)}</span>}
                  <Rich text={l.text} />
                  {l.files?.map((f) => <FileCard key={f.path} file={f} token={token} t={t} onNote={note} />)}
                </div>
              ) : (
                <div key={l.id} className={`msg ${l.who}`}>
                  {l.text}
                  {l.clips?.map((name) => (
                    <span key={name} className="clip-tag">
                      📎 {name}
                    </span>
                  ))}
                </div>
              ),
            )}
            {tasks
              .filter((k) => k.state?.partial)
              .map((k) => (
                <div
                  key={k.id}
                  className={`msg vaelon md live ${split ? "tinted" : ""}`}
                  style={split ? { ["--task" as string]: TASK_COLORS[k.slot] } : undefined}
                >
                  {split && <span className="re">↳ {short(k.text, 60)}</span>}
                  <Rich text={k.state?.partial ?? ""} />
                </div>
              ))}
            {solo && !solo.state?.partial && (
              <p className="msg vaelon thinking" aria-label="Vaelon is thinking">
                <span />
                <span />
                <span />
              </p>
            )}
          </section>

          {pending?.state?.approval && (
            <div className="verdict" role="alertdialog" aria-label={t.approvalTitle}>
              <div className="verdict-title">
                <Icon name="shield" size={16} /> {t.approvalTitle} · {pending.state.approval.tool}
                {split ? ` · ${t.task} ${pending.slot + 1}` : ""}
              </div>
              <pre>{pending.state.approval.summary}</pre>
              {pending.state.approval.note && <div className="verdict-note">Vaelon: {pending.state.approval.note}</div>}
              {pending.state.approval.tainted && <div className="verdict-warn">{t.tainted}</div>}
              <div className="verdict-actions">
                <button className="deny" onClick={() => void decide(false)}>
                  {t.deny}
                </button>
                <button className="allow" onClick={() => void decide(true)}>
                  {t.allow}
                </button>
              </div>
            </div>
          )}

          {clips.length > 0 && (
            <div className="clips" title={t.attachHint}>
              {clips.map((c) => (
                <span key={c.path} className="clip">
                  📎 {short(c.name, 28)}
                  <button type="button" aria-label={t.removeAttachment} onClick={() => setClips((x) => x.filter((y) => y.path !== c.path))}>
                    ✕
                  </button>
                </span>
              ))}
            </div>
          )}
          <form
            className={`command ${dropping ? "dropping" : ""}`}
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDropping(true);
            }}
            onDragLeave={() => setDropping(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDropping(false);
              void attach(e.dataTransfer.files);
            }}
          >
            <input
              ref={fileInput}
              type="file"
              hidden
              multiple
              accept=".png,.jpg,.jpeg,.webp,.gif,.bmp,.pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.json"
              onChange={(e) => {
                void attach(e.target.files);
                e.target.value = "";
              }}
            />
            <button type="button" className="clipper" title={t.attach} aria-label={t.attach} onClick={() => fileInput.current?.click()}>
              <Icon name="clip" />
            </button>
            <input
              ref={inputRef}
              value={input}
              placeholder={dropping ? t.attachDrop : t.placeholder}
              onChange={(e) => {
                setInput(e.target.value);
                if (!input && e.target.value) warmUp(new VaelonApi(tokenRef.current)); // you began to write: connections ready by Enter
              }}
              onPaste={(e) => {
                if (e.clipboardData.files.length) {
                  e.preventDefault();
                  void attach(e.clipboardData.files);
                }
              }}
              aria-label={t.command}
            />
            <button
              type="button"
              className={`mic ${conv ? (hearing ? "listening" : "open") : mic}`}
              onClick={() => void toggleMic()}
              title={conv ? t.talkOn : mic === "listening" ? t.micListening : mic === "transcribing" ? t.micThinking : t.mic}
              aria-label={t.mic}
              aria-pressed={conv || mic === "listening"}
            >
              <Icon name="mic" />
            </button>
            <button
              type="button"
              className={`chip talk ${conv ? "on" : ""}`}
              onClick={() => void toggleConv()}
              aria-pressed={conv}
              title={t.talkTitle}
            >
              <Icon name="wave" size={15} /> {conv ? t.talkOn : t.talkOff}
            </button>
            <button type="button" className={`chip ${voiceOn ? "on" : ""}`} onClick={toggleVoice} aria-pressed={voiceOn}
              title={voiceOn ? (ttsMode === "NEURAL" ? t.voiceNeural : t.voiceBrowser) : t.voiceOff}>
              <Icon name={voiceOn ? "speaker" : "mute"} size={15} />
              <span className="chip-label">{voiceOn ? (ttsMode === "NEURAL" ? t.voiceNeural : t.voiceBrowser) : t.voiceOff}</span>
            </button>
            <button type="submit" className="go" disabled={(!input.trim() && !clips.length) || tasks.length >= MAX_TASKS} aria-label={t.send}>
              <Icon name="send" size={18} />
            </button>
          </form>
        </>
      )}

      {toast && <div className="toast">{toast}</div>}

      {inspected && token && (
        <TaskPanel
          task={inspected}
          lang={lang}
          toolWord={word}
          token={token}
          onNote={note}
          onCancel={(k) => cancelTask(k)}
          onClose={() => {
            setInspect(null);
            setFinished(null);
          }}
        />
      )}
      {menu && token && (
        <MenuPanel
          token={token}
          lang={lang}
          tab={menu}
          onTab={setMenu}
          onClose={() => setMenu(null)}
          onPick={(text) => {
            setMenu(null);
            setInput(text);
            setTimeout(() => inputRef.current?.focus(), 0);
          }}
        />
      )}
      {help && token && (
        <HelpPanel token={token} lang={lang} section={help} owner={owner} onClose={() => setHelp(null)} onNote={note} />
      )}
      {token && company?.locked && <SignIn token={token} t={t} state={company} onDone={setCompany} />}
      {billsPanel && token && (
        <BillsPanel token={token} lang={lang} tab={billsPanel} perms={company?.enabled ? company.perms : null}
          onCompany={setCompany} onClose={() => setBillsPanel(null)} onNote={note} />
      )}
      {calendarPanel && token && (
        <CalendarPanel token={token} lang={lang} onClose={() => setCalendarPanel(false)} onNote={note} />
      )}
      {chatsPanel && token && (
        <ChatsPanel
          token={token}
          lang={lang}
          onClose={() => setChatsPanel(false)}
          onNote={note}
          onShow={(messages, fresh) => {
            showChat(messages);
            note(fresh ? t.chatStarted : t.chatSwitched);
          }}
        />
      )}
      {settingsPanel && token && (
        <SettingsPanel token={token} lang={lang} onClose={() => setSettingsPanel(false)} onNote={note} />
      )}
      {setup && token && (
        <SetupWizard
          token={token}
          lang={lang}
          first={setup}
          onDone={(text) => {
            setSetup(null);
            note(text);
          }}
        />
      )}
      {voicePanel && token && (
        <VoicePanel
          token={token}
          lang={lang}
          onClose={() => setVoicePanel(false)}
          onNote={note}
          onPlay={(b) => speaker.current?.playBlob(b)}
        />
      )}
    </main>
  );
}
