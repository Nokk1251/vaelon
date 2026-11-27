// Client for the local Vaelon API (see src/vaelon/server.py). Talks to 127.0.0.1 only.
// The built app is served BY the core, so it uses the same origin; `npm run dev` talks to the default port.
export const API_BASE =
  process.env.NEXT_PUBLIC_VAELON_API ?? (process.env.NODE_ENV === "production" ? "" : "http://127.0.0.1:8765");

export type JobState = {
  status: "running" | "approval" | "done";
  first_after?: number | null; // seconds from the request to the first words of the answer
  approval: { tool: string; summary: string; tainted: boolean; id: string; note?: string } | null;
  answer: string;
  partial: string; // text streamed so far
  tool: string; // last tool Vaelon called
  rev: number; // change counter for long-polling
  learned?: string[]; // facts Vaelon picked up about you during this job
  text?: string; // the request
  steps?: TaskStep[]; // what the task did so far
  queued?: boolean; // waiting for a free slot
  cancelled?: boolean;
  elapsed?: number; // seconds
  files?: MadeFile[]; // files this task created
};

export type MadeFile = { path: string; name: string; kb: number };
export type Attachment = MadeFile & { image: boolean };
export type Notice = { id: number; ts: number; kind: string; title: string; text: string };

export type TaskStep = { t: number; label: string; detail: string };

export type VoiceProfile = { preset: string; pitch: number; speed: number; metal: number; robot: number;
  radio: number; echo: number; space: number };

export type VoiceEngines = {
  selected: string; // auto | piper | sapi | elevenlabs
  speaking: string | null; // the engine that actually speaks now
  piper: boolean;
  windows: boolean;
  elevenlabs: boolean; // key stored
  elevenlabs_used: number;
  elevenlabs_cap: number;
};

export type Catalog = {
  tools: { name: string; description: string; group: string; risk: string; args: string[] }[];
  skills: { name: string; description: string; triggers: string[]; learned: boolean }[];
  examples: Record<string, string[]>;
  profiles: string[];
  slash: [string, string][];
  cli: [string, string][];
  memory: { profile: Record<string, string | string[]>; facts: Record<string, number>; recent: string[];
    conversation: number; learned_skills: number };
  model: { provider: string; model: string; local: boolean };
  keys: Record<string, boolean>;
  about?: { version: string; author: string; author_url?: string; license: string; source: string; text: string };
};

/** State of one API key. The key itself never leaves the core - there is no way to read it back. */
export type KeyRow = { name: string; what: string; url: string; provider: string | null; set: boolean; stored: boolean;
  age_days: number | null };
export type ModelPreset = { name: string; model: string; note: string; url: string; key: string; key_set: boolean;
  cloud: boolean };
export type Settings = {
  version: string; first_run: boolean; address_as: string; preset: string | null; model: string; local: boolean; ollama_used?: boolean;
  presets: ModelPreset[]; keys: KeyRow[]; tts_engine: string; stt_engine: string; auto_learn: boolean;
  elevenlabs_monthly_chars: number; output_dir: string; stock_sources: string[]; search_sources: string[];
  update_check?: boolean;
  mcp: { name: string; enabled: boolean; tools: number; trusted: boolean }[];
  comms: { provider: string; smtp_host: string; smtp_port: number; imap_host: string; email_ready: boolean;
    phone_ready: boolean; contacts: number; providers: string[] };
  ollama?: { reachable: boolean; models: string[] };
  profiles: Profile[]; feedback_mail: boolean; warnings?: string[];
};
export type Profile = { name: string; title: string; blurb: string; on: boolean };
export type FeedbackAnswer = { ok: boolean; error?: string | null; path?: string; mailto?: string };
export type SettingsChange = Partial<{ address_as: string; provider: string; model: string; tts_engine: string;
  stt_engine: string; auto_learn: boolean; elevenlabs_monthly_chars: number; setup_done: true; mail_provider: string;
  smtp_host: string; smtp_port: number; imap_host: string; profiles: string[]; update_check: boolean }>;
