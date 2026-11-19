"""Provider-agnostic LLM layer. Local-first (Ollama); any OpenAI-compatible server; Anthropic.

Outbound text is scrubbed of secrets when the provider is not local.
"""
from __future__ import annotations

import json

import requests

from .config import Config, env
from .speed import HTTP as _http, used as _used  # one keep-alive pool for model, speech-to-text and cloud voice: no new handshake per call
from .security.redact import redact


class LLMError(Exception):
    pass


def _openai_body(c: Config, messages: list[dict], tools: list | None, stream: bool) -> dict:
    """Request body for OpenAI-compatible servers. With `tools`, the model uses NATIVE function calling - what
    cloud models (gpt-oss, llama, qwen, gemini...) are trained for; their calls are turned back into Vaelon's
    {"tool", "args"} JSON, so the agent loop and all safety checks stay exactly the same."""
    body = {"model": c.model, "messages": messages, "stream": stream, "temperature": 0.2,
            "max_tokens": max(c.max_tokens, 3000)}  # room for full lessons; clouds are fast and stop when done
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if "gpt-oss" in c.model and "groq.com" in (c.base_url or ""):
        body["reasoning_effort"] = "low"  # less hidden thinking = faster answers, nothing lost for an assistant
    return body


def _tool_json(name: str, arguments) -> str:
    try:
        args = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else (arguments or {})
    except ValueError:
        args = {}
    return json.dumps({"tool": name, "args": args if isinstance(args, dict) else {}}, ensure_ascii=False)


def _calls_json(calls: list) -> str:
    """One call -> {"tool", "args"}; several (asked for at once) -> {"tools": [...]} so they can run in parallel."""
    one = [json.loads(_tool_json(n, a)) for n, a in calls if n]
    if len(one) == 1:
        return json.dumps(one[0], ensure_ascii=False)
    return json.dumps({"tools": one}, ensure_ascii=False)


def _from_reasoning(reasoning: str) -> str:
    """Some reasoning models (gpt-oss) write a tool call into their hidden channel and leave the answer empty.
    Recover the call - never the private reasoning itself."""
    i = reasoning.rfind('{"tool"')
    return reasoning[i:] if i != -1 else ""


def _key(c: Config) -> str:
    """The API key for this provider - only if base_url really is that provider's server."""
    from .providers import key_allowed

    base = c.base_url or "https://api.openai.com/v1"
    for name in (c.api_key_env, "VAELON_API_KEY", "OPENAI_API_KEY"):
        if not name:
            continue
        val = env(name)
        if val:
            if not key_allowed(name, base):
                err = LLMError(f"{name} is only sent to its own provider, not to {base} (check base_url)")
                err.fatal = True
                raise err
            return val
    return ""


