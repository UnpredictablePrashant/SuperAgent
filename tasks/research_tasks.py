import json
import os
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.coding_tasks import _extract_output_text
from tasks.research_infra import fetch_url_content, llm_text, parse_documents
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


DEFAULT_DEEP_RESEARCH_MODEL = os.getenv("OPENAI_DEEP_RESEARCH_MODEL", "o4-mini-deep-research")

AGENT_METADATA = {
    "deep_research_agent": {
        "description": "Runs OpenAI Deep Research for web-grounded, source-aware, in-depth research tasks.",
        "skills": ["deep", "research", "web", "citations", "analysis"],
        "input_keys": [
            "research_query",
            "research_model",
            "research_instructions",
            "research_max_tool_calls",
            "research_max_output_tokens",
            "research_web_search_enabled",
            "deep_research_source_urls",
            "local_drive_paths",
        ],
        "output_keys": [
            "research_result",
            "research_status",
            "research_response_id",
            "research_raw",
        ],
        "requirements": ["openai"],
        "display_name": "Deep Research Agent",
        "category": "research",
        "intent_patterns": [
            "research this topic", "do deep research", "investigate in depth",
            "find citations", "source-backed analysis", "web research with sources",
        ],
        "active_when": ["env:OPENAI_API_KEY"],
        "config_hint": "Add your OpenAI API key in Setup → Providers.",
    }
}


def _serialize_response(response) -> dict:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if isinstance(response, dict):
        return response
    return {"response": str(response)}


