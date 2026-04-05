import os
import logging
import sys
import tempfile
import time as _time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from tasks.setup_config_store import apply_setup_env_defaults

load_dotenv()
apply_setup_env_defaults()

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)
RUN_OUTPUT_ROOT = os.path.join(OUTPUT_DIR, "runs")
os.makedirs(RUN_OUTPUT_ROOT, exist_ok=True)
ACTIVE_OUTPUT_DIR = OUTPUT_DIR

_ACTIVE_AGENT_NAME: ContextVar[str] = ContextVar("active_agent_name", default="")
_ACTIVE_PROVIDER_OVERRIDE: ContextVar[str] = ContextVar("active_provider_override", default="")
_ACTIVE_MODEL_OVERRIDE: ContextVar[str] = ContextVar("active_model_override", default="")
_LLM_CLIENTS: dict[str, object] = {}
_DEFAULT_GENERAL_MODEL = os.getenv("OPENAI_MODEL_GENERAL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
_DEFAULT_CODING_MODEL = os.getenv("OPENAI_MODEL_CODING", os.getenv("OPENAI_CODEX_MODEL", _DEFAULT_GENERAL_MODEL))
_CODING_AGENTS = {
    "coding_agent",
    "master_coding_agent",
    "agent_factory_agent",
    "dynamic_agent_runner",
    "reddit_agent",
    # Project builder agents
    "project_blueprint_agent",
    "project_scaffold_agent",
    "database_architect_agent",
    "backend_builder_agent",
    "frontend_builder_agent",
    "devops_agent",
    # Testing agents
    "api_test_agent",
    "unit_test_agent",
    "test_runner_agent",
    "test_fix_agent",
    "regression_test_agent",
}


def _agent_role(agent_name: str) -> str:
    return "coding" if agent_name in _CODING_AGENTS else "general"


@contextmanager
def runtime_model_override(provider: str = "", model: str = ""):
    provider_token = _ACTIVE_PROVIDER_OVERRIDE.set(str(provider or "").strip().lower())
    model_token = _ACTIVE_MODEL_OVERRIDE.set(str(model or "").strip())
    try:
        yield
    finally:
        _ACTIVE_PROVIDER_OVERRIDE.reset(provider_token)
        _ACTIVE_MODEL_OVERRIDE.reset(model_token)


def model_selection_for_agent(agent_name: str = "") -> dict[str, str]:
    from kendr.llm_router import get_active_provider, get_model_for_provider

    name = (agent_name or "").strip()
    provider = (_ACTIVE_PROVIDER_OVERRIDE.get("") or get_active_provider()).strip().lower()
    forced_model = _ACTIVE_MODEL_OVERRIDE.get("").strip()

    if forced_model:
        return {"model": forced_model, "source": "runtime_override", "provider": provider}

    # Agent-specific override still respected
    if name:
        agent_key = f"OPENAI_MODEL_AGENT_{name.upper()}"
        agent_specific = os.getenv(agent_key, "").strip()
        if agent_specific:
            return {"model": agent_specific, "source": agent_key, "provider": provider}

    role = _agent_role(name)
    model = get_model_for_provider(provider, role)
    return {"model": model, "source": f"KENDR_LLM_PROVIDER={provider}", "provider": provider}


def model_for_agent(agent_name: str = "") -> str:
    return model_selection_for_agent(agent_name).get("model", _DEFAULT_GENERAL_MODEL)


def _client_for_model(model: str, role: str = "general") -> object:
    from kendr.llm_router import build_llm, get_active_provider

    provider = (_ACTIVE_PROVIDER_OVERRIDE.get("") or get_active_provider()).strip().lower()
    cache_key = f"{provider}:{role}:{model}"
    client = _LLM_CLIENTS.get(cache_key)
    if client is None:
        try:
            client = build_llm(provider=provider, model=model, role=role)
        except Exception:
            client = ChatOpenAI(model=model)
        _LLM_CLIENTS[cache_key] = client
    return client


@contextmanager
def agent_model_context(agent_name: str):
    token = _ACTIVE_AGENT_NAME.set(agent_name or "")
    try:
        yield
    finally:
        _ACTIVE_AGENT_NAME.reset(token)


def _mask_api_key(key: str) -> str:
    if not key:
        return "<not set>"
    if len(key) <= 8:
        return "*" * len(key)
    return key[:6] + "..." + key[-4:]


def _prompt_summary(prompt) -> tuple[str, int]:
    """Return (preview_str, total_char_count) for any LangChain prompt shape."""
    if isinstance(prompt, str):
        return prompt, len(prompt)
    if isinstance(prompt, list):
        lines: list[str] = []
        for msg in prompt:
            if hasattr(msg, "type") and hasattr(msg, "content"):
                lines.append(f"[{msg.type}] {str(msg.content)}")
            elif isinstance(msg, (list, tuple)) and len(msg) == 2:
                lines.append(f"[{msg[0]}] {msg[1]}")
            else:
                lines.append(str(msg))
        combined = "\n".join(lines)
        return combined, len(combined)
    text = str(prompt)
    return text, len(text)


def _usage_str(response) -> str:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        meta = getattr(response, "response_metadata", {}) or {}
        usage = meta.get("token_usage") or meta.get("usage")
    if usage is None:
        return ""
    if isinstance(usage, dict):
        in_t = usage.get("input_tokens") or usage.get("prompt_tokens", "?")
        out_t = usage.get("output_tokens") or usage.get("completion_tokens", "?")
        total = usage.get("total_tokens", "")
        total_str = f"/total:{total}" if total else ""
        return f" | tokens in:{in_t} out:{out_t}{total_str}"
    in_t = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None)
    out_t = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None)
    if in_t is not None or out_t is not None:
        return f" | tokens in:{in_t} out:{out_t}"
    return ""


