import os
import re
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.coding_tasks import (
    DEFAULT_CODEX_MODEL,
    DEFAULT_REASONING_EFFORT,
    _call_codex_cli,
    _call_openai_sdk,
    _call_responses_http,
    _parse_coding_response,
    _read_context_files,
    _resolve_backend,
)
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


REDDIT_DOC_URL = "https://developers.reddit.com/docs/capabilities/server/reddit-api"
REDDIT_DOC_SUMMARY = """
Use the Reddit API through Devvit rather than raw Reddit OAuth.

Rules from the Reddit API Overview:
- Devvit handles authentication automatically when the app enables Reddit access.
- Devvit Web should enable `permissions.reddit: true` in `devvit.json`.
- Devvit Blocks / Mod Tools should call `Devvit.configure({ redditAPI: true })`.
- Devvit Web examples import from `@devvit/web/server` and can use `context` and `reddit`.
- Devvit Blocks / Mod Tools use `context.reddit`.
- Reddit thing prefixes:
  - `t1_` comment
  - `t2_` user
  - `t3_` post
  - `t4_` message
  - `t5_` subreddit
- Example methods shown in the docs:
  - `reddit.submitCustomPost(...)`
  - `context.reddit.submitPost(...)`
  - `reddit.submitComment(...)`
  - `context.reddit.getPostById(...)`
  - `context.reddit.getCommentById(...)`
- Devvit apps cannot access certain private user data such as saved posts, votes, browsing history, private profile fields, follows/friends, or subscribed subreddit lists.
""".strip()


def _build_reddit_prompt(
    task: str,
    framework: str,
    extra_instructions: str,
    target_write_path: str | None,
    context_blob: str,
    missing_files: list[str],
) -> str:
    write_instruction = (
        f"Return the full replacement file contents for this path: {target_write_path}."
        if target_write_path
        else "Return the code artifact directly. Do not assume any file write unless told."
    )
    missing_context = "\n".join(missing_files) if missing_files else "None"

    return f"""
You are the Reddit agent inside a multi-agent ecosystem.

Your job is to generate production-ready Devvit Reddit app code using the official Reddit for Developers Reddit API Overview.
Target framework: {framework}.
Prefer TypeScript unless the user explicitly requests another language.
Use only the Devvit/Reddit patterns supported by the documentation summary below.
Keep non-code text minimal.
{write_instruction}
Do not wrap the code in markdown fences.

Official source:
{REDDIT_DOC_URL}

Documentation summary:
{REDDIT_DOC_SUMMARY}

Return EXACTLY in this format:
SUMMARY: one-line summary
LANGUAGE: TypeScript or other requested language
CODE:
full code here

Task:
{task}

Additional instructions:
{extra_instructions or "None"}

Missing context files:
{missing_context}

Relevant context:
{context_blob or "No file context provided."}
""".strip()


def _task_requires_content_fetch(task: str) -> bool:
    lower = task.lower()
    fetch_markers = [
        "fetch",
        "read",
        "retrieve",
        "get post",
        "get comment",
        "by id",
        "post id",
        "comment id",
    ]
    return any(marker in lower for marker in fetch_markers)


def _missing_content_fields(code: str) -> list[str]:
    checks = {
        "title": [r"\btitle\b"],
        "body/selftext/text": [r"\bselftext\b", r"\bbody\b", r"\btext\b"],
        "author": [r"\bauthor\b", r"\busername\b"],
        "subreddit": [r"\bsubreddit\b", r"\bsubredditname\b"],
        "score": [r"\bscore\b", r"\bupvotes?\b", r"\bvote"],
        "created time": [r"\bcreated\b", r"\bcreatedat\b", r"\bcreatedutc\b", r"\btimestamp\b"],
    }
    lower = code.lower()
    missing = []
    for field_name, patterns in checks.items():
        if not any(re.search(pattern, lower) for pattern in patterns):
            missing.append(field_name)
    return missing


def _call_reddit_backend(prompt: str, preferred_backend: str, api_key: str | None, model: str, reasoning_effort: str, working_directory: Path, timeout_seconds: int) -> tuple[str, str]:
    backend_errors = []
    raw_output = ""
    backend_used = None

    for backend in _resolve_backend(preferred_backend, api_key):
        try:
            if backend == "codex-cli":
                raw_output = _call_codex_cli(prompt, model, working_directory, timeout_seconds)
            elif backend == "openai-sdk":
                raw_output = _call_openai_sdk(prompt, model, reasoning_effort, api_key or "")
            elif backend == "responses-http":
                raw_output = _call_responses_http(prompt, model, reasoning_effort, api_key or "", timeout_seconds)
            else:
                raise ValueError(f"Unsupported reddit backend: {backend}")
            backend_used = backend
            break
        except Exception as exc:
            backend_errors.append(f"{backend}: {exc}")

    if not backend_used:
        raise RuntimeError("reddit_agent could not generate code.\n" + "\n".join(backend_errors))

    return raw_output, backend_used


