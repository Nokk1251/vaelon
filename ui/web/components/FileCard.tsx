"use client";

import { useEffect, useRef, useState } from "react";
import { VaelonApi, type MadeFile } from "@/lib/vaelonApi";
import type { Strings } from "@/lib/i18n";

const ICON: Record<string, string> = {
  pdf: "PDF", docx: "DOC", xlsx: "XLS", pptx: "PPT", wav: "♪", md: "MD", txt: "TXT", csv: "CSV", png: "IMG", jpg: "IMG", jpeg: "IMG",
};

/** A file Vaelon created: open it, show it in its folder, or play / preview it right here. */
export default function FileCard({ file, token, t, onNote }: { file: MadeFile; token: string; t: Strings; onNote: (s: string) => void }) {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  const audio = ext === "wav";
  const image = ["png", "jpg", "jpeg"].includes(ext);
  const [url, setUrl] = useState("");
  const urlNow = useRef("");
  urlNow.current = url;
  useEffect(() => () => {
    if (urlNow.current) URL.revokeObjectURL(urlNow.current); // the card goes away: so does its audio / picture
  }, []);

  useEffect(() => {
    // pictures are shown at once; audio is fetched when you press Play
    if (!image) return;
    let live = true;
    let made = "";
    new VaelonApi(token)
      .fileBlob(file.path)
      .then((b) => {
        if (!live) return;
        made = URL.createObjectURL(b);
        setUrl(made);
      })
      .catch(() => undefined);
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [file.path, image, token]);

  const open = (reveal: boolean) =>
    new VaelonApi(token).open(file.path, reveal).catch((e: unknown) => onNote(e instanceof Error ? e.message : t.fileOpenFail));

  const play = async () => {
    try {
      const made = URL.createObjectURL(await new VaelonApi(token).fileBlob(file.path));
      setUrl((old) => {
        if (old) URL.revokeObjectURL(old); // the previous clip's memory is given back
        return made;
      });
    } catch {
      onNote(t.fileOpenFail);
    }
  };

  return (
    <div className="file">
      <span className={`file-icon ${ext}`}>{ICON[ext] ?? "FILE"}</span>
      <span className="file-name" title={file.path}>
        {file.name}
        <em>{file.kb >= 1024 ? `${(file.kb / 1024).toFixed(1)} MB` : `${file.kb} KB`}</em>
      </span>
      {audio && !url && (
        <button onClick={() => void play()}>{t.filePlay}</button>
      )}
      <button onClick={() => void open(false)}>{t.fileOpen}</button>
      <button className="ghost" onClick={() => void open(true)}>
        {t.fileFolder}
      </button>
      {audio && url && <audio className="file-audio" controls autoPlay src={url} />}
      {image && url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="file-image" src={url} alt={file.name} />
      )}
    </div>
  );
}
