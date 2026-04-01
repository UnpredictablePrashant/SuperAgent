"""
kendr.llm_router
~~~~~~~~~~~~~~~~
Multi-provider LLM routing layer.

Reads KENDR_LLM_PROVIDER (or KENDR_PROVIDER) to select the active backend,
then builds the appropriate LangChain chat client.  All provider-specific env
vars are documented in kendr/setup/catalog.py.

Supported providers
-------------------
openai          OpenAI API (default)
anthropic       Anthropic Claude API
google          Google Gemini (GenerativeAI)
xai             xAI Grok (OpenAI-compatible)
minimax         MiniMax (OpenAI-compatible)
qwen            Alibaba Qwen / DashScope (OpenAI-compatible)
glm             Zhipu GLM (OpenAI-compatible)
ollama          Ollama local server (OpenAI-compatible)
openrouter      OpenRouter multi-model gateway (OpenAI-compatible)
custom          Any OpenAI-compatible endpoint

Backward compatibility
----------------------
All existing OPENAI_MODEL_GENERAL / OPENAI_MODEL_CODING / OPENAI_API_KEY env
vars still work when provider == "openai" (or not set).
"""

from __future__ import annotations

import os
from typing import Any

# ── provider constants ────────────────────────────────────────────────────────

PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GOOGLE = "google"
PROVIDER_XAI = "xai"
PROVIDER_MINIMAX = "minimax"
PROVIDER_QWEN = "qwen"
PROVIDER_GLM = "glm"
PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_CUSTOM = "custom"

ALL_PROVIDERS = (
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_XAI,
    PROVIDER_MINIMAX,
    PROVIDER_QWEN,
    PROVIDER_GLM,
    PROVIDER_OLLAMA,
    PROVIDER_OPENROUTER,
    PROVIDER_CUSTOM,
)

# Default models per provider
_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    PROVIDER_OPENAI: "gpt-4o-mini",
    PROVIDER_ANTHROPIC: "claude-haiku-4-5",
    PROVIDER_GOOGLE: "gemini-2.0-flash",
    PROVIDER_XAI: "grok-3",
    PROVIDER_MINIMAX: "MiniMax-M2",
    PROVIDER_QWEN: "qwen-plus",
    PROVIDER_GLM: "glm-4",
    PROVIDER_OLLAMA: "llama3.2",
    PROVIDER_OPENROUTER: "openai/gpt-4o-mini",
    PROVIDER_CUSTOM: "gpt-4o-mini",
}

# Env var that holds the model name, per provider
_PROVIDER_MODEL_ENV: dict[str, str] = {
    PROVIDER_OPENAI: "",         # handled separately (general/coding split)
    PROVIDER_ANTHROPIC: "ANTHROPIC_MODEL",
    PROVIDER_GOOGLE: "GOOGLE_MODEL",
    PROVIDER_XAI: "XAI_MODEL",
    PROVIDER_MINIMAX: "MINIMAX_MODEL",
    PROVIDER_QWEN: "QWEN_MODEL",
    PROVIDER_GLM: "GLM_MODEL",
    PROVIDER_OLLAMA: "OLLAMA_MODEL",
    PROVIDER_OPENROUTER: "OPENROUTER_MODEL",
    PROVIDER_CUSTOM: "CUSTOM_LLM_MODEL",
}

# OpenAI-compatible base URLs per provider (None means use provider SDK)
_PROVIDER_BASE_URLS: dict[str, str] = {
    PROVIDER_XAI: "https://api.x.ai/v1",
    PROVIDER_MINIMAX: "https://api.minimax.chat/v1",
    PROVIDER_QWEN: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    PROVIDER_GLM: "https://open.bigmodel.cn/api/paas/v4",
    PROVIDER_OPENROUTER: "https://openrouter.ai/api/v1",
}