/** Cash flow (issue #42): amounts in cents of `currency`; balance null = the user has not given one. */
export type CashFlow = { currency: string; days: number; today: string; balance: number | null; balance_on: string;
  weeks: { from: string; to: string; in: number; out: number; net: number; balance: number }[];
  in_total: number; out_total: number; late_in: number; late_out: number; undated_out: number;
  possible: { client: string; title: string; close: string; weighted: number; stage: string }[];
  apart: Record<string, number>; lowest: { balance: number; week: string } | null; short_week: string };
/** Settings > Your folders: a folder whose documents Vaelon can search (issue #30). */
export type LibraryFolder = { path: string; files: number; passages: number; skipped: number; skipped_sample: string[];
  hidden: number; unavailable: string; updated: string; added: string };
/** Is there a newer Vaelon? `off` = the daily check is off (only "Check now" asks GitHub). */
export type UpdateInfo = { enabled: boolean; off?: boolean; current: string; latest: string; newer: boolean; url: string;
  error?: string | null; checking?: boolean };

export type CalEvent = { id: string; title: string; start: string; minutes: number; all_day: boolean; place: string;
  notes: string; repeat: string; remind: number | null };
export type CalDay = { date: string; label: string; weekday: number; events: CalEvent[] };
export type CalAnswer = { ok: boolean; error?: string | null; event?: CalEvent; path?: string;
  clashes?: { title: string; start: string }[] };

export type Bill = { id: string; vendor: string; amount: number; currency: string; due: string; category: string;
  number: string; notes: string; status: "unpaid" | "paid"; paid_on: string; repeat: string; remind: number | null;
  estimate: boolean; overdue: boolean; label: string };
export type Invoice = { id: string; number: string; client: string; issued: string; due: string; status: "unpaid" | "paid" | "void";
  paid_on: string; currency: string; net: number; vat: number; total: number; vat_rate: string; file: string; overdue: boolean };
export type BillsOverview = { today: string; unpaid: Bill[]; paid: Bill[]; invoices: Invoice[]; me: Record<string, string>;
  next: string; categories: string[]; currencies: string[];
  totals: { unpaid: Record<string, number>; overdue: number; paid_year: Record<string, number>;
    by_category: Record<string, Record<string, number>>; year: number } };
export type BudgetEntry = { id: string; kind: "expense" | "income"; amount: number; currency: string; category: string;
  note: string; date: string };
export type BudgetMonth = { month: string; label: string; currency: string; income: number; spent: number; left: number;
  total_limit: number | null; rows: { category: string; spent: number; limit: number | null }[]; apart: Record<string, number>;
  entries: BudgetEntry[]; bills: { id: string; vendor: string; amount: number; currency: string; category: string; date: string }[];
  categories: string[]; currencies: string[] };
export type Deal = { id: string; client: string; title: string; value: number; currency: string; stage: string; close: string;
  next_step: string; next_date: string; contact: string; notes: { date: string; text: string }[]; won_on: string;
  lost_reason: string; invoice: string; updated: string; chance: number; late: boolean; stale: boolean };
export type DealsOverview = { today: string; deals: Deal[]; stages: string[]; chance: Record<string, number>; currencies: string[];
  totals: { open: Record<string, number>; expected: Record<string, number>; won_year: Record<string, number>; won: number;
    lost: number; year: number; count: number } };
export type Workspace = { id: string; name: string; created: string };
export type Person = { id: string; name: string; role: string; workspaces: string[] };
export type CompanyState = { enabled: boolean; user: Person | null; locked: boolean; workspace: Workspace; workspaces: Workspace[];
  perms: string[]; roles: string[]; people: { id: string; name: string }[]; lock_on_start: boolean };
export type JournalEntry = { t: string; who: string; role: string; action: string; detail: string; ws: string };
export type BillsAnswer = { ok: boolean; error?: string | null; path?: string; kb?: number; bill?: Bill; invoice?: Invoice };

