import json
import os
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from kendr.llm_router import PROVIDER_OPENAI, supports_native_web_search
from kendr.rag_manager import build_research_grounding
from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.coding_tasks import _extract_output_text
from tasks.research_infra import duckduckgo_html_search, fetch_url_content, fetch_urls_content, llm_text, parse_documents
from tasks.research_output import render_phase0_report, split_sources_section
from tasks.utils import OUTPUT_DIR, log_task_update, model_selection_for_agent, runtime_model_override, write_text_file


DEFAULT_DEEP_RESEARCH_MODEL = os.getenv("OPENAI_DEEP_RESEARCH_MODEL", "o4-mini-deep-research")

AGENT_METADATA = {
    "deep_research_agent": {
        "description": "Legacy deep research shim that redirects public deep-research workflows to long_document_agent.",
        "skills": ["deep", "research", "web", "citations", "analysis"],
        "input_keys": [
            "research_query",
            "research_model",
            "research_provider",
            "research_instructions",
            "research_max_tool_calls",
            "research_max_output_tokens",
            "research_web_search_enabled",
            "deep_research_source_urls",
            "local_drive_paths",
            "research_kb_enabled",
            "research_kb_id",
            "research_kb_top_k",
        ],
        "output_keys": [
            "research_result",
            "research_status",
            "research_response_id",
            "research_raw",
            "research_provider",
            "research_kb_used",
            "research_kb_name",
            "research_kb_hit_count",
            "research_kb_citations",
            "research_kb_warning",
            "research_source_summary",
            "deep_research_result_card",
        ],
        "requirements": [],
        "discoverable": False,
        "display_name": "Deep Research Agent",
        "category": "research",
        "intent_patterns": [
            "research this topic", "do deep research", "investigate in depth",
            "find citations", "source-backed analysis", "web research with sources",
        ],
        "active_when": [],
        "config_hint": "Choose any configured model in Studio. OpenAI is only required when the selected model uses native web search.",
    }
}