# API key env var per provider
_PROVIDER_API_KEY_ENV: dict[str, str] = {
    PROVIDER_OPENAI: "OPENAI_API_KEY",
    PROVIDER_ANTHROPIC: "ANTHROPIC_API_KEY",
    PROVIDER_GOOGLE: "GOOGLE_API_KEY",
    PROVIDER_XAI: "XAI_API_KEY",
    PROVIDER_MINIMAX: "MINIMAX_API_KEY",
    PROVIDER_QWEN: "QWEN_API_KEY",
    PROVIDER_GLM: "GLM_API_KEY",
    PROVIDER_OLLAMA: "",              # no key needed
    PROVIDER_OPENROUTER: "OPENROUTER_API_KEY",
    PROVIDER_CUSTOM: "CUSTOM_LLM_API_KEY",
}

# Known context-window sizes (tokens) per model name substring
_CONTEXT_WINDOWS: dict[str, int] = {
    "o1": 200000, "o3": 200000,
    "gpt-4o": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5": 16385,
    "claude": 200000,
    "gemini-2.0-flash": 1048576,
    "gemini-1.5-pro": 2097152,
    "gemini-1.5-flash": 1048576,
    "gemini": 1048576,
    "grok-3": 131072,
    "grok": 131072,
    "llama3": 131072,
    "llama": 131072,
    "mistral": 32768,
    "phi": 131072,
    "qwen": 131072,
    "glm": 131072,
    "minimax": 1000000,
}


def get_context_window(model: str) -> int:
    """Return the approximate context-window size (tokens) for a model name."""
    m = (model or "").lower()
    for key, size in _CONTEXT_WINDOWS.items():
        if key in m:
            return size
    return 128000


# ── provider detection ────────────────────────────────────────────────────────

def get_active_provider() -> str:
    """Return the active provider name (lower-cased)."""
    val = (
        os.getenv("KENDR_LLM_PROVIDER", "")
        or os.getenv("KENDR_PROVIDER", "")
    ).strip().lower()
    return val if val in ALL_PROVIDERS else PROVIDER_OPENAI


def get_api_key(provider: str) -> str:
    env = _PROVIDER_API_KEY_ENV.get(provider, "")
    if not env:
        return ""
    return os.getenv(env, "").strip()


def get_base_url(provider: str) -> str:
    if provider == PROVIDER_OLLAMA:
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        return f"{base}/v1"
    if provider == PROVIDER_CUSTOM:
        return os.getenv("CUSTOM_LLM_BASE_URL", "").strip()
    return _PROVIDER_BASE_URLS.get(provider, "")


def get_model_for_provider(provider: str, role: str = "general") -> str:
    """Return the configured model for *provider* and *role* (general or coding)."""
    # Allow global override
    global_override = os.getenv("KENDR_MODEL", "").strip()
    if global_override:
        return global_override

    if provider == PROVIDER_OPENAI:
        if role == "coding":
            return (
                os.getenv("OPENAI_MODEL_CODING", "")
                or os.getenv("OPENAI_CODEX_MODEL", "")
                or os.getenv("OPENAI_MODEL_GENERAL", "")
                or os.getenv("OPENAI_MODEL", _PROVIDER_DEFAULT_MODELS[PROVIDER_OPENAI])
            ).strip()
        return (
            os.getenv("OPENAI_MODEL_GENERAL", "")
            or os.getenv("OPENAI_MODEL", _PROVIDER_DEFAULT_MODELS[PROVIDER_OPENAI])
        ).strip()

    env = _PROVIDER_MODEL_ENV.get(provider, "")
    if env:
        val = os.getenv(env, "").strip()
        if val:
            return val

    return _PROVIDER_DEFAULT_MODELS.get(provider, "gpt-4o-mini")


# ── Ollama health check ───────────────────────────────────────────────────────

