// Look-and-sound choices of this computer's user (Settings > Look and sound). Kept in the browser storage of the app
// (a convenience, nothing private); every open Vaelon window follows a change at once.

export type Prefs = {
  glitchVisual: boolean; // the swarm's glitch moments (split / shake / flicker / tear bars)
  glitchVoice: boolean; // the voice crackles with them while Vaelon speaks
  avatarDot: boolean; // the small orange dot in front of Vaelon's answers
};

const KEY = "vaelon_prefs";
export const DEFAULT_PREFS: Prefs = { glitchVisual: true, glitchVoice: true, avatarDot: true };

export function readPrefs(): Prefs {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}") as Partial<Prefs>;
    return {
      glitchVisual: raw.glitchVisual !== false,
      glitchVoice: raw.glitchVoice !== false,
      avatarDot: raw.avatarDot !== false,
    };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

export function writePrefs(next: Prefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* private mode: this window still follows the change below */
  }
  window.dispatchEvent(new CustomEvent("vaelon-prefs", { detail: next }));
}

/** Call `apply` now and whenever the choices change - in this window or in another Vaelon window. */
export function watchPrefs(apply: (p: Prefs) => void): () => void {
  apply(readPrefs());
  const own = (e: Event) => apply((e as CustomEvent<Prefs>).detail);
  const other = (e: StorageEvent) => {
    if (e.key === KEY) apply(readPrefs());
  };
  window.addEventListener("vaelon-prefs", own);
  window.addEventListener("storage", other);
  return () => {
    window.removeEventListener("vaelon-prefs", own);
    window.removeEventListener("storage", other);
  };
}
