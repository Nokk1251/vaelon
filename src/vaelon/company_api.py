"""What the app's company screen may do (POST /company). Every change is journaled by company.py."""
from __future__ import annotations

from . import company


def act(service, data: dict) -> tuple[int, dict]:
    """enable / disable / sign_in / sign_out / add_user / update_user / remove_user / add_workspace /
    rename_workspace / switch / lock_on_start. Returns (HTTP status, answer)."""
    action = data.get("action")
    try:
        # A task keeps the person and company it started with (company.bind), so locking is always allowed. Changing
        # who is signed in or which company is open waits only for tasks that were not stopped (a stopped task whose
        # model call hangs must never keep Vaelon from being locked or handed over).
        busy = sum(1 for j in list(getattr(service, "jobs", {}).values()) if j.status != "done" and not j.cancelled) \
            if hasattr(service, "jobs") else service.open_jobs()
        if action in ("enable", "disable", "sign_in", "switch") and busy:
            return 409, {"ok": False, "error": "wait for the running tasks to finish (or stop them) first"}
        if action == "enable":
            u = company.enable(str(data.get("name", "")), str(data.get("pin", "")))
            return 200, {"ok": True, "user": u, "state": company.state()}
        if action == "disable":
            company.disable(str(data.get("pin", "")))
            return 200, {"ok": True, "state": company.state()}
        if action == "sign_in":
            u = company.sign_in(str(data.get("user", "")), str(data.get("pin", "")))
            return 200, {"ok": True, "user": u, "state": company.state()}
        if action == "sign_out":  # always allowed: running tasks keep their own person and company
            company.sign_out()
            return 200, {"ok": True, "state": company.state()}
        if not company.enabled():
            return 400, {"ok": False, "error": "company mode is off"}
        if action == "add_user":
            u = company.add_user(str(data.get("name", "")), str(data.get("role", "")), str(data.get("pin", "")),
                                 [str(w) for w in data.get("workspaces") or []])
            return 200, {"ok": True, "user": u, "state": company.state()}
        if action == "update_user":
            u = company.update_user(str(data.get("id", "")), data.get("role") or None, data.get("pin") or None,
                                    [str(w) for w in data["workspaces"]] if isinstance(data.get("workspaces"), list) else None)
            return 200, {"ok": True, "user": u, "state": company.state()}
        if action == "remove_user":
            company.remove_user(str(data.get("id", "")))
            return 200, {"ok": True, "state": company.state()}
        if action == "add_workspace":
            w = company.add_workspace(str(data.get("name", "")))
            return 200, {"ok": True, "workspace": w, "state": company.state()}
        if action == "rename_workspace":
            company.rename_workspace(str(data.get("id", "")), str(data.get("name", "")))
            return 200, {"ok": True, "state": company.state()}
        if action == "switch":
            company.switch(str(data.get("id", "")))
            return 200, {"ok": True, "state": company.state()}
        if action == "lock_on_start":
            company.set_lock_on_start(bool(data.get("on")))
            return 200, {"ok": True, "state": company.state()}
        if action == "people":
            company.require("users.manage")
            return 200, {"ok": True, "people": company.users(), "workspaces": company.load()["workspaces"]}
    except company.Denied as e:
        return 403, {"ok": False, "error": str(e)}
    except (ValueError, TypeError) as e:
        return 400, {"ok": False, "error": str(e) or "bad value"}
    return 400, {"ok": False, "error": "unknown action"}