def is_ollama_running() -> bool:
    """Return True if a local Ollama server is reachable."""
    import urllib.request
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        req = urllib.request.Request(f"{base}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def list_ollama_models() -> list[dict]:
    """Return list of models available in the local Ollama server."""
    import json
    import urllib.request
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        req = urllib.request.Request(f"{base}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("models", [])
    except Exception:
        return []


# ── provider status ───────────────────────────────────────────────────────────

def provider_status(provider: str) -> dict:
    """Return a status dict for the given provider."""
    api_key_env = _PROVIDER_API_KEY_ENV.get(provider, "")
    has_key = bool(os.getenv(api_key_env, "").strip()) if api_key_env else True

    base_url = get_base_url(provider)
    model = get_model_for_provider(provider)

    if provider == PROVIDER_OLLAMA:
        running = is_ollama_running()
        models = list_ollama_models() if running else []
        return {
            "provider": provider,
            "ready": running,
            "has_key": True,
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            "model": model,
            "local_models": [m.get("name", "") for m in models],
            "note": "Running" if running else "Not running — start with: ollama serve",
        }

    if provider == PROVIDER_CUSTOM:
        url = os.getenv("CUSTOM_LLM_BASE_URL", "").strip()
        return {
            "provider": provider,
            "ready": bool(url),
            "has_key": True,
            "base_url": url,
            "model": model,
            "note": "Configured" if url else "Set CUSTOM_LLM_BASE_URL",
        }

    return {
        "provider": provider,
        "ready": has_key,
        "has_key": has_key,
        "base_url": base_url,
        "model": model,
        "api_key_env": api_key_env,
        "note": "API key configured" if has_key else f"Set {api_key_env}",
    }


def all_provider_statuses() -> list[dict]:
    """Return status for every supported provider."""
    return [provider_status(p) for p in ALL_PROVIDERS]


# ── LLM client factory ────────────────────────────────────────────────────────

def build_llm(
    provider: str | None = None,
    model: str | None = None,
    role: str = "general",
    **kwargs: Any,
) -> Any:
    """
    Build and return a LangChain chat client for the given provider.

    Falls back to OpenAI if the requested provider cannot be initialised.
    """
    p = (provider or get_active_provider()).lower()
    m = model or get_model_for_provider(p, role)

    if p == PROVIDER_ANTHROPIC:
        return _build_anthropic(m, **kwargs)
    if p == PROVIDER_GOOGLE:
        return _build_google(m, **kwargs)
    if p in (PROVIDER_OPENAI, PROVIDER_XAI, PROVIDER_MINIMAX, PROVIDER_QWEN,
             PROVIDER_GLM, PROVIDER_OPENROUTER, PROVIDER_CUSTOM):
        return _build_openai_compat(p, m, **kwargs)
    if p == PROVIDER_OLLAMA:
        return _build_ollama(m, **kwargs)

    return _build_openai_compat(PROVIDER_OPENAI, m, **kwargs)


def _build_openai_compat(provider: str, model: str, **kwargs: Any) -> Any:
    from langchain_openai import ChatOpenAI

    api_key = get_api_key(provider) or "ollama"  # ollama needs a placeholder
    base_url = get_base_url(provider)

    init: dict[str, Any] = {"model": model}
    if api_key:
        init["api_key"] = api_key
    if base_url:
        init["base_url"] = base_url
    init.update(kwargs)
    return ChatOpenAI(**init)


def _build_anthropic(model: str, **kwargs: Any) -> Any:
    from langchain_anthropic import ChatAnthropic

    api_key = get_api_key(PROVIDER_ANTHROPIC)
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set.")
    return ChatAnthropic(model=model, api_key=api_key, **kwargs)


def _build_google(model: str, **kwargs: Any) -> Any:
    from langchain_google_genai import ChatGoogleGenerativeAI

    api_key = get_api_key(PROVIDER_GOOGLE)
    if not api_key:
        raise ValueError("GOOGLE_API_KEY is not set.")
    return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, **kwargs)


def _build_ollama(model: str, **kwargs: Any) -> Any:
    try:
        from langchain_ollama import ChatOllama

        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        return ChatOllama(model=model, base_url=base, **kwargs)
    except ImportError:
        return _build_openai_compat(PROVIDER_OLLAMA, model, **kwargs)