class RoutedLLM:
    def invoke(self, prompt, *args, **kwargs):
        from kendr.llm_router import get_active_provider, get_api_key, get_base_url

        forced_agent = kwargs.pop("agent_name", "")
        agent_name = forced_agent or _ACTIVE_AGENT_NAME.get("")
        role = _agent_role(agent_name)
        model = model_for_agent(agent_name)

        provider = (_ACTIVE_PROVIDER_OVERRIDE.get("") or get_active_provider()).strip().lower()
        base_url = get_base_url(provider) or {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
            "google": "https://generativelanguage.googleapis.com/v1beta",
        }.get(provider, f"<{provider} default>")
        raw_key = get_api_key(provider)

        prompt_text, prompt_chars = _prompt_summary(prompt)

        logger.info(
            "[LLM Call] agent=%s | role=%s | provider=%s | model=%s | endpoint=%s | key=%s | prompt_chars=%d",
            agent_name or "<none>", role, provider, model, base_url,
            _mask_api_key(raw_key), prompt_chars,
        )
        logger.info("[LLM Prompt]\n%s", prompt_text)

        t0 = _time.monotonic()
        try:
            response = _client_for_model(model, role).invoke(prompt, *args, **kwargs)
            elapsed_ms = int((_time.monotonic() - t0) * 1000)
            logger.info(
                "[LLM OK] agent=%s | model=%s | elapsed_ms=%d%s",
                agent_name or "<none>", model, elapsed_ms, _usage_str(response),
            )
            return response
        except Exception as exc:
            elapsed_ms = int((_time.monotonic() - t0) * 1000)
            logger.error(
                "[LLM Error] agent=%s | provider=%s | model=%s | endpoint=%s | elapsed_ms=%d | %s: %s",
                agent_name or "<none>", provider, model, base_url,
                elapsed_ms, type(exc).__name__, exc,
            )
            raise


llm = RoutedLLM()

logger = logging.getLogger("multi_agent_workflow")
logger.setLevel(logging.INFO)
logger.handlers.clear()

file_handler = logging.FileHandler(
    os.path.join(ACTIVE_OUTPUT_DIR, "execution.log"),
    mode="w",
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("%(message)s"))

logger.addHandler(file_handler)
logger.addHandler(console_handler)
logger.propagate = False


def get_output_dir() -> str:
    return ACTIVE_OUTPUT_DIR


def normalize_llm_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text_value = item.get("text")
                if text_value is None:
                    text_value = item.get("content")
                parts.append(str(text_value) if text_value is not None else str(item))
                continue
            parts.append(str(item))
        return "\n".join(part for part in parts if part is not None)
    return str(value)


def resolve_output_path(filename: str | os.PathLike[str]) -> str:
    path = Path(filename)
    if path.is_absolute():
        return str(path)
    return str(Path(get_output_dir()) / path)


def set_active_output_dir(path: str, *, append: bool = False) -> str:
    global ACTIVE_OUTPUT_DIR, file_handler

    ACTIVE_OUTPUT_DIR = path
    os.makedirs(ACTIVE_OUTPUT_DIR, exist_ok=True)

    try:
        logger.removeHandler(file_handler)
        file_handler.close()
    except Exception:
        pass

    file_handler = logging.FileHandler(
        os.path.join(ACTIVE_OUTPUT_DIR, "execution.log"),
        mode="a" if append else "w",
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(file_handler)
    return ACTIVE_OUTPUT_DIR


def create_run_output_dir(run_id: str, base_dir: str | None = None) -> str:
    root = base_dir.strip() if isinstance(base_dir, str) and base_dir.strip() else RUN_OUTPUT_ROOT
    if base_dir:
        root = os.path.join(root, "runs")
    os.makedirs(root, exist_ok=True)
    prefix = f"{run_id}_"
    run_dir = tempfile.mkdtemp(prefix=prefix, dir=root)
    return set_active_output_dir(run_dir)


def log_task_update(task_name: str, message: str, content: str | None = None):
    logger.info(f"[{task_name}] {message}")
    if content:
        logger.info(content.strip())


def log_file_action(action: str, path: str) -> None:
    logger.info(f"[files] {action}: {path}")


def normalize_llm_response(response) -> str:
    """Safely extract a plain string from any LangChain LLM response.

    Some providers (Claude, Gemini, etc.) return ``response.content`` as a
    list of typed content blocks rather than a plain string.  This wrapper
    extracts the content field and delegates to :func:`normalize_llm_text`
    which already handles all known shapes (str, list[str], list[dict], …).
    """
    content = response.content if hasattr(response, "content") else response
    return normalize_llm_text(content)


def _to_str(content) -> str:
    """Ensure content is a str; delegates to normalize_llm_text."""
    return normalize_llm_text(content)


def write_text_file(filename: str, content):
    filepath = resolve_output_path(filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(_to_str(content))
    log_file_action("wrote", filepath)


def write_binary_file(filename: str, content: bytes):
    filepath = resolve_output_path(filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(content)
    log_file_action("wrote", filepath)


def append_text_file(filename: str, content):
    filepath = resolve_output_path(filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(_to_str(content))


def reset_text_file(filename: str, content=""):
    filepath = resolve_output_path(filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(_to_str(content))


def record_work_note(state: dict | None, actor: str, stage: str, details):
    filename = "agent_work_notes.txt"
    if state and state.get("work_notes_file"):
        filename = state["work_notes_file"]

    timestamp = datetime.now(timezone.utc).isoformat()
    run_id = state.get("run_id", "no-run-id") if state else "no-run-id"
    note = (
        f"[{timestamp}] run={run_id} actor={actor} stage={stage}\n"
        f"{_to_str(details).strip()}\n\n"
    )
    append_text_file(filename, note)