def reddit_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "reddit_agent")
    state["reddit_agent_calls"] = state.get("reddit_agent_calls", 0) + 1
    call_number = state["reddit_agent_calls"]

    task = state.get("reddit_task") or task_content or state.get("current_objective") or state.get("user_query", "").strip()
    if not task:
        raise ValueError("reddit_agent requires 'reddit_task' or 'user_query' in state.")

    working_directory = Path(state.get("reddit_working_directory", ".")).resolve()
    target_write_path = state.get("reddit_write_path")
    context_files = state.get("reddit_context_files", [])
    framework = state.get("reddit_framework", "devvit-web")
    extra_instructions = state.get("reddit_instructions", "")
    preferred_backend = state.get("reddit_backend", "auto")
    model = state.get("reddit_model", DEFAULT_CODEX_MODEL)
    reasoning_effort = state.get("reddit_reasoning_effort", DEFAULT_REASONING_EFFORT)
    timeout_seconds = int(state.get("reddit_timeout", 90))
    api_key = os.getenv("OPENAI_API_KEY")

    log_task_update("Reddit Agent", f"Generation pass #{call_number} started.")
    log_task_update(
        "Reddit Agent",
        f"Generating Reddit app code for framework '{framework}' using backend preference '{preferred_backend}'.",
        task,
    )

    context_blob, missing_files = _read_context_files(context_files, working_directory)
    prompt = _build_reddit_prompt(
        task=task,
        framework=framework,
        extra_instructions=extra_instructions,
        target_write_path=target_write_path,
        context_blob=context_blob,
        missing_files=missing_files,
    )

    raw_output, backend_used = _call_reddit_backend(
        prompt=prompt,
        preferred_backend=preferred_backend,
        api_key=api_key,
        model=model,
        reasoning_effort=reasoning_effort,
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
    )
    summary, language, code = _parse_coding_response(raw_output)
    validation_retry = False
    missing_content_fields = []

    if _task_requires_content_fetch(task):
        missing_content_fields = _missing_content_fields(code)
        if missing_content_fields:
            validation_retry = True
            validation_instruction = (
                "CRITICAL: This is a Reddit content retrieval task. "
                "Return code that retrieves and returns full content fields, not only IDs. "
                "The response object must include: title, body/selftext/text, author, subreddit, score, and created timestamp."
            )
            retry_extra = "\n".join(part for part in [extra_instructions.strip(), validation_instruction] if part)
            retry_prompt = _build_reddit_prompt(
                task=task,
                framework=framework,
                extra_instructions=retry_extra,
                target_write_path=target_write_path,
                context_blob=context_blob,
                missing_files=missing_files,
            )
            raw_output, backend_used = _call_reddit_backend(
                prompt=retry_prompt,
                preferred_backend=preferred_backend,
                api_key=api_key,
                model=model,
                reasoning_effort=reasoning_effort,
                working_directory=working_directory,
                timeout_seconds=timeout_seconds,
            )
            summary, language, code = _parse_coding_response(raw_output)
            missing_content_fields = _missing_content_fields(code)

    raw_filename = f"reddit_agent_raw_{call_number}.txt"
    code_filename = f"reddit_agent_code_{call_number}.txt"
    report_filename = f"reddit_agent_output_{call_number}.txt"

    write_text_file(raw_filename, raw_output)
    write_text_file(code_filename, code)

    written_path = None
    if target_write_path:
        written_path = Path(target_write_path)
        if not written_path.is_absolute():
            written_path = working_directory / written_path
        written_path.parent.mkdir(parents=True, exist_ok=True)
        written_path.write_text(code, encoding="utf-8")
        state["reddit_written_path"] = str(written_path)

    report_lines = [
        f"Backend: {backend_used}",
        f"Model: {model}",
        f"Reasoning effort: {reasoning_effort}",
        f"Framework: {framework}",
        f"Summary: {summary}",
        f"Language: {language}",
        f"Target write path: {written_path or 'none'}",
        f"Context files: {', '.join(context_files) if context_files else 'none'}",
        f"Missing context files: {', '.join(missing_files) if missing_files else 'none'}",
        f"Documentation source: {REDDIT_DOC_URL}",
        f"Validation retry used: {validation_retry}",
        f"Missing content fields after validation: {', '.join(missing_content_fields) if missing_content_fields else 'none'}",
        "",
        "Generated Code:",
        code,
    ]
    report = "\n".join(report_lines).strip()
    write_text_file(report_filename, report)

    state["reddit_summary"] = summary
    state["reddit_language"] = language
    state["reddit_code"] = code
    state["reddit_model"] = model
    state["reddit_backend_used"] = backend_used
    state["reddit_raw_output"] = raw_output
    state["reddit_validation_retry"] = validation_retry
    state["reddit_missing_content_fields"] = missing_content_fields
    state["draft_response"] = report

    log_task_update(
        "Reddit Agent",
        f"Reddit code generation finished with backend '{backend_used}'. Saved artifacts to {OUTPUT_DIR}/{report_filename}.",
        report,
    )
    state = publish_agent_output(
        state,
        "reddit_agent",
        report,
        f"reddit_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent"],
    )
    return state