_RESEARCH_PROVIDER_NAMES = {
    "openai",
    "anthropic",
    "google",
    "xai",
    "ollama",
    "openrouter",
    "custom",
    "minimax",
    "qwen",
    "glm",
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


def _resolve_research_backend(state: dict, *, web_search_enabled: bool) -> dict[str, Any]:
    selection = model_selection_for_agent("deep_research_agent")
    provider = str(selection.get("provider") or PROVIDER_OPENAI).strip().lower() or PROVIDER_OPENAI
    model = str(selection.get("model") or DEFAULT_DEEP_RESEARCH_MODEL).strip() or DEFAULT_DEEP_RESEARCH_MODEL
    source = str(selection.get("source") or "").strip() or "agent_selection"

    explicit_provider = str(state.get("research_provider") or "").strip().lower()
    if explicit_provider:
        provider = explicit_provider
        source = "state.research_provider"

    raw_research_model = str(state.get("research_model") or "").strip()
    if raw_research_model:
        lowered = raw_research_model.lower()
        if lowered in _RESEARCH_PROVIDER_NAMES and not explicit_provider:
            log_task_update(
                "Deep Research",
                (
                    f"state.research_model='{raw_research_model}' looks like a provider token, not a model id. "
                    "Ignoring it and using the UI-selected model instead."
                ),
            )
        else:
            model = raw_research_model
            source = "state.research_model"

    native_web_search_enabled = bool(web_search_enabled and supports_native_web_search(model, provider))
    return {
        "provider": provider,
        "model": model,
        "source": source,
        "native_web_search_enabled": native_web_search_enabled,
    }


def _collect_generic_web_evidence(
    query: str,
    *,
    provided_urls: list[str],
    max_results: int = 6,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    search_results: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        search_payload = duckduckgo_html_search(query, num=max_results)
        raw_results = search_payload.get("results", []) if isinstance(search_payload, dict) else []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            search_results.append(
                {
                    "title": str(item.get("title", "")).strip() or url,
                    "url": url,
                    "snippet": str(item.get("snippet", "")).strip(),
                    "source": str(item.get("source", "")).strip(),
                    "date": str(item.get("date", "")).strip(),
                }
            )
    except Exception as exc:
        warnings.append(f"DuckDuckGo search failed: {exc}")

    ordered_urls: list[str] = []
    seen_urls: set[str] = set()
    for url in [*provided_urls, *[item.get("url", "") for item in search_results]]:
        normalized = str(url or "").strip()
        if not normalized or normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        ordered_urls.append(normalized)

    fetched_pages = fetch_urls_content(
        ordered_urls,
        timeout=20,
        max_workers=min(4, len(ordered_urls) or 1),
    ) if ordered_urls else []
    return search_results[:max_results], fetched_pages, warnings


def _generic_web_evidence_context(
    *,
    search_results: list[dict[str, Any]],
    fetched_pages: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    search_lookup = {
        str(item.get("url", "")).strip(): item
        for item in search_results
        if isinstance(item, dict) and str(item.get("url", "")).strip()
    }

    source_summary: list[str] = []
    seen_summary: set[str] = set()
    for item in search_results[:8]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip() or url
        if not url:
            continue
        line = f"- Web source: {title} ({url})"
        if line not in seen_summary:
            seen_summary.add(line)
            source_summary.append(line)

    blocks: list[str] = []
    for index, page in enumerate(fetched_pages[:8], start=1):
        url = str(page.get("url", "")).strip()
        lookup = search_lookup.get(url, {})
        title = str(lookup.get("title") or page.get("title") or url or f"web-source-{index}").strip()
        snippet = str(lookup.get("snippet", "")).strip()
        page_error = str(page.get("error", "")).strip()
        page_text = str(page.get("text", "")).strip()[:2500]
        lines = [
            f"[Web Source {index}] {title}",
            f"URL: {url or 'n/a'}",
        ]
        if snippet:
            lines.append(f"Search snippet: {snippet}")
        if page_error and not page_text:
            lines.append(f"Fetch note: {page_error}")
        elif page_text:
            lines.append(page_text)
        else:
            lines.append("No readable text extracted.")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks).strip(), source_summary


def _research_source_summary_lines(
    state: dict,
    *,
    web_search_enabled: bool,
    model: str,
    local_meta: dict,
    kb_grounding: dict[str, Any],
) -> list[str]:
    lines: list[str] = []

    kb_name = str((kb_grounding or {}).get("kb_name", "") or "").strip()
    kb_hits = int((kb_grounding or {}).get("hit_count", 0) or 0)
    kb_citations = list((kb_grounding or {}).get("citations", []) or [])
    if kb_name or kb_hits or kb_citations:
        label = kb_name or "active knowledge base"
        hit_label = "hit" if kb_hits == 1 else "hits"
        lines.append(f"- Knowledge base: {label} ({kb_hits} {hit_label})")
        for citation in kb_citations[:5]:
            source_id = str(
                citation.get("source_id")
                or citation.get("uri")
                or citation.get("path")
                or citation.get("title")
                or ""
            ).strip()
            if source_id:
                lines.append(f"- KB source: {source_id}")

    if web_search_enabled:
        lines.append(f"- Web evidence: live web research enabled via {str(model or 'configured model').strip()}")
    else:
        lines.append("- Web evidence: disabled for this run")

    local_file_count = int((local_meta or {}).get("local_file_count", 0) or 0)
    if local_file_count > 0:
        label = "file" if local_file_count == 1 else "files"
        lines.append(f"- Local {label} reviewed: {local_file_count}")

    provided_urls = _normalize_url_list(state.get("deep_research_source_urls", []))[:10]
    if provided_urls:
        for url in provided_urls:
            lines.append(f"- Provided URL: {url}")
    else:
        provided_url_count = int((local_meta or {}).get("provided_url_count", 0) or 0)
        if provided_url_count > 0:
            label = "URL" if provided_url_count == 1 else "URLs"
            lines.append(f"- Provided {label} reviewed: {provided_url_count}")

    return lines


def _research_coverage_lines(
    *,
    web_search_enabled: bool,
    model: str,
    local_meta: dict,
    kb_enabled: bool,
    kb_grounding: dict[str, Any],
    kb_warning: str,
) -> list[str]:
    lines = [
        f"Mode: {'web-backed' if web_search_enabled else 'local-only'}",
        f"Web search: {'enabled' if web_search_enabled else 'disabled'}",
        f"Model: {model if web_search_enabled else 'local-only-synthesis'}",
        f"Local files reviewed: {int((local_meta or {}).get('local_file_count', 0) or 0)}",
        f"Provided URLs reviewed: {int((local_meta or {}).get('provided_url_count', 0) or 0)}",
    ]

    kb_name = str((kb_grounding or {}).get("kb_name", "") or "").strip()
    kb_hits = int((kb_grounding or {}).get("hit_count", 0) or 0)
    if kb_enabled or kb_name or kb_hits:
        lines.append(f"Knowledge base: {kb_name or 'configured'}")
        lines.append(f"Knowledge base hits: {kb_hits}")
    else:
        lines.append("Knowledge base: disabled")

    if kb_warning:
        lines.append(f"Knowledge base note: {kb_warning}")
    return lines


def _research_next_steps(
    *,
    web_search_enabled: bool,
    local_meta: dict,
    kb_enabled: bool,
    kb_grounding: dict[str, Any],
) -> list[str]:
    steps: list[str] = []
    if int((local_meta or {}).get("local_file_count", 0) or 0) > 0:
        steps.append("Review the highest-signal local files for exact numbers, dates, and quotations before sharing this brief.")
    if web_search_enabled or int((local_meta or {}).get("provided_url_count", 0) or 0) > 0:
        steps.append("Cross-check the highest-impact claims against a second independent source before treating them as final.")
    if int((kb_grounding or {}).get("hit_count", 0) or 0) > 0:
        steps.append("Inspect the cited knowledge-base entries to confirm they still match the current evidence set.")
    elif kb_enabled:
        steps.append("Rebuild or retune the knowledge-base index if you expected internal grounding for this query.")
    if not steps:
        steps.append("Gather at least one primary source before relying on this brief for external decisions.")
    return steps[:3]


def _build_research_result_card(
    *,
    query: str,
    web_search_enabled: bool,
    local_meta: dict,
    kb_grounding: dict[str, Any],
    kb_warning: str,
    source_summary: list[str],
) -> dict[str, Any]:
    return {
        "kind": "brief",
        "title": "Deep Research Brief",
        "query": query,
        "mode": "web" if web_search_enabled else "local_only",
        "web_search_enabled": web_search_enabled,
        "local_sources": int((local_meta or {}).get("local_file_count", 0) or 0),
        "provided_urls": int((local_meta or {}).get("provided_url_count", 0) or 0),
        "research_kb_used": bool((kb_grounding or {}).get("prompt_context")),
        "research_kb_name": str((kb_grounding or {}).get("kb_name", "") or ""),
        "research_kb_hit_count": int((kb_grounding or {}).get("hit_count", 0) or 0),
        "research_kb_citations": list((kb_grounding or {}).get("citations", []) or []),
        "research_kb_warning": kb_warning,
        "source_summary": list(source_summary or []),
    }


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
        provided_urls = _normalize_url_list(state.get("deep_research_source_urls", []))[:10]
        for index, url in enumerate(provided_urls, start=1):
            page = dict(fetch_url_content(url, timeout=20) or {})
            if page.get("error"):
                page_text = f"URL extraction failed: {page.get('error')}"
            else:
                page_text = str(page.get("text", "")).strip()[:2500]
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


def _should_delegate_public_deep_research(state: dict[str, Any]) -> bool:
    workflow_type = str(state.get("workflow_type", "") or "").strip().lower()
    return bool(
        workflow_type in {"deep_research", "long_document"}
        or bool(state.get("deep_research_mode", False))
        or bool(state.get("long_document_mode", False))
        or bool(state.get("local_drive_force_long_document", False))
    )


def _retarget_active_deep_research_task(state: dict[str, Any], target_agent: str) -> None:
    active_task = state.get("active_task")
    if isinstance(active_task, dict) and str(active_task.get("recipient", "")).strip() == "deep_research_agent":
        active_task["recipient"] = target_agent
        state["active_task"] = active_task
        task_id = str(active_task.get("task_id", "") or "").strip()
    else:
        task_id = ""
    a2a = state.get("a2a", {})
    tasks = a2a.get("tasks", []) if isinstance(a2a, dict) else []
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task_id and str(task.get("task_id", "")).strip() != task_id:
            continue
        if str(task.get("recipient", "")).strip() == "deep_research_agent" and str(task.get("status", "pending")).strip() == "pending":
            task["recipient"] = target_agent
            break


def deep_research_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "deep_research_agent")
    state["deep_research_calls"] = state.get("deep_research_calls", 0) + 1
    call_number = state["deep_research_calls"]
	
    query = state.get("research_query") or task_content or state.get("current_objective") or state.get("user_query", "").strip()
    if not query:
        raise ValueError("deep_research_agent requires 'research_query' or 'user_query' in state.")

    if _should_delegate_public_deep_research(state):
        from tasks.long_document_tasks import long_document_agent

        _retarget_active_deep_research_task(state, "long_document_agent")
        state["workflow_type"] = "deep_research"
        state["deep_research_mode"] = True
        state["long_document_mode"] = True
        log_task_update(
            "Deep Research",
            "Delegating legacy deep_research_agent execution to long_document_agent for the full research pipeline.",
            query,
        )
        return long_document_agent(state)
	
    max_web_results = max(1, int(state.get("research_max_web_results", 6) or 6))
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
    kb_enabled = bool(state.get("research_kb_enabled", False))
    kb_ref = str(state.get("research_kb_id", "") or "").strip()
    kb_top_k = max(1, int(state.get("research_kb_top_k", 8) or 8))
    backend = _resolve_research_backend(state, web_search_enabled=web_search_enabled)
    provider = str(backend.get("provider") or PROVIDER_OPENAI).strip().lower() or PROVIDER_OPENAI
    model = str(backend.get("model") or DEFAULT_DEEP_RESEARCH_MODEL).strip() or DEFAULT_DEEP_RESEARCH_MODEL
    native_web_search_enabled = bool(backend.get("native_web_search_enabled", False))
    search_backend = "native_model" if native_web_search_enabled else "kendr_search" if web_search_enabled else "local_only"

    local_context, local_meta = _build_local_source_context(state, query, include_urls=True)
    has_non_kb_evidence = bool(
        web_search_enabled
        or int(local_meta.get("local_file_count", 0) or 0) > 0
        or int(local_meta.get("provided_url_count", 0) or 0) > 0
    )
    kb_warning = ""
    kb_grounding: dict[str, Any] = {}
    if kb_enabled:
        try:
            kb_grounding = build_research_grounding(
                query,
                kb_ref=kb_ref,
                top_k=kb_top_k,
                use_active_if_empty=True,
                require_indexed=True,
            )
        except Exception as exc:
            kb_warning = str(exc)
            if has_non_kb_evidence:
                log_task_update(
                    "Deep Research",
                    f"Knowledge base grounding unavailable; continuing with other sources. {kb_warning}",
                )
            else:
                raise ValueError(
                    f"Knowledge base grounding failed and no other evidence sources are available. {kb_warning}"
                ) from exc
        else:
            if int(kb_grounding.get("hit_count", 0) or 0) <= 0:
                kb_warning = (
                    f"Knowledge base '{kb_grounding.get('kb_name', 'unknown')}' returned no relevant results for this query."
                )
            if kb_grounding.get("prompt_context"):
                instructions = (
                    f"{instructions}\n\n"
                    "Prioritize the supplied knowledge-base grounding and explicitly reconcile it with any other findings.\n\n"
                    f"{kb_grounding['prompt_context']}"
                )
            elif not has_non_kb_evidence and not web_search_enabled:
                raise ValueError(
                    f"{kb_warning} No other evidence sources are available for this local-only run."
                )
    if local_context:
        instructions = (
            f"{instructions}\n\n"
            "Prioritize the supplied local source context and explicitly reconcile it with any additional findings.\n\n"
            f"Local source context:\n{local_context}"
        )
    combined_source_context = "\n\n".join(
        part
        for part in (kb_grounding.get("prompt_context", ""), local_context)
        if str(part).strip()
    ).strip()
    source_summary = _research_source_summary_lines(
        state,
        web_search_enabled=web_search_enabled,
        model=str(model),
        local_meta=local_meta,
        kb_grounding=kb_grounding,
    )
    coverage_summary = _research_coverage_lines(
        web_search_enabled=web_search_enabled,
        model=str(model),
        local_meta=local_meta,
        kb_enabled=kb_enabled,
        kb_grounding=kb_grounding,
        kb_warning=kb_warning,
    )
    recommended_next_steps = _research_next_steps(
        web_search_enabled=web_search_enabled,
        local_meta=local_meta,
        kb_enabled=kb_enabled,
        kb_grounding=kb_grounding,
    )
    result_card = _build_research_result_card(
        query=query,
        web_search_enabled=web_search_enabled,
        local_meta=local_meta,
        kb_grounding=kb_grounding,
        kb_warning=kb_warning,
        source_summary=source_summary,
    )

    if not web_search_enabled:
        local_only_prompt = f"""
You are conducting a deep research pass without internet or web search.

Research query:
{query}

Available source context:
{combined_source_context or "No local file context was provided."}

Write a source-aware research memo that:
- uses only the provided source context
- does not invent external citations
- calls out gaps or uncertainty clearly
- ends with a concise recommended next-steps section
"""
        raw_output_text = llm_text(local_only_prompt).strip()
        findings_text, cited_sources = split_sources_section(raw_output_text)
        output_text = render_phase0_report(
            title="Deep Research Brief",
            objective=query,
            findings=findings_text or raw_output_text,
            coverage_lines=coverage_summary,
            next_steps=recommended_next_steps,
            sources_lines=[*source_summary, *cited_sources],
        )
        payload = {
            "mode": "local_only",
            "query": query,
            "local_context": combined_source_context,
            "local_source_count": local_meta.get("local_file_count", 0),
            "provided_url_count": local_meta.get("provided_url_count", 0),
            "research_kb": kb_grounding,
            "research_kb_used": bool(kb_grounding.get("prompt_context")),
            "research_kb_warning": kb_warning,
            "source_summary": [*source_summary, *cited_sources],
            "coverage_summary": coverage_summary,
            "recommended_next_steps": recommended_next_steps,
            "raw_output_text": raw_output_text,
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
        state["research_provider"] = provider
        state["research_raw"] = payload
        state["research_kb_used"] = bool(payload.get("research_kb_used"))
        state["research_kb_name"] = str((kb_grounding or {}).get("kb_name", "") or "")
        state["research_kb_hit_count"] = int((kb_grounding or {}).get("hit_count", 0) or 0)
        state["research_kb_citations"] = list((kb_grounding or {}).get("citations", []) or [])
        state["research_kb_warning"] = kb_warning
        state["research_source_summary"] = payload["source_summary"]
        state["deep_research_result_card"] = {
            **result_card,
            "search_backend": search_backend,
            "source_summary": list(payload["source_summary"]),
        }
        state["draft_response"] = output_text
        log_task_update(
            "Deep Research",
            (
                f"Completed local-only deep research run #{call_number} using "
                f"{local_meta.get('local_file_count', 0)} local file(s), "
                f"{local_meta.get('provided_url_count', 0)} provided URL(s), and "
                f"{int((kb_grounding or {}).get('hit_count', 0) or 0)} KB hit(s)."
            ),
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

    log_task_update(
        "Deep Research",
        (
            f"Research pass #{call_number} started with provider '{provider or 'default'}', "
            f"model '{model}', backend '{search_backend}'."
        ),
        query,
    )

    if native_web_search_enabled:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when the selected Deep Research model uses native web search.")

        client = OpenAI(api_key=api_key)
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
        payload["mode"] = "native_web_search"
        payload["search_backend"] = search_backend
        payload["research_provider"] = provider
        payload["research_kb"] = kb_grounding
        payload["research_kb_used"] = bool(kb_grounding.get("prompt_context"))
        payload["research_kb_warning"] = kb_warning
        raw_output_text = getattr(response, "output_text", None) or _extract_output_text(payload)
        findings_text, cited_sources = split_sources_section(raw_output_text)
        payload["source_summary"] = [*source_summary, *cited_sources]
        payload["coverage_summary"] = coverage_summary
        payload["recommended_next_steps"] = recommended_next_steps
        payload["raw_output_text"] = raw_output_text
        output_text = render_phase0_report(
            title="Deep Research Brief",
            objective=query,
            findings=findings_text or raw_output_text,
            coverage_lines=coverage_summary,
            next_steps=recommended_next_steps,
            sources_lines=payload["source_summary"],
        )
        payload["output_text"] = output_text
    else:
        log_task_update(
            "Deep Research",
            (
                f"{provider or 'selected'} / {model} does not expose native web search here. "
                "Using Kendr web search fallback for source gathering."
            ),
        )
        provided_urls = _normalize_url_list(state.get("deep_research_source_urls", []))[:10]
        search_results, fetched_pages, search_warnings = _collect_generic_web_evidence(
            query,
            provided_urls=provided_urls,
            max_results=max_web_results,
        )
        web_context, fallback_source_lines = _generic_web_evidence_context(
            search_results=search_results,
            fetched_pages=fetched_pages,
        )
        if not web_context and not combined_source_context:
            warning_text = " ".join(search_warnings).strip()
            raise ValueError(
                "Deep research could not collect any evidence with the configured web-search fallback."
                + (f" {warning_text}" if warning_text else "")
            )

        fallback_prompt = f"""
You are conducting a deep research pass using Kendr's web-search fallback because the selected model/provider does not expose native web search.

Research query:
{query}

Research instructions:
{instructions}

Collected web evidence:
{web_context or "No web pages were successfully fetched. Use only the supplied local or knowledge-base context."}

Supplemental local or knowledge-base context:
{combined_source_context or "None"}

Write a source-aware research memo that:
- uses only the evidence supplied above
- attributes important claims to the available URLs or supplied context
- calls out uncertainty and evidence gaps clearly
- ends with a concise Sources section listing the URLs you relied on
- ends with concise recommended next steps
""".strip()
        with runtime_model_override(provider, model):
            raw_output_text = llm_text(fallback_prompt).strip()
        findings_text, cited_sources = split_sources_section(raw_output_text)
        payload = {
            "mode": "web_fallback",
            "search_backend": search_backend,
            "query": query,
            "research_provider": provider,
            "research_model": model,
            "search_results": search_results,
            "fetched_pages": fetched_pages,
            "search_warnings": search_warnings,
            "local_context": combined_source_context,
            "local_source_count": local_meta.get("local_file_count", 0),
            "provided_url_count": local_meta.get("provided_url_count", 0),
            "research_kb": kb_grounding,
            "research_kb_used": bool(kb_grounding.get("prompt_context")),
            "research_kb_warning": kb_warning,
            "source_summary": [*source_summary, *fallback_source_lines, *search_warnings, *cited_sources],
            "coverage_summary": coverage_summary,
            "recommended_next_steps": recommended_next_steps,
            "raw_output_text": raw_output_text,
        }
        output_text = render_phase0_report(
            title="Deep Research Brief",
            objective=query,
            findings=findings_text or raw_output_text,
            coverage_lines=coverage_summary,
            next_steps=recommended_next_steps,
            sources_lines=payload["source_summary"],
        )
        payload["output_text"] = output_text
        response_id = f"kendr_search_{call_number}"
        status = "completed"

    raw_filename = f"deep_research_raw_{call_number}.json"
    output_filename = f"deep_research_output_{call_number}.txt"

    write_text_file(raw_filename, json.dumps(payload, indent=2, ensure_ascii=False))
    write_text_file(output_filename, output_text)

    state["research_response_id"] = response_id
    state["research_status"] = getattr(response, "status", status) if native_web_search_enabled else status
    state["research_result"] = output_text
    state["research_model"] = model
    state["research_provider"] = provider
    state["research_raw"] = payload
    state["research_kb_used"] = bool(payload.get("research_kb_used"))
    state["research_kb_name"] = str((kb_grounding or {}).get("kb_name", "") or "")
    state["research_kb_hit_count"] = int((kb_grounding or {}).get("hit_count", 0) or 0)
    state["research_kb_citations"] = list((kb_grounding or {}).get("citations", []) or [])
    state["research_kb_warning"] = kb_warning
    state["research_source_summary"] = payload["source_summary"]
    state["deep_research_result_card"] = {
        **result_card,
        "search_backend": search_backend,
        "source_summary": list(payload["source_summary"]),
    }
    state["draft_response"] = output_text

    log_task_update(
        "Deep Research",
        (
            f"Deep research finished with status '{state['research_status']}'. "
            f"Saved artifacts to {OUTPUT_DIR}/{output_filename}. "
            f"Search backend: {search_backend}. "
            f"KB hits: {int((kb_grounding or {}).get('hit_count', 0) or 0)}."
        ),
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