export type ChatRow = { id: string; title: string; updated: number; count: number; current: boolean };
export type ChatMessage = { role: "user" | "assistant"; content: string };
export type ChatsAnswer = { ok: boolean; error?: string | null; chats: ChatRow[]; current: string; messages: ChatMessage[] };

export type PullStatus = { ok?: boolean; running: boolean; model: string; status: string; completed: number; total: number;
  percent: number; error: string; done: boolean };

export type Graphics = { name: string; vram_gb: number; kind: "nvidia" | "amd" | "apple" | "integrated" | "other" };
export type Machine = { processor: string; cores: number; graphics: Graphics[]; apple_silicon: boolean; memory_gb: number;
  free_gb: number };
export type LocalModel = { name: string; size_gb: number; need_gb: number; vision: boolean; good_for: string;
  fit: "ok" | "tight" | "too_big"; speed: "fast" | "usable" | "slow" | "very_slow"; installed: boolean; in_use: boolean;
  recommended: boolean };
export type LocalModels = { machine: Machine; ollama: { reachable: boolean; models: string[] }; overhead_gb: number;
  in_use: string; in_use_installed: boolean; remote: boolean; models: LocalModel[] };

export class VaelonApi {
  constructor(private token: string) {}

  /** The Help page's feedback: saved as a text file in the output folder (mail = a draft in the user's own program). */
  feedback(kind: string, text: string, mail = false): Promise<FeedbackAnswer> {
    return this.ask("/feedback", { kind, text, mail });
  }

