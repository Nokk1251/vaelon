"""One-command model providers. Local stays the default; cloud ones are faster/smarter but your text leaves the PC.

  vaelon provider groq            # switch (prints where to get the free key)
  vaelon key set GROQ_API_KEY     # paste the key once - stored ENCRYPTED in the vault, never in config.json
  vaelon models                   # list the models your key can use; vaelon config model <name> to pick one

Secrets are redacted from outbound text (`redact_outbound`), but the conversation itself is sent to the provider.
"""
from __future__ import annotations

PRESETS = {
    "local": {"provider": "ollama", "base_url": "", "model": "qwen3:4b-instruct", "api_key_env": "",
              "free": "free, private, runs on your PC", "url": "https://ollama.com/library"},
    "groq": {"provider": "openai", "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b",
             "api_key_env": "GROQ_API_KEY", "free": "free tier, extremely fast",
             "url": "https://console.groq.com/keys"},
    "gemini": {"provider": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": "gemini-3-flash-preview", "api_key_env": "GEMINI_API_KEY", "free": "free tier, very smart",
               "url": "https://aistudio.google.com/apikey"},
    "openrouter": {"provider": "openai", "base_url": "https://openrouter.ai/api/v1",
                   "model": "meta-llama/llama-3.3-70b-instruct:free", "api_key_env": "OPENROUTER_API_KEY",
                   "free": "many free models (:free)", "url": "https://openrouter.ai/keys"},
    "cerebras": {"provider": "openai", "base_url": "https://api.cerebras.ai/v1", "model": "llama-3.3-70b",
                 "api_key_env": "CEREBRAS_API_KEY", "free": "free tier, very fast",
                 "url": "https://cloud.cerebras.ai"},
    "mistral": {"provider": "openai", "base_url": "https://api.mistral.ai/v1", "model": "mistral-small-latest",
                "api_key_env": "MISTRAL_API_KEY", "free": "free 'Experiment' plan, EU company",
                "url": "https://console.mistral.ai/api-keys"},
    "openai": {"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini",
               "api_key_env": "OPENAI_API_KEY", "free": "paid", "url": "https://platform.openai.com/api-keys"},
    "anthropic": {"provider": "anthropic", "base_url": "", "model": "claude-sonnet-5-5",
                  "api_key_env": "ANTHROPIC_API_KEY", "free": "paid, the smartest",
                  "url": "https://console.anthropic.com/settings/keys"},
}

# Optional keys for extra powers (all have free tiers). Store with: vaelon key set NAME
EXTRA_KEYS = {
    "ELEVENLABS_API_KEY": ("studio-quality voices in any language (cloud)", "https://elevenlabs.io/app/settings/api-keys"),
    "TWILIO_ACCOUNT_SID": ("phone calls and SMS", "https://console.twilio.com"),
    "TWILIO_AUTH_TOKEN": ("phone calls and SMS", "https://console.twilio.com"),
    "VAELON_TELEGRAM_TOKEN": ("control Vaelon from your phone (Telegram bot)", "https://t.me/BotFather"),
    "GITHUB_TOKEN": ("higher GitHub research limits (read-only token)", "https://github.com/settings/tokens"),
    "VAELON_SMTP_PASS": ("send email (Gmail app password)", "https://myaccount.google.com/apppasswords"),
    "TWELVEDATA_API_KEY": ("stock prices and history from an official source (free key)", "https://twelvedata.com/pricing"),
    "FINNHUB_API_KEY": ("real-time US stock quotes (free key)", "https://finnhub.io/register"),
    "TAVILY_API_KEY": ("reliable web search through an official API (free plan)", "https://app.tavily.com"),
    "BRAVE_SEARCH_API_KEY": ("reliable web search through Brave's official API (free plan)", "https://api-dashboard.search.brave.com"),
}


# Each key may only ever be sent to its own provider. If config.json is tampered with to point base_url
# elsewhere, the key is withheld (see llm._key).
KEY_HOSTS = {
    "GROQ_API_KEY": "api.groq.com", "GEMINI_API_KEY": "generativelanguage.googleapis.com",
    "OPENROUTER_API_KEY": "openrouter.ai", "CEREBRAS_API_KEY": "api.cerebras.ai", "MISTRAL_API_KEY": "api.mistral.ai",
    "OPENAI_API_KEY": "api.openai.com", "ANTHROPIC_API_KEY": "api.anthropic.com",
    "TWELVEDATA_API_KEY": "api.twelvedata.com", "FINNHUB_API_KEY": "finnhub.io",
    "TAVILY_API_KEY": "api.tavily.com", "BRAVE_SEARCH_API_KEY": "api.search.brave.com",
}


def key_allowed(key_env: str, base_url: str) -> bool:
    from urllib.parse import urlparse

    want = KEY_HOSTS.get(key_env)
    if not want:
        return True  # custom/self-hosted key: the user chose the server
    host = (urlparse(base_url).hostname or "").lower()
    return host == want


# Providers retire models often. If the preset model is gone, the first available one from this list is used.
PREFERRED = {
    "groq.com": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"],
    "openrouter.ai": ["meta-llama/llama-3.3-70b-instruct:free", "openai/gpt-oss-120b:free"],
    # checked 2026-11-11 on a free key (gemini-2.5-flash is closed to new users)
    "googleapis.com": ["gemini-3-flash-preview", "gemini-flash-latest", "gemini-3.1-flash-lite"],
}


def pick_available(cfg, name: str) -> str | None:
    """Make sure cfg.model really exists for this key; switch to a preferred available model if not.
    Returns the new model name if it changed, None otherwise (or when the list cannot be fetched)."""
    try:
        models = set(list_models(cfg))
    except Exception:
        return None
    if not models or cfg.model in models:
        return None
    host = next((k for k in PREFERRED if k in (cfg.base_url or "")), "")
    for m in PREFERRED.get(host, []):
        if m in models:
            cfg.model = m
            cfg.save()
            return m
    return None


def apply(cfg, name: str):
    p = PRESETS[name]
    for k in ("provider", "base_url", "model", "api_key_env"):
        setattr(cfg, k, p[k])
    cfg.save()
    return p


def list_models(cfg) -> list[str]:
    """Models available to your key (OpenAI-compatible /models, Ollama /api/tags)."""
    import requests

    from .config import env

    if cfg.provider == "ollama":
        r = requests.get(f"{cfg.base_url or 'http://localhost:11434'}/api/tags", timeout=10)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))
    if cfg.provider == "openai":
        from .llm import _key

        key = _key(cfg)  # refuses to send a provider's key to any other server
        r = requests.get(f"{cfg.base_url or 'https://api.openai.com/v1'}/models", timeout=15,
                         headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        return sorted(m.get("id", "") for m in r.json().get("data", []))
    return [cfg.model]