class MockLLM:
    """Deterministic scripted backend for tests/offline demos."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen: list[list[dict]] = []

    def chat(self, messages):
        self.seen.append(messages)
        return self.replies.pop(0) if self.replies else '{"final": "done"}'


class LLM:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _scrub(self, messages):
        if self.cfg.is_local or not self.cfg.redact_outbound:
            return messages
        return [{**m, "content": redact(m["content"])} for m in messages]

    @property
    def supports_tools(self) -> bool:
        """True when the backend takes native function calling (OpenAI-compatible clouds)."""
        return self.cfg.provider == "openai"

    @property
    def supports_schema(self) -> bool:
        """True when the backend can force structured JSON output (Ollama `format`)."""
        return self.cfg.provider == "ollama"

    def chat(self, messages: list[dict], fmt: dict | None = None, tools: list | None = None) -> str:
        """Primary model with retries/backoff, then each configured fallback (cfg.fallbacks)."""
        import time

        candidates = [self.cfg] + self._siblings() + [
            self._variant(fb) for fb in (getattr(self.cfg, "fallbacks", None) or [])
        ]
        last: Exception | None = None
        for cand in candidates:
            for attempt in range(3):
                try:
                    out = LLM(cand)._once(messages, fmt, tools if cand.provider == "openai" else None)
                    if cand is not self.cfg:
                        self.last_fallback = f"{cand.provider}:{cand.model}"
                    return out
                except LLMError as e:
                    last = e
                    if getattr(e, "fatal", False) or getattr(e, "code", 0) == 429:
                        break  # rate limit: the next model has its own separate quota - move on at once
                    time.sleep(min(2 ** attempt, 4))
        local = self._local_rescue()
        if local is not None:  # every cloud option is exhausted: the private local model answers instead
            try:
                self.last_fallback = f"ollama:{local.model}"
                return LLM(local)._once(messages, fmt if fmt else None)
            except LLMError as e:
                last = e
        raise LLMError(f"all models failed: {last}")

    def _siblings(self) -> list:
        """Other models of the same cloud provider (each has its own free per-minute quota)."""
        from .providers import PREFERRED

        if self.cfg.provider != "openai":
            return []
        name = next((k for k in PREFERRED if k in (self.cfg.base_url or "")), None)
        out = []
        for m in PREFERRED.get(name, []):
            if m != self.cfg.model:
                v = self._variant({"model": m})
                out.append(v)
        return out[:2]

    def _local_rescue(self):
        """A local Ollama model, if one is installed and running (used only after the cloud failed)."""
        if self.cfg.provider == "ollama":
            return None
        try:
            tags = _http.get("http://localhost:11434/api/tags", timeout=1.5).json().get("models", [])
        except Exception:
            return None
        names = [m["name"] for m in tags]
        pick = next((n for n in names if "instruct" in n), names[0] if names else None)
        if not pick:
            return None
        import copy

        c = copy.copy(self.cfg)
        c.provider, c.model, c.base_url, c.api_key_env, c.fallbacks = "ollama", pick, "", "", []
        return c

    def warm(self, messages: list[dict]) -> None:
        """Load the model and pre-read the static prompt (Ollama keeps it cached), so the first real question
        only has to read the new words. Best effort, never raises."""
        if self.cfg.provider != "ollama":
            return
        try:
            _http.post(f"{self.cfg.base_url or 'http://localhost:11434'}/api/chat", timeout=600,
                       json={"model": self.cfg.model, "messages": messages, "stream": False, "think": False,
                             "keep_alive": "30m", "options": {"num_ctx": self.cfg.num_ctx, "num_predict": 1}})
        except Exception:
            pass

    def chat_stream(self, messages: list[dict], fmt: dict | None = None, tools: list | None = None):
        """Yield text chunks as they are generated (Ollama and OpenAI-compatible); others yield the whole reply."""
        p, c = self.cfg.provider, self.cfg
        _used(c.base_url or "")  # this host's connection is warm now (see speed.warm)
        messages = self._scrub(messages)
        try:
            if p == "ollama":
                base = c.base_url or "http://localhost:11434"
                with _http.post(f"{base}/api/chat", stream=True, timeout=300,
                                   json={"model": c.model, "messages": messages, "stream": True, "think": False,
                                         **({"format": fmt} if fmt else {}),
                                         "keep_alive": "30m", "options": {"num_ctx": c.num_ctx, "temperature": 0.2, "num_predict": c.max_tokens}}) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if line:
                            j = json.loads(line)
                            yield j.get("message", {}).get("content", "")
                            if j.get("done"):
                                return
                return
            if p == "openai":
                base = c.base_url or "https://api.openai.com/v1"
                h = {"Authorization": f"Bearer {_key(c)}"}
                with _http.post(f"{base}/chat/completions", headers=h, stream=True, timeout=300,
                                json=_openai_body(c, messages, tools, True)) as r:
                    if r.status_code >= 400:
                        err = LLMError(f"LLM stream failed ({p}): HTTP {r.status_code} {redact(r.text[:200])}")
                        err.code = r.status_code
                        raise err
                    calls: dict[int, dict] = {}
                    reasoning, said = "", False
                    for line in r.iter_lines():
                        if not line.startswith(b"data: ") or line == b"data: [DONE]":
                            continue
                        choices = json.loads(line[6:]).get("choices") or [{}]
                        delta = choices[0].get("delta", {}) or {}
                        reasoning += delta.get("reasoning") or ""
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(tc.get("index", 0), {"name": "", "args": ""})
                            fn = tc.get("function") or {}
                            slot["name"] += fn.get("name") or ""
                            slot["args"] += fn.get("arguments") or ""
                        text = delta.get("content") or ""
                        if text:
                            said = True
                            yield text
                    if calls:
                        yield ("\n" if said else "") + _calls_json(
                            [(calls[k]["name"], calls[k]["args"]) for k in sorted(calls)])
                    elif not said:
                        yield _from_reasoning(reasoning)
                return
        except (requests.RequestException, KeyError, ValueError) as e:
            raise LLMError(f"LLM stream failed ({p}): {e}") from e
        yield self.chat(messages, fmt, tools)

    def _variant(self, fb: dict) -> Config:
        import copy

        c = copy.copy(self.cfg)
        for k in ("provider", "model", "base_url", "api_key_env"):
            if k in fb:
                setattr(c, k, fb[k])
        c.fallbacks = []
        return c

    def _once(self, messages: list[dict], fmt: dict | None = None, tools: list | None = None) -> str:
        messages = self._scrub(messages)
        p, c = self.cfg.provider, self.cfg
        _used(c.base_url or "")  # this host's connection is warm now (see speed.warm)
        try:
            if p == "ollama":
                base = c.base_url or "http://localhost:11434"
                r = _http.post(f"{base}/api/chat", timeout=300,
                                  json={"model": c.model, "messages": messages, "stream": False,
                                        **({"format": fmt} if fmt else {}),
                                        "think": False,  # skip qwen3-style hidden reasoning: much faster
                                        "keep_alive": "30m",  # keep the model in RAM between requests
                                        "options": {"num_ctx": c.num_ctx, "temperature": 0.2, "num_predict": c.max_tokens}})
                r.raise_for_status()
                return r.json()["message"]["content"]
            if p == "openai":
                base = c.base_url or "https://api.openai.com/v1"
                h = {"Authorization": f"Bearer {_key(c)}"}
                r = _http.post(f"{base}/chat/completions", headers=h, timeout=300,
                               json=_openai_body(c, messages, tools, False))
                r.raise_for_status()
                msg = r.json()["choices"][0]["message"]
                calls = msg.get("tool_calls") or []
                if calls:
                    fns = [c.get("function") or {} for c in calls]
                    return _calls_json([(f.get("name", ""), f.get("arguments", "")) for f in fns])
                return msg.get("content") or _from_reasoning(msg.get("reasoning") or "")
            if p == "anthropic":
                base = c.base_url or "https://api.anthropic.com"
                system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
                rest = [m for m in messages if m["role"] != "system"]
                from .providers import key_allowed

                if not key_allowed("ANTHROPIC_API_KEY", base):
                    err = LLMError(f"ANTHROPIC_API_KEY is only sent to api.anthropic.com, not to {base}")
                    err.fatal = True
                    raise err
                h = {"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}
                r = _http.post(f"{base}/v1/messages", headers=h, timeout=300, allow_redirects=False,
                                  json={"model": c.model, "max_tokens": 4096, "system": system, "messages": rest})
                r.raise_for_status()
                return "".join(b.get("text", "") for b in r.json()["content"])
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            detail = redact(e.response.text[:160]) if e.response is not None and code == 400 else ""
            hint = {400: f" - the provider rejected the request: {detail}",
                    401: " - the API key was rejected (vaelon key set ...)",
                    404: f" - model '{c.model}' not found; see: vaelon models",
                    429: " - rate limit / free quota reached, try again later"}.get(code, "")
            err = LLMError(f"LLM request failed ({p}): HTTP {code}{hint}")
            err.code = code
            err.fatal = 400 <= code < 500 and code not in (408, 429)  # bad key/model: retrying is pointless
            raise err from e
        except (requests.RequestException, KeyError, ValueError) as e:
            raise LLMError(f"LLM request failed ({p}): {e}") from e
        raise LLMError(f"unknown provider '{p}'")
