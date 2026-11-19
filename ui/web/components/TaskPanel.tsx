"use client";

import { useEffect } from "react";
import type { JobState } from "@/lib/vaelonApi";
import { STRINGS, type Lang, type Strings } from "@/lib/i18n";
import { TASK_COLORS } from "@/lib/swarm";
import Rich from "./Rich";
import FileCard from "./FileCard";

export type Task = {
  id: string;
  slot: number; // 0..3: its colour and its cluster in the swarm
  text: string; // the request
  state: JobState | null;
  started: number;
  talk: boolean; // the answer is spoken
  done?: boolean;
};

export function taskStatus(task: Task, t: Strings, toolWord: (tool: string) => string): string {
  const s = task.state;
  if (task.done) return s?.cancelled ? t.taskCancelled : t.taskDone;
  if (!s || s.queued) return t.taskQueued;
  if (s.status === "approval") return t.taskApproval;
  if (s.partial) return t.taskWriting;
  if (s.tool) return toolWord(s.tool);
  return t.taskThinking;
}

/** The inspector: everything one task has done so far, and its answer as it is being written. */
export default function TaskPanel(props: {
  task: Task;
  lang: Lang;
  toolWord: (tool: string) => string;
  token: string;
  onNote: (text: string) => void;
  onCancel: (task: Task) => void;
  onClose: () => void;
}) {
  const { task, lang, toolWord, token, onNote, onCancel, onClose } = props;
  const t = STRINGS[lang];
  const steps = task.state?.steps ?? [];
  const words = t.stepWords as Record<string, string>;
  const body = task.done ? task.state?.answer : task.state?.partial;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="panel-wrap" onClick={onClose}>
      <aside
        className="panel task"
        role="dialog"
        aria-label={t.task}
        style={{ ["--task" as string]: TASK_COLORS[task.slot % TASK_COLORS.length] }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="panel-head">
          <span className="panel-title">
            <i className="task-dot" /> {t.task} {task.slot + 1}
          </span>
          <span className="panel-sub">
            {taskStatus(task, t, toolWord)} ·{" "}
            {(task.done ? (task.state?.elapsed ?? 0) : Math.max(0, (Date.now() - task.started) / 1000)).toFixed(0)} s
          </span>
          <button className="x" onClick={onClose} aria-label={t.close}>
            ✕
          </button>
        </div>
        <div className="panel-body">
          <p className="task-ask">{task.text}</p>

          <h3>{t.taskSteps}</h3>
          {steps.length === 0 && <p className="muted scan">{t.taskNoSteps}</p>}
          <ol className="steps">
            {steps.map((s, i) => (
              <li key={i} className={i === steps.length - 1 && !task.done ? "now" : ""}>
                <b>{s.t.toFixed(1)} s</b>
                <span>{words[s.label] ?? toolWord(s.label)}</span>
                {s.detail && <em>{s.detail}</em>}
              </li>
            ))}
          </ol>

          {body && (
            <>
              <h3>{task.done ? t.taskAnswerDone : t.taskAnswer}</h3>
              <div className={`msg vaelon md ${task.done ? "" : "live"}`}>
                <Rich text={body} />
              </div>
            </>
          )}

          {(task.state?.files ?? []).map((f) => (
            <FileCard key={f.path} file={f} token={token} t={t} onNote={onNote} />
          ))}

          {!task.done && (
            <button className="task-cancel" onClick={() => onCancel(task)}>
              {t.cancelTask}
            </button>
          )}
        </div>
      </aside>
    </div>
  );
}