def _normalize_url_list(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        raw_items = raw_value.split(",")
    elif isinstance(raw_value, list):
        raw_items = raw_value
    else:
        raw_items = []
    urls: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        value = str(item or "").strip()
        if not value or not value.lower().startswith(("http://", "https://")):
            continue
        if value in seen:
            continue
        seen.add(value)
        urls.append(value)
    return urls


def _build_local_source_context(state: dict, query: str, *, include_urls: bool) -> tuple[str, dict]:
    blocks: list[str] = []
    meta = {"local_file_count": 0, "provided_url_count": 0}

    local_drive_paths = [str(item).strip() for item in list(state.get("local_drive_paths") or []) if str(item).strip()]
    local_docs = state.get("local_drive_documents") if isinstance(state.get("local_drive_documents"), list) else []
    if not local_docs and local_drive_paths:
        local_docs = parse_documents(
            local_drive_paths,
            continue_on_error=True,
            ocr_images=bool(state.get("local_drive_enable_image_ocr", True)),
            ocr_instruction=state.get("local_drive_ocr_instruction"),
        )
    for index, doc in enumerate(local_docs[:12], start=1):
        path_value = str(doc.get("path", "")).strip()
        text_value = str(doc.get("text", "")).strip()[:2500]
        meta["local_file_count"] += 1
        blocks.append(
            "\n".join(
                [
                    f"[Local File {index}] {Path(path_value).name or path_value or 'document'}",
                    f"Path: {path_value or 'n/a'}",
                    text_value or "No readable text extracted.",
                ]
            )
        )

    if include_urls:
        for index, url in enumerate(_normalize_url_list(state.get("deep_research_source_urls", []))[:10], start=1):
            try:
                page = fetch_url_content(url, timeout=20)
                page_text = str(page.get("text", "")).strip()[:2500]
            except Exception as exc:
                page_text = f"URL extraction failed: {exc}"
            meta["provided_url_count"] += 1
            blocks.append(
                "\n".join(
                    [
                        f"[Provided URL {index}] {url}",
                        page_text or "No readable text extracted.",
                    ]
                )
            )

    if not blocks:
        return "", meta

    prompt = f"""
You are preparing source context for a deep research run.

Research objective:
{query}

Available local source material:
{chr(10).join(blocks)[:22000]}

Produce a concise source memo with:
- strongest facts and evidence
- important numbers, dates, entities
- contradictions or gaps
- which sources appear most relevant
"""
    return llm_text(prompt).strip(), meta


def deep_research_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "deep_research_agent")
    state["deep_research_calls"] = state.get("deep_research_calls", 0) + 1
    call_number = state["deep_research_calls"]

    query = state.get("research_query") or task_content or state.get("current_objective") or state.get("user_query", "").strip()
    if not query:
        raise ValueError("deep_research_agent requires 'research_query' or 'user_query' in state.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for deep_research_agent.")

    model = state.get("research_model", DEFAULT_DEEP_RESEARCH_MODEL)
    max_tool_calls = int(state.get("research_max_tool_calls", 8))
    max_output_tokens = state.get("research_max_output_tokens")
    instructions = state.get(
        "research_instructions",
        "Conduct a careful web-based deep research pass. Synthesize the results clearly, cite concrete sources when available, and call out uncertainty.",
    )
    web_search_enabled = bool(state.get("research_web_search_enabled", True))
    background = state.get("research_background", True)
    poll_interval_seconds = int(state.get("research_poll_interval_seconds", 5))
    max_wait_seconds = int(state.get("research_max_wait_seconds", 600))

    local_context, local_meta = _build_local_source_context(state, query, include_urls=web_search_enabled)
    if local_context:
        instructions = (
            f"{instructions}\n\n"
            "Prioritize the supplied local source context and explicitly reconcile it with any additional findings.\n\n"
            f"Local source context:\n{local_context}"
        )

    if not web_search_enabled:
        local_only_prompt = f"""
You are conducting a deep research pass without internet or web search.

Research query:
{query}

Available source context:
{local_context or "No local file context was provided."}

Write a source-aware research memo that:
- uses only the provided local file context
- does not invent external citations
- calls out gaps or uncertainty clearly
- ends with a concise recommended next-steps section
"""
        output_text = llm_text(local_only_prompt).strip()
        payload = {
            "mode": "local_only",
            "query": query,
            "local_context": local_context,
            "local_source_count": local_meta.get("local_file_count", 0),
            "provided_url_count": 0,
            "output_text": output_text,
        }
        raw_filename = f"deep_research_raw_{call_number}.json"
        output_filename = f"deep_research_output_{call_number}.txt"
        write_text_file(raw_filename, json.dumps(payload, indent=2, ensure_ascii=False))
        write_text_file(output_filename, output_text)
        state["research_response_id"] = f"local_only_{call_number}"
        state["research_status"] = "completed"
        state["research_result"] = output_text
        state["research_model"] = "local-only-synthesis"
        state["research_raw"] = payload
        state["draft_response"] = output_text
        log_task_update(
            "Deep Research",
            f"Completed local-only deep research run #{call_number} using {local_meta.get('local_file_count', 0)} local file(s).",
            output_text,
        )
        state = publish_agent_output(
            state,
            "deep_research_agent",
            output_text,
            f"deep_research_result_{call_number}",
            recipients=["orchestrator_agent", "worker_agent"],
        )
        return state

    client = OpenAI(api_key=api_key)

    log_task_update(
        "Deep Research",
        f"Research pass #{call_number} started with model '{model}'.",
        query,
    )

    create_kwargs = {
        "model": model,
        "input": query,
        "instructions": instructions,
        "background": background,
        "max_tool_calls": max_tool_calls,
        "reasoning": {"summary": "auto"},
        "tools": [{"type": "web_search_preview"}],
    }
    if max_output_tokens is not None:
        create_kwargs["max_output_tokens"] = int(max_output_tokens)

    response = client.responses.create(**create_kwargs)
    response_id = response.id
    status = getattr(response, "status", "unknown")

    log_task_update(
        "Deep Research",
        f"Research job created with response id '{response_id}' and initial status '{status}'.",
    )

    elapsed_seconds = 0
    while background and status not in {"completed", "failed", "cancelled", "incomplete"}:
        if elapsed_seconds >= max_wait_seconds:
            raise TimeoutError(
                f"Deep research job '{response_id}' did not finish within {max_wait_seconds} seconds."
            )

        time.sleep(poll_interval_seconds)
        elapsed_seconds += poll_interval_seconds
        response = client.responses.retrieve(response_id)
        new_status = getattr(response, "status", "unknown")

        if new_status != status:
            status = new_status
            log_task_update(
                "Deep Research",
                f"Research job '{response_id}' status changed to '{status}' after {elapsed_seconds} seconds.",
            )
        else:
            log_task_update(
                "Deep Research",
                f"Research job '{response_id}' still '{status}' after {elapsed_seconds} seconds.",
            )

    payload = _serialize_response(response)
    output_text = getattr(response, "output_text", None) or _extract_output_text(payload)

    raw_filename = f"deep_research_raw_{call_number}.json"
    output_filename = f"deep_research_output_{call_number}.txt"

    write_text_file(raw_filename, json.dumps(payload, indent=2, ensure_ascii=False))
    write_text_file(output_filename, output_text)

    state["research_response_id"] = response_id
    state["research_status"] = getattr(response, "status", status)
    state["research_result"] = output_text
    state["research_model"] = model
    state["research_raw"] = payload
    state["draft_response"] = output_text

    log_task_update(
        "Deep Research",
        f"Deep research finished with status '{state['research_status']}'. Saved artifacts to {OUTPUT_DIR}/{output_filename}.",
        output_text,
    )
    state = publish_agent_output(
        state,
        "deep_research_agent",
        output_text,
        f"deep_research_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent"],
    )
    return state
