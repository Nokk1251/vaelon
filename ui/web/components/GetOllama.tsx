const OLLAMA_DOWNLOAD = "https://ollama.com/download"; // a fixed address: the official download page (Windows / macOS)

/** Opens Ollama's official download page in the system browser (the app window sends outside links there). */
export default function GetOllama({ t }: { t: { getOllama: string } }) {
  return (
    <a className="btn" href={OLLAMA_DOWNLOAD} target="_blank" rel="noopener noreferrer">
      {t.getOllama}
    </a>
  );
}
