"""
kendr.llm_router
~~~~~~~~~~~~~~~~
Multi-provider LLM routing layer.

Reads KENDR_LLM_PROVIDER (or KENDR_PROVIDER) to select the active backend,
then builds the appropriate LangChain chat client.  All provider-specific env
vars are documented in kendr/setup/catalog.py.

Supported providers
-------------------
openai          OpenAI API
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
vars still work when provider == "openai" (or when OpenAI is inferred).
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
    PROVIDER_XAI: "grok-4",
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

_PROVIDER_DEFAULT_MODEL_SELECTION_ENV: dict[str, str] = {
    PROVIDER_OPENAI: "OPENAI_MODEL_GENERAL",
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

_PROVIDER_RELEASE_MODELS: dict[str, list[str]] = {
    PROVIDER_OPENAI: ["gpt-5", "gpt-5.1", "gpt-5-mini", "gpt-4o", "gpt-4o-mini", "o3"],
    PROVIDER_ANTHROPIC: ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"],
    PROVIDER_GOOGLE: ["gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-pro"],
    PROVIDER_XAI: ["grok-4", "grok-4.20-beta-latest-non-reasoning", "grok-4-1-fast-reasoning"],
    PROVIDER_MINIMAX: ["MiniMax-M2", "image-01"],
    PROVIDER_QWEN: ["qwen-max", "qwen-plus", "qwen-turbo"],
    PROVIDER_GLM: ["glm-5", "glm-4", "glm-4-flash"],
    PROVIDER_OLLAMA: ["llama3.2", "mistral", "deepseek-r1", "qwen2.5", "gemma3"],
    PROVIDER_OPENROUTER: [
        "openai/gpt-5",
        "openai/gpt-4o",
        "anthropic/claude-sonnet-4",
        "google/gemini-2.5-pro",
        "meta-llama/llama-3.1-8b-instruct",
    ],
    PROVIDER_CUSTOM: [],
}

_PROVIDER_MODEL_BADGE_CANDIDATES: dict[str, dict[str, list[str]]] = {
    PROVIDER_OPENAI: {
        "latest": ["gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.1", "gpt-5"],
        "best": ["gpt-5.4", "gpt-5.4-pro", "gpt-5.1", "gpt-5", "o3"],
        "cheapest": ["gpt-5-nano", "gpt-5.4-nano", "gpt-4.1-nano", "gpt-4o-mini"],
    },
    PROVIDER_XAI: {
        "latest": ["grok-4.20-beta-latest-non-reasoning", "grok-4"],
        "best": ["grok-4.20-beta-latest-non-reasoning", "grok-4", "grok-4-1-fast-reasoning"],
        "cheapest": ["grok-4-1-fast-reasoning", "grok-4"],
    },
    PROVIDER_ANTHROPIC: {
        "best": ["claude-opus-4-6", "claude-sonnet-4-6"],
        "cheapest": ["claude-haiku-4-5"],
    },
    PROVIDER_GOOGLE: {
        "best": ["gemini-2.5-pro"],
        "cheapest": ["gemini-2.0-flash"],
    },
}

_MODEL_FAMILY_RULES: list[tuple[str, str]] = [
    ("gpt-", PROVIDER_OPENAI),
    ("o1", PROVIDER_OPENAI),
    ("o3", PROVIDER_OPENAI),
    ("o4-", PROVIDER_OPENAI),
    ("claude", PROVIDER_ANTHROPIC),
    ("gemini", PROVIDER_GOOGLE),
    ("grok", PROVIDER_XAI),
    ("minimax", PROVIDER_MINIMAX),
    ("qwen", PROVIDER_QWEN),
    ("glm", PROVIDER_GLM),
    ("llama", PROVIDER_OLLAMA),
    ("mistral", PROVIDER_OLLAMA),
    ("deepseek", PROVIDER_OLLAMA),
    ("gemma", PROVIDER_OLLAMA),
    ("phi", PROVIDER_OLLAMA),
]

_MODEL_CAPABILITY_RULES: list[tuple[str, dict[str, bool]]] = [
    ("gpt-5", {"tool_calling": True, "vision": True, "structured_output": True, "reasoning": True}),
    ("gpt-4o", {"tool_calling": True, "vision": True, "structured_output": True, "reasoning": False}),
    ("o3", {"tool_calling": True, "vision": True, "structured_output": True, "reasoning": True}),
    ("claude", {"tool_calling": True, "vision": True, "structured_output": True, "reasoning": True}),
    ("gemini", {"tool_calling": True, "vision": True, "structured_output": True, "reasoning": True}),
    ("grok-4.20", {"tool_calling": True, "vision": True, "structured_output": True, "reasoning": True}),
    ("grok-4-1-fast-reasoning", {"tool_calling": True, "vision": True, "structured_output": True, "reasoning": True}),
    ("grok-4", {"tool_calling": True, "vision": True, "structured_output": True, "reasoning": True}),
    ("grok", {"tool_calling": True, "vision": True, "structured_output": True, "reasoning": True}),
    ("llama", {"tool_calling": True, "vision": False, "structured_output": False, "reasoning": False}),
    ("mistral", {"tool_calling": True, "vision": False, "structured_output": False, "reasoning": False}),
    ("qwen", {"tool_calling": True, "vision": True, "structured_output": True, "reasoning": True}),
    ("glm", {"tool_calling": True, "vision": True, "structured_output": True, "reasoning": True}),
]

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
    "gpt-5.4": 400000,
    "gpt-5.3": 400000,
    "gpt-5.2": 400000,
    "gpt-5.1": 400000,
    "gpt-5-mini": 400000,
    "gpt-5-nano": 400000,
    "gpt-5": 400000,
    "gpt-4.1": 1047576,
    "o1": 200000, "o3": 200000,
    "o4-mini": 200000,
    "gpt-4o": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5": 16385,
    "claude": 200000,
    "claude-sonnet-4": 200000,
    "claude-opus-4": 200000,
    "gemini-2.0-flash": 1048576,
    "gemini-2.5-pro": 1048576,
    "gemini-2.5-flash": 1048576,
    "gemini-1.5-pro": 2097152,
    "gemini-1.5-flash": 1048576,
    "gemini": 1048576,
    "grok-4.20": 2000000,
    "grok-4": 2000000,
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


def supports_native_web_search(model: str, provider: str = "") -> bool:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider != PROVIDER_OPENAI:
        return False
    name = str(model or "").strip().lower()
    if not name:
        return False
    if "gpt-4.1-nano" in name:
        return False
    if "deep-research" in name:
        return True
    return any(token in name for token in ("gpt-5", "gpt-4o", "gpt-4.1", "o3", "o4-"))


def get_model_capabilities(model: str, provider: str = "") -> dict[str, bool]:
    name = str(model or "").strip().lower()
    default = {
        "tool_calling": False,
        "vision": False,
        "structured_output": False,
        "reasoning": False,
        "native_web_search": False,
    }
    for needle, capabilities in _MODEL_CAPABILITY_RULES:
        if needle in name:
            return {
                **default,
                **capabilities,
                "native_web_search": supports_native_web_search(model, provider),
            }
    return {
        **default,
        "native_web_search": supports_native_web_search(model, provider),
    }


def is_agent_capable_model(model: str, provider: str = "") -> bool:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == PROVIDER_OLLAMA:
        return False
    capabilities = get_model_capabilities(model, provider)
    return bool(capabilities.get("tool_calling"))


# ── provider detection ────────────────────────────────────────────────────────

def _provider_has_explicit_model_selection(provider: str) -> bool:
    normalized_provider = str(provider or "").strip().lower()
    return bool(configured_models_for_provider(normalized_provider))


def _provider_is_configured(provider: str) -> bool:
    normalized_provider = str(provider or "").strip().lower()
    if not normalized_provider:
        return False
    if normalized_provider == PROVIDER_CUSTOM:
        return bool(os.getenv("CUSTOM_LLM_BASE_URL", "").strip())
    if normalized_provider == PROVIDER_OLLAMA:
        return _provider_has_explicit_model_selection(normalized_provider)
    return bool(get_api_key(normalized_provider))


def _provider_autoselect_score(provider: str, *, inferred_family: str = "") -> float:
    normalized_provider = str(provider or "").strip().lower()
    if not normalized_provider:
        return float("-inf")
    score = 0.0
    if normalized_provider == inferred_family:
        score += 120.0
    if _provider_has_explicit_model_selection(normalized_provider):
        score += 80.0
    if _provider_is_configured(normalized_provider):
        score += 40.0
    model = get_model_for_provider(normalized_provider)
    capabilities = get_model_capabilities(model, normalized_provider)
    if capabilities.get("tool_calling"):
        score += 12.0
    if capabilities.get("reasoning"):
        score += 10.0
    if capabilities.get("structured_output"):
        score += 8.0
    score += min(get_context_window(model), 400000) / 100000.0
    return score


def _auto_detect_active_provider() -> str:
    global_model = os.getenv("KENDR_MODEL", "").strip()
    inferred_family = infer_model_family(global_model)
    if inferred_family in ALL_PROVIDERS and (
        _provider_is_configured(inferred_family) or _provider_has_explicit_model_selection(inferred_family)
    ):
        return inferred_family

    explicit_model_providers = [provider for provider in ALL_PROVIDERS if _provider_has_explicit_model_selection(provider)]
    ready_explicit_model_providers = [provider for provider in explicit_model_providers if _provider_is_configured(provider)]
    if ready_explicit_model_providers:
        return max(
            ready_explicit_model_providers,
            key=lambda provider: (_provider_autoselect_score(provider, inferred_family=inferred_family), -ALL_PROVIDERS.index(provider)),
        )

    configured_providers = [provider for provider in ALL_PROVIDERS if _provider_is_configured(provider)]
    if configured_providers:
        return max(
            configured_providers,
            key=lambda provider: (_provider_autoselect_score(provider, inferred_family=inferred_family), -ALL_PROVIDERS.index(provider)),
        )

    if explicit_model_providers:
        return max(
            explicit_model_providers,
            key=lambda provider: (_provider_autoselect_score(provider, inferred_family=inferred_family), -ALL_PROVIDERS.index(provider)),
        )

    if inferred_family in ALL_PROVIDERS:
        return inferred_family
    return PROVIDER_OPENAI


def get_active_provider() -> str:
    """Return the active provider name (lower-cased)."""
    val = (
        os.getenv("KENDR_LLM_PROVIDER", "")
        or os.getenv("KENDR_PROVIDER", "")
    ).strip().lower()
    return val if val in ALL_PROVIDERS else _auto_detect_active_provider()


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
    if provider == PROVIDER_OPENAI:
        if role == "coding":
            return (
                os.getenv("OPENAI_MODEL_CODING", "")
                or os.getenv("OPENAI_CODEX_MODEL", "")
                or os.getenv("OPENAI_MODEL_GENERAL", "")
                or os.getenv("OPENAI_MODEL", _PROVIDER_DEFAULT_MODELS[PROVIDER_OPENAI])
                or os.getenv("KENDR_MODEL", "")
            ).strip()
        return (
            os.getenv("OPENAI_MODEL_GENERAL", "")
            or os.getenv("OPENAI_MODEL", _PROVIDER_DEFAULT_MODELS[PROVIDER_OPENAI])
            or os.getenv("KENDR_MODEL", "")
        ).strip()

    env = _PROVIDER_MODEL_ENV.get(provider, "")
    if env:
        val = os.getenv(env, "").strip()
        if val:
            return val

    global_override = os.getenv("KENDR_MODEL", "").strip()
    if global_override:
        return global_override

    return _PROVIDER_DEFAULT_MODELS.get(provider, "gpt-4o-mini")


def get_model_setting_env(provider: str) -> str:
    return _PROVIDER_DEFAULT_MODEL_SELECTION_ENV.get(provider, "")


def known_models_for_provider(provider: str) -> list[str]:
    return list(_PROVIDER_RELEASE_MODELS.get(provider, []))


def configured_models_for_provider(provider: str) -> list[str]:
    provider = str(provider or "").strip().lower()
    if provider == PROVIDER_OPENAI:
        return _merge_model_choices(
            [
                os.getenv("OPENAI_MODEL_GENERAL", "").strip(),
                os.getenv("OPENAI_MODEL_CODING", "").strip(),
                os.getenv("OPENAI_CODEX_MODEL", "").strip(),
                os.getenv("OPENAI_MODEL", "").strip(),
                os.getenv("OPENAI_VISION_MODEL", "").strip(),
            ]
        )

    env = _PROVIDER_MODEL_ENV.get(provider, "")
    if env:
        return _merge_model_choices([os.getenv(env, "").strip()])
    return []


def infer_model_family(model: str, provider: str = "") -> str:
    name = str(model or "").strip().lower()
    if not name:
        return str(provider or "").strip().lower()

    for prefix, family in _MODEL_FAMILY_RULES:
        if name.startswith(prefix):
            return family

    if "/" in name:
        family = name.split("/", 1)[0].strip()
        if family in ALL_PROVIDERS:
            return family

    return str(provider or "").strip().lower()


def _merge_model_choices(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            item = str(raw or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return merged


def _badge_provider_for_model(provider: str, model: str) -> str:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider in _PROVIDER_MODEL_BADGE_CANDIDATES:
        return normalized_provider
    inferred = infer_model_family(model, normalized_provider)
    if inferred in _PROVIDER_MODEL_BADGE_CANDIDATES:
        return inferred
    return normalized_provider


def _get_remote_model_inventory(provider: str) -> tuple[list[str], str]:
    provider = str(provider or "").strip().lower()
    if provider not in {
        PROVIDER_OPENAI,
        PROVIDER_XAI,
        PROVIDER_MINIMAX,
        PROVIDER_QWEN,
        PROVIDER_GLM,
        PROVIDER_OPENROUTER,
        PROVIDER_CUSTOM,
    }:
        return [], ""

    api_key = get_api_key(provider)
    if provider != PROVIDER_CUSTOM and not api_key:
        return [], ""

    try:
        if provider == PROVIDER_XAI:
            import requests

            base_url = get_base_url(provider).rstrip("/")
            response = requests.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("data") if isinstance(payload, dict) else payload
            ids = [str((item or {}).get("id", "")).strip() for item in (items or []) if isinstance(item, dict)]
            return [item for item in ids if item], ""

        from openai import OpenAI

        init: dict[str, Any] = {"timeout": 5.0}
        if api_key:
            init["api_key"] = api_key
        base_url = get_base_url(provider)
        if base_url:
            init["base_url"] = base_url

        client = OpenAI(**init)
        response = client.models.list()
        data = getattr(response, "data", None)
        items = data if isinstance(data, list) else list(response)
        ids = [str(getattr(item, "id", "") or "").strip() for item in items]
        return [item for item in ids if item], ""
    except Exception as exc:
        return [], str(exc).strip() or "Failed to fetch models"


def _sort_model_choices(provider: str, models: list[str]) -> list[str]:
    preferred = list(_PROVIDER_RELEASE_MODELS.get(provider, []))
    preferred_index = {name: idx for idx, name in enumerate(preferred)}
    seen = _merge_model_choices(models)
    return sorted(
        seen,
        key=lambda item: (
            0 if item in preferred_index else 1,
            preferred_index.get(item, 10_000),
            item.lower(),
        ),
    )


def _model_badges_for_provider(provider: str, models: list[str]) -> dict[str, list[str]]:
    available = {str(item or "").strip() for item in models if str(item or "").strip()}
    badges: dict[str, list[str]] = {}
    grouped_available: dict[str, set[str]] = {}
    for model in available:
        badge_provider = _badge_provider_for_model(provider, model)
        grouped_available.setdefault(badge_provider, set()).add(model)

    for badge_provider, family_models in grouped_available.items():
        for badge, candidates in _PROVIDER_MODEL_BADGE_CANDIDATES.get(badge_provider, {}).items():
            for candidate in candidates:
                if candidate in family_models:
                    badges.setdefault(candidate, []).append(badge)
                    break

    return badges


def selectable_models_for_provider(provider: str) -> list[str]:
    provider = str(provider or "").strip().lower()
    if provider == PROVIDER_OLLAMA:
        if not is_ollama_running():
            return []
        models = [str(item.get("name", "")).strip() for item in list_ollama_models()]
        return [name for name in models if name]
    if provider == PROVIDER_CUSTOM:
        status = provider_status(provider)
        selectable = status.get("selectable_models") if isinstance(status, dict) else []
        return [str(item).strip() for item in (selectable or []) if str(item).strip()]
    if not provider_status(provider).get("ready"):
        return []
    remote, _ = _get_remote_model_inventory(provider)
    configured = configured_models_for_provider(provider)
    return _sort_model_choices(provider, _merge_model_choices(remote, configured, known_models_for_provider(provider)))


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
        selectable = [m.get("name", "") for m in models if str(m.get("name", "")).strip()]
        return {
            "provider": provider,
            "ready": running,
            "has_key": True,
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            "model": model,
            "model_family": PROVIDER_OLLAMA,
            "configured_models": configured_models_for_provider(provider),
            "local_models": [m.get("name", "") for m in models],
            "selectable_models": selectable,
            "selectable_model_details": [
                {
                    "name": name,
                    "family": infer_model_family(name, provider),
                    "context_window": get_context_window(name),
                    "capabilities": get_model_capabilities(name, provider),
                    "agent_capable": False,
                }
                for name in selectable
            ],
            "agent_capable": False,
            "note": "Running" if running else "Not running — start with: ollama serve",
        }

    if provider == PROVIDER_CUSTOM:
        url = os.getenv("CUSTOM_LLM_BASE_URL", "").strip()
        configured = configured_models_for_provider(provider)
        remote_models, remote_error = _get_remote_model_inventory(provider) if url else ([], "")
        selectable = _sort_model_choices(
            infer_model_family(model, provider),
            _merge_model_choices(remote_models, configured),
        ) if url else configured
        return {
            "provider": provider,
            "ready": bool(url),
            "has_key": True,
            "base_url": url,
            "model": model,
            "model_family": infer_model_family(model, provider),
            "configured_models": configured,
            "selectable_models": selectable,
            "selectable_model_details": [
                {
                    "name": item,
                    "family": infer_model_family(item, provider),
                    "context_window": get_context_window(item),
                    "capabilities": get_model_capabilities(item, provider),
                    "agent_capable": is_agent_capable_model(item, infer_model_family(item, provider)),
                }
                for item in selectable
            ],
            "model_badges": _model_badges_for_provider(provider, selectable) if url else {},
            "model_fetch_error": remote_error,
            "note": "Configured" if url else "Set CUSTOM_LLM_BASE_URL",
        }

    remote_models, remote_error = _get_remote_model_inventory(provider) if has_key else ([], "")
    configured = configured_models_for_provider(provider)
    selectable = _sort_model_choices(
        provider,
        _merge_model_choices(remote_models, configured, known_models_for_provider(provider)),
    ) if has_key else []

    return {
        "provider": provider,
        "ready": has_key,
        "has_key": has_key,
        "base_url": base_url,
        "model": model,
        "model_family": infer_model_family(model, provider),
        "configured_models": configured,
        "model_capabilities": get_model_capabilities(model, provider),
        "agent_capable": is_agent_capable_model(model, provider),
        "selectable_models": selectable,
        "selectable_model_details": [
            {
                "name": item,
                "family": infer_model_family(item, provider),
                "context_window": get_context_window(item),
                "capabilities": get_model_capabilities(item, provider),
                "agent_capable": is_agent_capable_model(item, infer_model_family(item, provider)),
            }
            for item in selectable
        ],
        "api_key_env": api_key_env,
        "model_badges": _model_badges_for_provider(provider, selectable) if has_key else {},
        "model_fetch_error": remote_error,
        "note": (
            f"Error fetching models: {remote_error}"
            if remote_error
            else ("API key configured" if has_key else f"Set {api_key_env}")
        ),
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

    Falls back to the active provider when none is supplied.
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
