/** Line icons drawn for Vaelon (24 px grid, 1.7 px stroke, round caps). One component, no icon library. */
const PATHS: Record<string, string> = {
  voice: "M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2",
  calendar: "M7 3v3M17 3v3M4 8.5h16M5.5 5h13A1.5 1.5 0 0 1 20 6.5v12a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-12A1.5 1.5 0 0 1 5.5 5ZM8 12.5h2M14 12.5h2M8 16h2",
  money: "M4 7.5A2.5 2.5 0 0 1 6.5 5H18v3M4 7.5v10A2.5 2.5 0 0 0 6.5 20H20v-4M4 7.5A2.5 2.5 0 0 0 6.5 10H20v3M15.5 13h4.5v3h-4.5a1.5 1.5 0 0 1 0-3Z",
  chats: "M20 12.5a7.5 7.5 0 0 1-11.2 6.5L4 20l1-4.6A7.5 7.5 0 1 1 20 12.5ZM9 11h6M9 14h4",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19.4 13.5l1.6 1.2-2 3.5-1.9-.8a7 7 0 0 1-2.4 1.4L14.4 21h-4l-.3-2.2a7 7 0 0 1-2.4-1.4l-1.9.8-2-3.5 1.6-1.2a7 7 0 0 1 0-3L3.8 9.3l2-3.5 1.9.8a7 7 0 0 1 2.4-1.4L10.4 3h4l.3 2.2a7 7 0 0 1 2.4 1.4l1.9-.8 2 3.5-1.6 1.2a7 7 0 0 1 0 3Z",
  examples: "M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8ZM18.5 14.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9ZM5.5 15l.7 1.5 1.5.7-1.5.7-.7 1.5-.7-1.5-1.5-.7 1.5-.7Z",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM9.5 9.3a2.6 2.6 0 0 1 5 1c0 1.7-2.5 2.3-2.5 3.7M12 17h.01",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M6.5 11h11A1.5 1.5 0 0 1 19 12.5v6a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 18.5v-6A1.5 1.5 0 0 1 6.5 11Z",
  clip: "M20.5 11.5 12 20a5 5 0 0 1-7-7l8.5-8.5a3.5 3.5 0 0 1 5 5L10 18a2 2 0 0 1-3-3l8-8",
  mic: "M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3ZM18 11a6 6 0 0 1-12 0M12 17v4M8.5 21h7",
  send: "M12 19V5M5.5 11.5 12 5l6.5 6.5",
  speaker: "M4 9.5h3.5L12 5.5v13l-4.5-4H4ZM16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11",
  mute: "M4 9.5h3.5L12 5.5v13l-4.5-4H4ZM16.5 9.5l5 5M21.5 9.5l-5 5",
  wave: "M3 12h2l2-5 3 10 3-12 3 9 2-4h3",
  close: "M6 6l12 12M18 6 6 18",
  shield: "M12 3 5 6v5.5c0 4.3 2.9 8 7 9.5 4.1-1.5 7-5.2 7-9.5V6Z",
  book: "M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5ZM20 5.5A1.5 1.5 0 0 0 18.5 4H13v16h5.5a1.5 1.5 0 0 0 1.5-1.5ZM7 8h1.5M15.5 8H17",
  code: "M8.5 8 4 12l4.5 4M15.5 8 20 12l-4.5 4M13.5 5l-3 14",
  sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM12 2.5V5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3 7 7M17 17l1.7 1.7M5.3 18.7 7 17M17 7l1.7-1.7",
};

export default function Icon({ name, size = 18, className }: { name: string; size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" className={className} fill="none"
      stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[name] ?? ""} />
    </svg>
  );
}

/** The Vaelon mark: a V of five dots that grow toward the point - the swarm, gathered. */
export function Mark({ size = 28 }: { size?: number }) {
  const dots: [number, number, number][] = [[5, 6, 1.6], [8, 11, 1.9], [12, 18.5, 2.6], [16, 11, 1.9], [19, 6, 1.6]];
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <defs>
        <linearGradient id="vaelon-mark" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffb064" />
          <stop offset="1" stopColor="#ff5a1c" />
        </linearGradient>
      </defs>
      {dots.map(([x, y, r]) => <circle key={`${x}-${y}`} cx={x} cy={y} r={r} fill="url(#vaelon-mark)" />)}
    </svg>
  );
}
