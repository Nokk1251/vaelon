"""Scheduler: recurring prompts ("every morning brief me"). Unattended runs can NEVER approve
dangerous actions - they are denied automatically; results land in the inbox (~/.vaelon/inbox.jsonl)."""
from __future__ import annotations

import json
import time
import uuid

from . import config
from .security import audit
from .security.confirm import deny_all


def _file():
    return config.HOME / "schedule.enc"


def load(strict: bool = False) -> list[dict]:
    """Scheduled tasks (encrypted - a prompt can be personal). An old plain schedule.json is moved in once.
    `strict` (before writes): an unreadable file raises instead of being replaced by an empty schedule."""
    from .security import vault

    p, old = _file(), config.HOME / "schedule.json"
    try:
        if p.exists():
            return json.loads(vault.decrypt_text(p.read_text("utf-8")))
        if old.exists():
            jobs = json.loads(old.read_text("utf-8"))
            save(jobs)
            old.unlink(missing_ok=True)
            return jobs
    except Exception:
        if strict:
            raise RuntimeError("the schedule could not be read, so nothing was changed")
        return []
    return []


def save(jobs: list[dict]) -> None:
    import os

    from .security import vault

    config.HOME.mkdir(parents=True, exist_ok=True)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(vault.encrypt_text(json.dumps(jobs, ensure_ascii=False)), "utf-8")
    os.replace(tmp, _file())


def inbox_add(entry: dict) -> None:
    """One result of a scheduled task, encrypted (a morning briefing holds bills, meetings, mail)."""
    from .security import vault

    with (config.HOME / "inbox.enc").open("a", encoding="utf-8") as f:
        f.write(vault.encrypt_text(json.dumps(entry, ensure_ascii=False)) + "\n")


def inbox() -> list[dict]:
    from .security import vault

    out = []
    for name, sealed in (("inbox.jsonl", False), ("inbox.enc", True)):  # the old plain file is still read
        p = config.HOME / name
        for line in (p.read_text("utf-8").splitlines() if p.exists() else []):
            try:
                out.append(json.loads(vault.decrypt_text(line) if sealed else line))
            except (ValueError, OSError):
                continue
    return out


def add(prompt: str, every_minutes: int | None = None, daily: str | None = None) -> dict:
    if bool(every_minutes) == bool(daily):
        raise ValueError("give exactly one of every_minutes or daily (HH:MM)")
    if daily:
        time.strptime(daily, "%H:%M")
    job = {"id": uuid.uuid4().hex[:8], "prompt": prompt, "every_minutes": every_minutes, "daily": daily, "last_run": 0}
    save(load(strict=True) + [job])
    return job


def remove(job_id: str) -> bool:
    jobs = load(strict=True)
    kept = [j for j in jobs if j["id"] != job_id]
    save(kept)
    return len(kept) != len(jobs)


def is_due(job: dict, now: float | None = None) -> bool:
    now = now or time.time()
    if job.get("every_minutes"):
        return now - job["last_run"] >= job["every_minutes"] * 60
    lt = time.localtime(now)
    hh, mm = map(int, job["daily"].split(":"))
    today_due = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, -1))
    return now >= today_due and job["last_run"] < today_due


def run_due(agent_factory, now: float | None = None) -> int:
    """Run every due job once, as the OWNER in the personal space (never as whoever happens to be signed in to a
    company at that moment). Returns how many ran."""
    from . import company

    if company.enabled():
        owner = company.owner_id()
        if not owner:
            return 0
        company.bind(owner, company.PERSONAL)
    try:
        return _run_due(agent_factory, now)
    finally:
        if company.enabled():
            company.unbind()


def _run_due(agent_factory, now: float | None = None) -> int:
    jobs, ran = load(), 0
    for job in jobs:
        if not is_due(job, now):
            continue
        job["last_run"] = now or time.time()
        save(jobs)  # persist before running so a crash cannot cause a re-run storm
        try:
            answer = agent_factory().run(job["prompt"])
        except Exception as e:
            answer = f"scheduled job failed: {e}"
        audit.log("scheduled_run", job=job["id"])
        inbox_add({"ts": time.time(), "job": job["id"], "prompt": job["prompt"], "answer": answer})
        try:
            from . import reminders

            reminders.notify("Vaelon - scheduled task", f"{job['prompt']}\n\n{answer}"[:600], "task")
        except Exception:
            pass
        ran += 1
    return ran


def daemon(cfg, poll_seconds: int = 30) -> None:
    from .agent import Agent

    print("Vaelon scheduler running (unattended: dangerous actions are auto-denied). Ctrl+C to stop.")
    while True:
        run_due(lambda: Agent(cfg, approver=deny_all))
        time.sleep(poll_seconds)