  /** POST that reports the core's own reason when it says no (a 400 with {error}). */
  private async ask<T extends { ok: boolean; error?: string | null }>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = (await res.json().catch(() => ({}))) as T;
    if (res.status === 401) throw new Error("BAD TOKEN");
    if (!res.ok && !data.error) throw new Error(`HTTP ${res.status}`);
    return data;
  }

  /** What the Settings screen shows. `probe` also looks whether the local model server (Ollama) is running. */
  settings(probe = false): Promise<Settings> {
    return this.req("GET", `/settings${probe ? "?probe=1" : ""}`);
  }

  /** Ask the user's Ollama to download the local model Vaelon is set to use, or `model` from Vaelon's curated list
   *  (the core refuses any other name). */
  pullModel(model?: string): Promise<PullStatus & { ok: boolean }> {
    return this.ask("/ollama/pull", model ? { model } : {});
  }

  pullStatus(model?: string): Promise<PullStatus> {
    return this.req("GET", `/ollama/pull${model ? `?model=${encodeURIComponent(model)}` : ""}`);
  }

  /** The folders of "Ask your folder" and the allowed folders a new one must be inside. */
  library(): Promise<{ folders: LibraryFolder[]; allowed: string[] }> {
    return this.req("GET", "/library");
  }

  libraryAct(action: "add" | "remove" | "refresh", path = ""): Promise<{ ok: boolean; error?: string | null;
    result?: unknown; folders?: LibraryFolder[] }> {
    return this.ask("/library", { action, path });
  }

  /** now = the user pressed "Check now"; otherwise the core answers only when the daily check is on. */
  updateCheck(now = false): Promise<UpdateInfo> {
    return this.req("GET", now ? "/update?now=1" : "/update");
  }

  /** The curated local models, what this computer has, and how well each model fits it (all read locally). */
  localModels(): Promise<LocalModels> {
    return this.req("GET", "/models/local");
  }

  saveSettings(changes: SettingsChange): Promise<{ ok: boolean; error?: string | null; settings: Settings }> {
    return this.ask("/settings", { changes });
  }

  /** Hand an API key to the core, which seals it in the encrypted vault. One way: it can never be read back. */
  setKey(name: string, value: string): Promise<{ ok: boolean; error?: string | null; keys: KeyRow[] }> {
    return this.ask("/key", { name, value });
  }

  deleteKey(name: string): Promise<{ ok: boolean; error?: string | null; keys: KeyRow[] }> {
    return this.ask("/key", { name, delete: true });
  }

  /** `count` days of the calendar from `from` (YYYY-MM-DD; default today). */
  calendar(from = "", count = 14): Promise<{ from: string; days: CalDay[]; total: number }> {
    return this.req("GET", `/calendar?from=${encodeURIComponent(from)}&days=${count}`);
  }

  /** add / cancel / skip (one date of a repeating event) / export (.ics). */
  calendarAct(body: Record<string, unknown>): Promise<CalAnswer> {
    return this.ask("/calendar", body);
  }

  /** Bills to pay, paid bills, issued invoices, business details (amounts in cents). */
  bills(): Promise<BillsOverview> {
    return this.req("GET", "/bills");
  }

  /** add / paid / unpaid / delete / invoice / invoice_paid / invoice_unpaid / invoice_void / profile / export.
   *  Nothing here pays anything: "paid" only marks a bill in the list. */
  billsAct(body: Record<string, unknown>): Promise<BillsAnswer> {
    return this.ask("/bills", body);
  }

  /** One month of the budget (YYYY-MM; default this month), amounts in cents of the budget currency. */
  budget(month = ""): Promise<BudgetMonth> {
    return this.req("GET", `/budget?month=${encodeURIComponent(month)}`);
  }

  /** Money > Cash flow: the next `days` days, week by week (issue #42). */
  cashflow(days = 90): Promise<CashFlow> {
    return this.req("GET", `/budget?view=cashflow&days=${days}`);
  }

  /** add (expense / income) / delete / limit / currency / balance. A record only: nothing moves money. */
  budgetAct(body: Record<string, unknown>): Promise<{ ok: boolean; error?: string | null; warning?: string; text?: string }> {
    return this.ask("/budget", body);
  }

  /** The sales pipeline (values in cents). */
  deals(): Promise<DealsOverview> {
    return this.req("GET", "/deals");
  }

  /** add / update / note / delete / invoice (a won deal). */
  dealsAct(body: Record<string, unknown>): Promise<{ ok: boolean; error?: string | null; path?: string; kb?: number; text?: string }> {
    return this.ask("/deals", body);
  }

  /** Company mode: on/off, who is signed in, the open company, what this person may do. */
  company(): Promise<CompanyState> {
    return this.req("GET", "/company");
  }

  /** enable / disable / sign_in / sign_out / add_user / update_user / remove_user / add_workspace / switch / ... */
  companyAct(body: Record<string, unknown>): Promise<{ ok: boolean; error?: string | null; state?: CompanyState; people?: Person[] }> {
    return this.ask("/company", body);
  }

  /** The journal of the open company and whether its chain is intact. */
  journal(): Promise<{ entries: JournalEntry[]; intact: boolean; check: string }> {
    return this.req("GET", "/journal");
  }

  /** Your conversations, newest first. */
  async chats(): Promise<ChatRow[]> {
    return (await this.req<{ chats: ChatRow[] }>("GET", "/chats")).chats;
  }

  /** The messages of one conversation, to show it again. */
  async chat(id: string): Promise<ChatMessage[]> {
    return (await this.req<{ messages: ChatMessage[] }>("GET", `/chats/${encodeURIComponent(id)}`)).messages;
  }

  /** new / open / delete / rename. Switching is refused while tasks are running. */
  chatAction(action: "new" | "open" | "delete" | "rename", id?: string, title?: string): Promise<ChatsAnswer> {
    return this.ask("/chats", { action, id, title });
  }

  models(): Promise<{ models: string[]; error: string | null }> {
    return this.req("GET", "/models");
  }

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.token}`,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 401) throw new Error("BAD TOKEN");
    if (res.status === 423) {
      // company mode: Vaelon is locked - the shell shows the sign-in
      if (typeof window !== "undefined") window.dispatchEvent(new Event("vaelon-locked"));
      throw new Error("LOCKED");
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  }

  /** Start a task. `spoken` = hands-free conversation (short, spoken-style answer). Several tasks may run at once. */
  async send(text: string, spoken = false, screen = false): Promise<string> {
    const body: Record<string, unknown> = { text };
    if (spoken) body.spoken = true;
    if (screen) body.screen = true; // you switched screen sharing on: Vaelon may look at the screen for this request
    return (await this.req<{ job: string }>("POST", "/chat", body)).job;
  }

  cancel(job: string): Promise<{ ok: boolean }> {
    return this.req("POST", "/cancel", { job });
  }

  /** Open a file Vaelon created (or show it in its folder). The core only opens documents from its own output folder. */
  async open(path: string, reveal = false): Promise<void> {
    const res = await fetch(`${API_BASE}/open`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ path, reveal }),
    });
    if (!res.ok) throw new Error(((await res.json().catch(() => ({}))) as { error?: string }).error || `HTTP ${res.status}`);
  }

  /** The bytes of a created file, for the in-app audio player and picture preview. */
  async fileBlob(path: string): Promise<Blob> {
    const res = await fetch(`${API_BASE}/file?path=${encodeURIComponent(path)}`, { headers: { Authorization: `Bearer ${this.token}` } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.blob();
  }

  /** Attach a picture or a document: it is stored in Vaelon's output folder so the tools can read it. */
  async upload(file: File): Promise<Attachment> {
    const res = await fetch(`${API_BASE}/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token}`, "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name) },
      body: file,
    });
    const body = (await res.json().catch(() => ({}))) as Attachment & { error?: string };
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    return body;
  }

  /** Reminders that fired and results of scheduled tasks since notice `since`. */
  async notices(since: number): Promise<Notice[]> {
    return (await this.req<{ notices: Notice[] }>("GET", `/notices?since=${since}`)).notices;
  }

  /** Long-poll: returns as soon as the job changes after `since` (or after ~15 s). No busy polling. */
  job(id: string, since = -1): Promise<JobState> {
    return this.req<JobState>("GET", `/job/${id}?since=${since}`);
  }

  /** `card` = the id of the approval card being answered (a stale card or a double click cannot approve the next one). */
  approve(job: string, allow: boolean, card: string): Promise<{ ok: boolean }> {
    return this.req("POST", "/approve", { job, allow, card });
  }

  catalog(lang = "en"): Promise<Catalog> {
    return this.req("GET", `/catalog?lang=${lang === "bg" ? "bg" : "en"}`);
  }

  voice(): Promise<{ voice: VoiceProfile; presets: Record<string, Omit<VoiceProfile, "preset">>;
    limits: Record<string, [number, number]>; engine: string; engines: VoiceEngines; stt: string | null;
    live?: { available: boolean; port: number; key: boolean; library: boolean; model: string } }> {
    return this.req("GET", "/voice");
  }

  saveVoice(voice: VoiceProfile, engine?: string): Promise<{ voice: VoiceProfile; engines: VoiceEngines }> {
    return this.req("POST", "/voice", engine ? { voice, engine } : { voice });
  }

  /** Spoken command -> text (local Whisper, or Groq Whisper if Groq is your provider). */
  async transcribe(audio: Blob, mime: string): Promise<string> {
    const res = await fetch(`${API_BASE}/stt`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token}`, "Content-Type": mime || "audio/webm" },
      body: audio,
    });
    const body = (await res.json().catch(() => ({}))) as { text?: string; error?: string };
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    return body.text ?? "";
  }

  /** Have the connections for the next request opened now (you started talking or typing). Sends nothing to anyone. */
  warm(): Promise<{ ok: boolean; warming: string[] }> {
    return this.req("POST", "/warm", {});
  }

  clearHistory(): Promise<{ ok: boolean }> {
    return this.req("POST", "/history/clear", {});
  }

  /** Speak a sample with an unsaved voice profile. */
  async preview(text: string, voice: VoiceProfile): Promise<Blob> {
    const res = await fetch(`${API_BASE}/tts`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.blob();
  }
}

export async function apiReachable(): Promise<boolean> {
  try {
    return (await fetch(`${API_BASE}/health`)).ok;
  } catch {
    return false;
  }
}
