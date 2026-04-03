from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import textwrap

from openai import OpenAI

from kendr.execution_trace import append_execution_event
from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.coding_tasks import _extract_output_text
from tasks.file_memory import bootstrap_file_memory, update_planning_file
from tasks.planning_tasks import build_plan_approval_prompt, normalize_plan_data, plan_as_markdown
from tasks.research_infra import fetch_url_content, llm_json, llm_text, serp_search
from tasks.utils import OUTPUT_DIR, log_task_update, model_selection_for_agent, write_text_file, resolve_output_path


DEFAULT_DEEP_RESEARCH_MODEL = os.getenv("OPENAI_DEEP_RESEARCH_MODEL", "o4-mini-deep-research")
DEFAULT_RESEARCH_FORMATS = ["pdf", "docx", "html", "md"]
SUPPORTED_CITATION_STYLES = {"apa", "mla", "chicago", "ieee", "vancouver", "harvard"}
DEEP_RESEARCH_LABEL = "Deep Research"


def _trace_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _trace_research_event(
    state: dict,
    *,
    title: str,
    detail: str = "",
    command: str = "",
    status: str = "running",
    kind: str = "research_activity",
    started_at: str = "",
    completed_at: str = "",
    metadata: dict[str, Any] | None = None,
    subtask: str = "",
) -> dict[str, Any]:
    return append_execution_event(
        state,
        kind=kind,
        actor="long_document_agent",
        status=status,
        title=title,
        detail=detail,
        command=command,
        started_at=started_at,
        completed_at=completed_at,
        metadata=metadata or {},
        persist=True,
        active_agent="long_document_agent",
        task=str(state.get("current_objective") or state.get("user_query") or "").strip(),
        subtask=subtask,
    )


def _trace_url_list(urls: list[str] | None, *, limit: int = 6) -> list[str]:
    compact: list[str] = []
    for raw in urls or []:
        value = str(raw or "").strip()
        if not value or value in compact:
            continue
        compact.append(value)
        if len(compact) >= limit:
            break
    return compact

AGENT_METADATA = {
    "long_document_agent": {
        "description": (
            "Builds deep research reports through tiered planning, source-backed evidence gathering, "
            "cross-section correlation, plagiarism checks, and multi-format export."
        ),
        "skills": ["deep-research", "reporting", "chaptering", "synthesis", "citations", "plagiarism"],
        "input_keys": [
            "current_objective",
            "deep_research_mode",
            "long_document_mode",
            "long_document_pages",
            "long_document_sections",
            "long_document_section_pages",
            "long_document_title",
            "long_document_collect_sources_first",
            "long_document_disable_visuals",
            "long_document_section_references",
            "long_document_section_search",
            "long_document_section_search_results",
            "research_model",
            "research_instructions",
            "research_max_tool_calls",
            "research_max_output_tokens",
            "research_poll_interval_seconds",
            "research_max_wait_seconds",
            "research_heartbeat_seconds",
            "research_output_formats",
            "research_citation_style",
            "research_enable_plagiarism_check",
            "research_web_search_enabled",
            "research_date_range",
            "research_max_sources",
            "research_checkpoint_enabled",
            "deep_research_source_urls",
        ],
        "output_keys": [
            "deep_research_analysis",
            "deep_research_result_card",
            "long_document_title",
            "long_document_outline",
            "long_document_sections_data",
            "long_document_artifact_dir",
            "long_document_compiled_path",
            "long_document_compiled_html_path",
            "long_document_compiled_docx_path",
            "long_document_compiled_pdf_path",
            "long_document_outline_md_path",
            "long_document_coherence_base_path",
            "long_document_coherence_live_path",
            "long_document_references_path",
            "long_document_references_json_path",
            "long_document_visual_index_path",
            "long_document_visual_index_json_path",
            "long_document_summary",
            "draft_response",
        ],
        "requirements": ["openai"],
        "display_name": "Deep Research Report Agent",
        "category": "documents",
        "intent_patterns": [
            "deep research report", "write a complete document", "research and write", "create a report",
            "generate a handbook", "produce a whitepaper", "write a guide",
            "document about", "full report on", "comprehensive guide to",
        ],
        "active_when": ["env:OPENAI_API_KEY"],
        "config_hint": "Add your OpenAI API key in Setup → Providers.",
    }
}


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _normalize_title(value: str, fallback: str) -> str:
    title = str(value or "").strip()
    if title:
        return title
    return fallback


def _read_text_file(path_value: str, fallback: str = "") -> str:
    path = str(path_value or "").strip()
    if not path:
        return fallback
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return fallback


def _trim_text(text: str, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def _normalize_research_formats(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        items = [part.strip().lower() for part in raw_value.split(",")]
    elif isinstance(raw_value, list):
        items = [str(part).strip().lower() for part in raw_value]
    else:
        items = []
    seen: set[str] = set()
    normalized: list[str] = []
    for item in items:
        if not item or item not in {"pdf", "docx", "html", "md"} or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized or list(DEFAULT_RESEARCH_FORMATS)


def _normalize_citation_style(raw_value: Any) -> str:
    style = str(raw_value or "").strip().lower()
    if style in SUPPORTED_CITATION_STYLES:
        return style
    return "apa"


def _tier_budget(tier: int) -> dict[str, Any]:
    budgets = {
        1: {"max_tokens": 5000, "max_sources": 3, "max_duration_minutes": 1},
        2: {"max_tokens": 30000, "max_sources": 20, "max_duration_minutes": 5},
        3: {"max_tokens": 150000, "max_sources": 60, "max_duration_minutes": 20},
        4: {"max_tokens": 500000, "max_sources": 150, "max_duration_minutes": 90},
        5: {"max_tokens": 0, "max_sources": 0, "max_duration_minutes": 0},
    }
    return budgets.get(_safe_int(tier, 2, 1, 5), budgets[2])


def _default_subtopics(objective: str) -> list[str]:
    seeds = [
        "Market structure and baseline context",
        "Key players and competitive dynamics",
        "Evidence, benchmarks, and current data points",
        "Risks, contradictions, and areas of uncertainty",
        "Implications, outlook, and conclusion",
    ]
    text = str(objective or "").strip()
    if not text:
        return seeds[:3]
    fragments = re.split(r"[?.!]", text)
    topical = [frag.strip().capitalize() for frag in fragments if len(frag.strip().split()) >= 4]
    return (topical[:4] or seeds[:4]) + ([seeds[-1]] if seeds[-1] not in topical[:4] else [])


def _research_depth_analysis(
    objective: str,
    *,
    target_pages: int,
    requested_sources: list[str],
    date_range: str,
) -> dict[str, Any]:
    text = str(objective or "").strip()
    lowered = text.lower()
    heuristic_tier = 2
    reason_bits: list[str] = []

    if len(text.split()) > 50:
        heuristic_tier += 1
        reason_bits.append("query length suggests broad scope")
    if any(token in lowered for token in ("compare", "analyse", "analyze", "comprehensive", "thorough", "deep", "full report", "detailed", "exhaustive")):
        heuristic_tier += 1
        reason_bits.append("explicit deep-analysis wording")
    if target_pages >= 100:
        heuristic_tier += 2
        reason_bits.append("very large page target")
    elif target_pages >= 50:
        heuristic_tier += 2
        reason_bits.append("large page target")
    elif target_pages >= 20:
        heuristic_tier += 1
        reason_bits.append("multi-section page target")
    if any(token in lowered for token in ("academic", "peer-reviewed", "scholarly", "patent", "scientific", "literature review")):
        heuristic_tier += 1
        reason_bits.append("academic / patent scope")
    if date_range and str(date_range).strip().lower() not in {"", "all_time", "all time"}:
        heuristic_tier += 1
        reason_bits.append("explicit temporal scope")
    if any(token in lowered for token in ("quick", "brief", "summary", "tldr", "short")):
        heuristic_tier -= 1
        reason_bits.append("short-form wording lowers depth")
    if len(re.findall(r"\b[A-Z][a-zA-Z0-9&.-]+\b", text)) >= 4:
        heuristic_tier += 1
        reason_bits.append("multiple named entities detected")
    heuristic_tier = max(1, min(5, heuristic_tier))

    estimated_pages = target_pages if target_pages > 0 else {1: 1, 2: 4, 3: 18, 4: 50, 5: 120}[heuristic_tier]
    estimated_sources = min(200, max(3, {1: 3, 2: 15, 3: 45, 4: 110, 5: 200}[heuristic_tier] + (10 if requested_sources else 0)))
    estimated_duration = {1: 1, 2: 5, 3: 15, 4: 45, 5: 120}[heuristic_tier]
    subtopics = _default_subtopics(text)

    fallback = {
        "tier": heuristic_tier,
        "reason": "; ".join(reason_bits) or "heuristic estimate",
        "estimated_sources": estimated_sources,
        "estimated_pages": estimated_pages,
        "subtopics": subtopics[:6],
        "requires_deep_research": heuristic_tier >= 3,
        "estimated_duration_minutes": estimated_duration,
    }

    prompt = f"""
You are a research complexity analyser.

Given the query and heuristic estimate below, determine the final research tier (1-5).
Respond with JSON only:
{{
  "tier": 3,
  "reason": "string",
  "estimated_sources": 40,
  "estimated_pages": 15,
  "subtopics": ["...", "..."],
  "requires_deep_research": true,
  "estimated_duration_minutes": 15
}}

Query:
{text}

Heuristic estimate:
{json.dumps(fallback, ensure_ascii=False)}
"""
    try:
        data = llm_json(prompt, fallback)
    except Exception:
        data = fallback

    if not isinstance(data, dict):
        data = fallback
    tier = _safe_int(data.get("tier"), heuristic_tier, 1, 5)
    estimated_pages = _safe_int(data.get("estimated_pages"), fallback["estimated_pages"], 1, 500)
    estimated_sources = _safe_int(data.get("estimated_sources"), fallback["estimated_sources"], 1, 400)
    estimated_duration = _safe_int(data.get("estimated_duration_minutes"), fallback["estimated_duration_minutes"], 1, 1440)
    subtopics_value = data.get("subtopics", [])
    if not isinstance(subtopics_value, list):
        subtopics_value = fallback["subtopics"]
    subtopics = [str(item).strip() for item in subtopics_value if str(item).strip()][:8] or fallback["subtopics"]
    budget = _tier_budget(tier)
    if budget["max_sources"]:
        estimated_sources = min(estimated_sources, int(budget["max_sources"]))
    return {
        "tier": tier,
        "reason": str(data.get("reason", "")).strip() or fallback["reason"],
        "estimated_sources": estimated_sources,
        "estimated_pages": estimated_pages,
        "subtopics": subtopics,
        "requires_deep_research": bool(data.get("requires_deep_research", tier >= 3)),
        "estimated_duration_minutes": estimated_duration,
        "budget": budget,
        "requested_sources": requested_sources,
        "date_range": date_range or "all_time",
    }


def _coherence_base_context(state: dict, objective: str) -> str:
    memory_blocks = [
        ("Agent.md", _read_text_file(state.get("memory_agent_file"), "")),
        ("soul.md", _read_text_file(state.get("memory_soul_file"), "")),
        ("memory.md", _read_text_file(state.get("memory_long_term_file"), "")),
        ("session.md", _read_text_file(state.get("memory_session_file"), "")),
        ("planning.md", _read_text_file(state.get("memory_planning_file"), "")),
    ]
    parts = [f"[Objective]\n{objective}"]
    for name, content in memory_blocks:
        if not str(content).strip():
            continue
        parts.append(f"[{name}]\n{_trim_text(content, 3000)}")
    fallback_context = str(state.get("file_memory_context", "")).strip()
    if fallback_context:
        parts.append(f"[file_memory_context]\n{_trim_text(fallback_context, 4000)}")
    return "\n\n".join(parts)


def _artifact_file(run_dir: str, filename: str) -> str:
    return f"{run_dir.rstrip('/')}/{filename.lstrip('/')}"


def _normalize_output_relative_path(path_value: str) -> str:
    value = str(path_value or "").strip()
    prefix = f"{OUTPUT_DIR}/"
    if value.startswith(prefix):
        return value[len(prefix):]
    return value


def _resolve_existing_output_path(path_value: str) -> str:
    if not str(path_value or "").strip():
        return ""
    candidate = Path(str(path_value))
    if candidate.is_absolute() and candidate.exists():
        return str(candidate)
    normalized = _normalize_output_relative_path(str(path_value))
    resolved = resolve_output_path(normalized)
    if Path(resolved).exists():
        return resolved
    resolved_fallback = resolve_output_path(str(path_value))
    if Path(resolved_fallback).exists():
        return resolved_fallback
    return resolved


def _source_label(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        file_name = Path(parsed.path or "").name
        return f"file:{file_name or 'local-source'}"
    host = parsed.netloc or "source"
    path = (parsed.path or "/").strip("/")
    if not path:
        return host
    parts = [item for item in path.split("/") if item][:2]
    return f"{host}/{'/'.join(parts)}"


def _collect_local_drive_evidence(state: dict, *, max_items: int = 25) -> list[dict]:
    summaries = state.get("local_drive_document_summaries") or []
    if not isinstance(summaries, list):
        return []
    entries = []
    for item in summaries[:max_items]:
        if not isinstance(item, dict):
            continue
        entries.append(
            {
                "source_type": "local_drive",
                "path": str(item.get("path", "")).strip(),
                "file_name": str(item.get("file_name", "")).strip(),
                "type": str(item.get("type", "")).strip(),
                "char_count": int(item.get("char_count", 0) or 0),
                "summary": str(item.get("summary", "")).strip(),
                "error": str(item.get("error", "")).strip(),
            }
        )
    return entries


def _file_source_url(path_value: str) -> str:
    try:
        return Path(str(path_value or "")).resolve().as_uri()
    except Exception:
        return f"file://{str(path_value or '').strip()}"


def _sources_from_local_entries(entries: list[dict]) -> list[dict]:
    sources = []
    for index, entry in enumerate(entries or [], start=1):
        path_value = str(entry.get("path", "")).strip()
        if not path_value:
            continue
        label = str(entry.get("file_name", "")).strip() or Path(path_value).name or f"Local file {index}"
        sources.append({"id": f"L{index}", "url": _file_source_url(path_value), "label": label})
    return sources


def _normalize_research_urls(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        raw_items = re.split(r"[\n,]", raw_value)
    elif isinstance(raw_value, list):
        raw_items = raw_value
    else:
        raw_items = []
    urls: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        candidate = _normalize_url(str(item or "").strip())
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _sources_from_url_entries(entries: list[dict]) -> list[dict]:
    sources = []
    for index, entry in enumerate(entries or [], start=1):
        url = str(entry.get("url", "")).strip()
        if not url:
            continue
        label = str(entry.get("label", "")).strip() or _source_label(url)
        sources.append({"id": f"U{index}", "url": url, "label": label})
    return sources


def _collect_user_url_evidence(objective: str, state: dict, *, max_items: int = 12) -> list[dict]:
    urls = _normalize_research_urls(state.get("deep_research_source_urls", []))
    if not urls:
        return []
    fetch_started_at = _trace_now()
    _trace_research_event(
        state,
        title="Extracting provided URLs",
        detail=f"Fetching and summarizing {min(len(urls), max_items)} user-provided URLs.",
        command="\n".join(urls[:max_items]),
        status="running",
        started_at=fetch_started_at,
        metadata={"phase": "provided_urls", "urls": _trace_url_list(urls[:max_items])},
        subtask="Fetch provided URLs",
    )
    entries = []
    for url in urls[:max_items]:
        try:
            page = fetch_url_content(url, timeout=20)
            page_text = _trim_text(str(page.get("text", "")).strip(), 8000)
            if page_text:
                summary = llm_text(
                    f"""
You are summarizing a user-provided URL for a deep research report.

Primary objective:
{objective}

URL:
{url}

Extracted content:
{page_text}

Write a concise evidence summary covering:
- what this page is about
- concrete facts, numbers, dates, and named entities
- relevance to the objective
- any credibility or freshness concerns
"""
                ).strip()
            else:
                summary = "No readable text was extracted from this URL."
            entries.append(
                {
                    "source_type": "provided_url",
                    "url": url,
                    "label": _source_label(url),
                    "content_type": str(page.get("content_type", "")).strip(),
                    "char_count": len(str(page.get("text", "")).strip()),
                    "summary": summary,
                    "excerpt": _trim_text(page_text, 2500),
                    "error": "",
                }
            )
        except Exception as exc:
            entries.append(
                {
                    "source_type": "provided_url",
                    "url": url,
                    "label": _source_label(url),
                    "content_type": "",
                    "char_count": 0,
                    "summary": "",
                    "excerpt": "",
                    "error": str(exc),
                }
            )
    ok_urls = [str(item.get("url", "")).strip() for item in entries if not str(item.get("error", "")).strip()]
    failed_urls = [str(item.get("url", "")).strip() for item in entries if str(item.get("error", "")).strip()]
    _trace_research_event(
        state,
        title="Extracting provided URLs",
        detail=(
            f"Extracted {len(ok_urls)} URL(s)"
            + (f"; {len(failed_urls)} failed." if failed_urls else ".")
        ),
        command="\n".join(urls[:max_items]),
        status="completed" if not failed_urls else ("failed" if not ok_urls else "completed"),
        started_at=fetch_started_at,
        completed_at=_trace_now(),
        metadata={
            "phase": "provided_urls",
            "urls": _trace_url_list(ok_urls or urls[:max_items]),
            "failed_urls": _trace_url_list(failed_urls),
        },
        subtask="Fetch provided URLs",
    )
    return entries


def _build_local_only_research_notes(
    *,
    objective: str,
    focus: str,
    local_entries: list[dict],
    url_entries: list[dict],
    continuity_notes: list[str] | None = None,
) -> str:
    corpus = {
        "objective": objective,
        "focus": focus,
        "continuity_notes": list(continuity_notes or [])[-8:],
        "local_files": [
            {
                "file_name": item.get("file_name", ""),
                "path": item.get("path", ""),
                "type": item.get("type", ""),
                "summary": item.get("summary", ""),
                "error": item.get("error", ""),
            }
            for item in (local_entries or [])[:25]
        ],
        "provided_urls": [
            {
                "url": item.get("url", ""),
                "label": item.get("label", ""),
                "summary": item.get("summary", ""),
                "error": item.get("error", ""),
                "excerpt": item.get("excerpt", ""),
            }
            for item in (url_entries or [])[:12]
        ],
    }
    return llm_text(
        f"""
You are synthesizing a deep research corpus without open web search.

Use only the supplied local files and explicitly provided URL extracts.
Do not invent external facts or imply that web search was performed.

Corpus:
{json.dumps(corpus, indent=2, ensure_ascii=False)[:24000]}

Write a structured evidence memo that includes:
- the strongest supported findings
- important numbers, dates, entities, and claims
- contradictions, gaps, or low-confidence areas
- which files or URLs are most relevant to this focus
"""
    ).strip()


def _collect_google_search_evidence(query: str, *, num: int = 10) -> dict:
    try:
        payload = serp_search(query, num=num)
    except Exception as exc:
        return {"results": [], "error": str(exc)}
    results = []
    for item in payload.get("organic_results", [])[:num]:
        results.append(
            {
                "title": str(item.get("title", "")).strip(),
                "url": str(item.get("link", "")).strip(),
                "snippet": str(item.get("snippet", "")).strip(),
                "source": str(item.get("source", "")).strip(),
                "date": str(item.get("date", "")).strip(),
            }
        )
    return {"results": results, "raw": payload, "error": ""}


def _sources_from_search_results(results: list[dict], *, prefix: str = "S") -> list[dict]:
    entries = []
    for index, item in enumerate(results or [], start=1):
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        label = str(item.get("title", "")).strip() or _source_label(url)
        entries.append({"id": f"{prefix}{index}", "url": url, "label": label})
    return entries


def _search_results_markdown(results: list[dict]) -> str:
    if not results:
        return "No web search results were available."
    lines = ["Web search results (SerpAPI):"]
    for item in results:
        title = str(item.get("title", "")).strip() or "Untitled"
        url = str(item.get("url", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        line = f"- {title}"
        if snippet:
            line += f": {snippet}"
        if url:
            line += f" ({url})"
        lines.append(line)
    return "\n".join(lines)


def _merge_sources(primary: list[dict], secondary: list[dict], *, max_sources: int = 60) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for item in (primary or []) + (secondary or []):
        url = str(item.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(item)
        if len(merged) >= max_sources:
            break
    # Re-number sequentially
    renumbered = []
    for index, item in enumerate(merged, start=1):
        renumbered.append({"id": f"S{index}", "url": item["url"], "label": item.get("label", "") or _source_label(item["url"])})
    return renumbered


def _format_evidence_bank_markdown(
    *,
    objective: str,
    local_entries: list[dict],
    url_entries: list[dict],
    search_results: dict,
    research_notes_text: str,
    source_ledger: list[dict],
    insufficiency_note: str,
) -> str:
    lines = ["# Evidence Bank", "", "## Objective", objective.strip(), ""]
    if insufficiency_note:
        lines.extend(["## Data Sufficiency Note", insufficiency_note.strip(), ""])
    lines.append("## Local File Sources")
    if local_entries:
        for entry in local_entries:
            label = entry.get("file_name") or entry.get("path") or "unknown"
            lines.append(f"- File: {label}")
            if entry.get("path"):
                lines.append(f"  - Path: {entry['path']}")
            if entry.get("type"):
                lines.append(f"  - Type: {entry['type']}")
            if entry.get("char_count"):
                lines.append(f"  - Characters: {entry['char_count']}")
            if entry.get("error"):
                lines.append(f"  - Extraction error: {entry['error']}")
            if entry.get("summary"):
                lines.append(f"  - Summary: {entry['summary']}")
    else:
        lines.append("- No local-drive sources were found.")
    lines.append("")

    lines.append("## User-Provided URL Sources")
    if url_entries:
        for entry in url_entries:
            label = entry.get("label") or entry.get("url") or "URL"
            lines.append(f"- URL: {label}")
            if entry.get("url"):
                lines.append(f"  - Link: {entry['url']}")
            if entry.get("content_type"):
                lines.append(f"  - Content type: {entry['content_type']}")
            if entry.get("char_count"):
                lines.append(f"  - Characters: {entry['char_count']}")
            if entry.get("error"):
                lines.append(f"  - Extraction error: {entry['error']}")
            if entry.get("summary"):
                lines.append(f"  - Summary: {entry['summary']}")
    else:
        lines.append("- No explicit URL sources were provided.")
    lines.append("")

    lines.append("## Web Search Results (Google via SerpAPI)")
    results = search_results.get("results", []) if isinstance(search_results, dict) else []
    if results:
        for item in results:
            title = item.get("title") or "Untitled"
            url = item.get("url") or ""
            snippet = item.get("snippet") or ""
            lines.append(f"- {title}")
            if url:
                lines.append(f"  - URL: {url}")
            if snippet:
                lines.append(f"  - Snippet: {snippet}")
    else:
        error = ""
        if isinstance(search_results, dict):
            error = str(search_results.get("error", "")).strip()
        if error:
            lines.append(f"- Search unavailable: {error}")
        else:
            lines.append("- No search results were collected.")
    lines.append("")

    lines.append("## Research Notes")
    lines.append(research_notes_text.strip() or "No research notes generated.")
    lines.append("")
    lines.append("## Source Ledger")
    if source_ledger:
        for item in source_ledger:
            lines.append(f"- [{item['id']}] {item['label']} - {item['url']}")
    else:
        lines.append("- No sources were extracted.")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def _write_absolute_text_file(path_value: str, content: str) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_long_document_addendum(
    state: dict,
    *,
    objective: str,
    call_number: int,
    artifact_dir: str,
) -> dict:
    compiled_path = _resolve_existing_output_path(state.get("long_document_compiled_path", ""))
    if not compiled_path or not Path(compiled_path).exists():
        summary = "Addendum requested but compiled document was not found. Skipping addendum."
        state["draft_response"] = summary
        state["_skip_review_once"] = True
        return publish_agent_output(
            state,
            "long_document_agent",
            summary,
            f"long_document_addendum_{call_number}",
            recipients=["orchestrator_agent", "reviewer_agent", "report_agent"],
        )

    attempts = int(state.get("long_document_addendum_attempts", 0) or 0) + 1
    max_attempts = int(state.get("long_document_addendum_max_attempts", 1) or 1)
    state["long_document_addendum_attempts"] = attempts
    if attempts > max_attempts:
        summary = f"Addendum requested but max attempts ({max_attempts}) reached. Skipping."
        state["draft_response"] = summary
        state["long_document_addendum_requested"] = False
        state["long_document_addendum_completed"] = True
        state["_skip_review_once"] = True
        return publish_agent_output(
            state,
            "long_document_agent",
            summary,
            f"long_document_addendum_{call_number}",
            recipients=["orchestrator_agent", "reviewer_agent", "report_agent"],
        )

    instructions = str(state.get("long_document_addendum_instructions") or objective).strip()
    evidence_excerpt = (
        str(state.get("long_document_evidence_bank_excerpt") or "").strip()
        or _read_text_file(state.get("long_document_evidence_bank_path", ""), "")
    )
    compiled_excerpt = _trim_text(_read_text_file(compiled_path, 12000), 12000)
    words_target = _safe_int(state.get("long_document_addendum_words"), 1200, 400, 5000)

    log_task_update(
        DEEP_RESEARCH_LABEL,
        f"Generating addendum (attempt {attempts + 1}) targeting ~{words_target} words.",
    )

    prompt = f"""
You are drafting a focused addendum to a deep research financial advisory report.
Use the reviewer feedback and evidence bank to add missing analysis without rewriting the full report.

Primary objective:
{objective}

Reviewer feedback / required additions:
{instructions}

Evidence bank excerpt:
{_trim_text(evidence_excerpt, 6000)}

Excerpt from the existing report:
{compiled_excerpt}

Write an addendum of about {words_target} words that:
- Directly addresses the missing market dynamics and geographic insights.
- Cites gaps explicitly where data is unavailable.
- Includes a short "Addendum Takeaways" list.
"""
    addendum_text = llm_text(prompt).strip()
    if not addendum_text:
        addendum_text = "Addendum could not be generated from the available evidence."
    log_task_update(
        DEEP_RESEARCH_LABEL,
        f"Addendum draft complete: {len(addendum_text.split())} words, {len(addendum_text)} chars.",
    )

    addendum_title = "## Addendum: Reviewer Follow-ups"
    addendum_body = f"{addendum_title}\n\n{addendum_text}\n"
    compiled_existing = _read_text_file(compiled_path, "")
    compiled_new = f"{compiled_existing.rstrip()}\n\n{addendum_body}"
    _write_absolute_text_file(compiled_path, compiled_new)

    addendum_filename = _artifact_file(artifact_dir, f"long_document_addendum_{attempts}.md")
    write_text_file(addendum_filename, addendum_body)

    manifest_path = _resolve_existing_output_path(state.get("long_document_manifest_path", ""))
    if manifest_path and Path(manifest_path).exists():
        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        if isinstance(manifest, dict):
            manifest["addendum_file"] = f"{OUTPUT_DIR}/{addendum_filename}"
            manifest["addendum_attempts"] = attempts
            _write_absolute_text_file(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False))

    state["long_document_addendum_requested"] = False
    state["long_document_addendum_completed"] = True
    state["long_document_addendum_path"] = f"{OUTPUT_DIR}/{addendum_filename}"
    state["_skip_review_once"] = True
    if bool(state.get("long_document_addendum_force_no_review", True)):
        state["skip_reviews"] = True
    summary = (
        "Addendum generated and appended to compiled report.\n"
        f"- Compiled markdown: {compiled_path}\n"
        f"- Addendum file: {OUTPUT_DIR}/{addendum_filename}\n"
    )
    state["draft_response"] = summary
    log_task_update(DEEP_RESEARCH_LABEL, "Addendum appended to compiled report.", summary)
    return publish_agent_output(
        state,
        "long_document_agent",
        summary,
        f"long_document_addendum_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent", "report_agent"],
    )


def _normalize_url(raw: str) -> str:
    value = str(raw or "").strip()
    while value and value[-1] in {".", ",", ";", ":", ")", "]", "}", "\"", "'"}:
        value = value[:-1]
    return value


def _extract_urls_from_text(text: str) -> list[str]:
    if not str(text or "").strip():
        return []
    matches = re.findall(r"https?://[^\s<>\"]+", text)
    urls: list[str] = []
    for item in matches:
        normalized = _normalize_url(item)
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls


def _extract_urls_from_obj(value: Any, urls: list[str], limit: int = 120) -> None:
    if len(urls) >= limit:
        return
    if isinstance(value, dict):
        for item in value.values():
            _extract_urls_from_obj(item, urls, limit=limit)
            if len(urls) >= limit:
                return
        return
    if isinstance(value, list):
        for item in value:
            _extract_urls_from_obj(item, urls, limit=limit)
            if len(urls) >= limit:
                return
        return
    if isinstance(value, str):
        for url in _extract_urls_from_text(value):
            if url not in urls:
                urls.append(url)
                if len(urls) >= limit:
                    return


def _extract_source_entries(research_pass: dict, *, max_sources: int = 30) -> list[dict]:
    urls: list[str] = []
    _extract_urls_from_obj(research_pass.get("raw"), urls)
    for item in _extract_urls_from_text(str(research_pass.get("output_text", "") or "")):
        if item not in urls:
            urls.append(item)
    entries = []
    for index, url in enumerate(urls[:max_sources], start=1):
        entries.append(
            {
                "id": f"S{index}",
                "url": url,
                "label": _source_label(url),
            }
        )
    return entries


def _source_ledger_markdown(entries: list[dict]) -> str:
    if not entries:
        return "- No externally verifiable URLs were extracted from this section research pass."
    return "\n".join(f"- [{item['id']}] {item['label']} - {item['url']}" for item in entries)


def _references_markdown(entries: list[dict], *, heading: str = "### Verified References", limit: int = 20) -> str:
    lines = [heading, ""]
    if not entries:
        lines.append("- No external references were extracted for this section.")
        return "\n".join(lines).strip()
    for item in entries[:limit]:
        lines.append(f"- [{item['id']}] {item['label']} - {item['url']}")
    return "\n".join(lines).strip()


def _append_verified_references(section_text: str, entries: list[dict]) -> str:
    text = (section_text or "").rstrip()
    references_block = _references_markdown(entries)
    return f"{text}\n\n{references_block}\n"

def _strip_section_references(section_text: str) -> str:
    text = str(section_text or "")
    match = re.search(r"\n#{2,3}\\s+References\\b", text, flags=re.IGNORECASE)
    if match:
        return text[: match.start()].rstrip()
    return text.rstrip()


def _remap_section_citations(section_text: str, section_sources: list[dict], consolidated: list[dict]) -> str:
    url_to_global = {str(item.get("url", "")).strip(): str(item.get("id", "")).strip() for item in consolidated}
    local_map: dict[str, str] = {}
    for item in section_sources:
        local_id = str(item.get("id", "")).strip()
        url = str(item.get("url", "")).strip()
        global_id = url_to_global.get(url)
        if local_id and global_id:
            local_map[local_id] = global_id

    if not local_map:
        return section_text

    def _swap(match: re.Match) -> str:
        local_id = match.group(1)
        return f"[{local_map.get(local_id, local_id)}]"

    # Match any source citation tag of the form [S1], [S12], [P1], etc.
    return re.sub(r"\[([A-Z]\d+)\]", _swap, section_text)


def _consolidate_references(section_outputs: list[dict]) -> list[dict]:
    combined: list[dict] = []
    seen: set[str] = set()
    for section in section_outputs:
        for item in section.get("references", []):
            url = str(item.get("url", "")).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            combined.append({"url": url, "label": str(item.get("label", "")).strip() or _source_label(url)})
    consolidated = []
    for index, item in enumerate(combined, start=1):
        consolidated.append({"id": f"R{index}", "url": item["url"], "label": item["label"]})
    return consolidated


def _extract_mermaid_blocks(text: str) -> list[str]:
    blocks = []
    pattern = re.compile(r"```mermaid\s*(.*?)```", flags=re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(text or ""):
        block = str(match.group(1) or "").strip()
        if block and block not in blocks:
            blocks.append(block)
    return blocks


def _extract_markdown_tables(text: str) -> list[str]:
    lines = (text or "").splitlines()
    tables = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if "|" not in line or line.strip().startswith("```"):
            index += 1
            continue
        start = index
        block = []
        while index < len(lines):
            current = lines[index]
            if "|" not in current or current.strip().startswith("```"):
                break
            block.append(current.rstrip())
            index += 1
        if len(block) >= 2 and re.match(r"^\s*\|?[\s:\-\|]+\|?\s*$", block[1]):
            table = "\n".join(block).strip()
            if table not in tables:
                tables.append(table)
        if index == start:
            index += 1
    return tables


def _generate_visual_assets(section_title: str, section_text: str, research_text: str) -> dict:
    prompt = f"""
You are a technical writing visual-design assistant.

From the section below, decide whether a markdown table and/or mermaid flowchart would improve clarity.
Generate visuals only if they add real value.

Section title:
{section_title}

Section text:
{_trim_text(section_text, 10000)}

Research notes:
{_trim_text(research_text, 9000)}

Return ONLY valid JSON:
{{
  "tables": [
    {{
      "title": "short title",
      "markdown": "| Col A | Col B |\\n|---|---|\\n| ... | ... |"
    }}
  ],
  "flowcharts": [
    {{
      "title": "short title",
      "mermaid": "flowchart TD\\nA --> B"
    }}
  ],
  "notes": "brief note"
}}
"""
    return llm_json(prompt, {"tables": [], "flowcharts": [], "notes": ""})


def _normalize_visual_assets(existing_tables: list[str], existing_flowcharts: list[str], generated: dict) -> dict:
    tables = []
    flowcharts = []

    for index, table_md in enumerate(existing_tables, start=1):
        cleaned = str(table_md or "").strip()
        if not cleaned:
            continue
        tables.append({"title": f"Existing Table {index}", "markdown": cleaned, "source": "existing"})

    for index, mermaid in enumerate(existing_flowcharts, start=1):
        cleaned = str(mermaid or "").strip()
        if not cleaned:
            continue
        flowcharts.append({"title": f"Existing Flowchart {index}", "mermaid": cleaned, "source": "existing"})

    if isinstance(generated, dict):
        for index, item in enumerate(generated.get("tables", []) if isinstance(generated.get("tables", []), list) else [], start=1):
            if not isinstance(item, dict):
                continue
            markdown = str(item.get("markdown", "")).strip()
            if "|" not in markdown or markdown in {entry["markdown"] for entry in tables}:
                continue
            title = str(item.get("title", "")).strip() or f"Generated Table {index}"
            tables.append({"title": title, "markdown": markdown, "source": "generated"})

        for index, item in enumerate(generated.get("flowcharts", []) if isinstance(generated.get("flowcharts", []), list) else [], start=1):
            if not isinstance(item, dict):
                continue
            mermaid = str(item.get("mermaid", "")).strip()
            if not mermaid:
                continue
            lower = mermaid.lower()
            if not (lower.startswith("flowchart") or lower.startswith("graph")):
                continue
            if mermaid in {entry["mermaid"] for entry in flowcharts}:
                continue
            title = str(item.get("title", "")).strip() or f"Generated Flowchart {index}"
            flowcharts.append({"title": title, "mermaid": mermaid, "source": "generated"})

    return {"tables": tables[:4], "flowcharts": flowcharts[:4], "notes": str((generated or {}).get("notes", "")).strip()}


def _render_visual_assets_md(visual_assets: dict) -> str:
    lines = ["### Visual Assets", ""]
    tables = visual_assets.get("tables", [])
    flowcharts = visual_assets.get("flowcharts", [])
    if not tables and not flowcharts:
        lines.append("- No additional visual assets were generated for this section.")
        return "\n".join(lines).strip()

    if tables:
        lines.append("#### Tables")
        lines.append("")
        for item in tables:
            lines.append(f"##### {item.get('title', 'Table')}")
            lines.append("")
            lines.append(str(item.get("markdown", "")).strip())
            lines.append("")

    if flowcharts:
        lines.append("#### Flowcharts")
        lines.append("")
        for item in flowcharts:
            lines.append(f"##### {item.get('title', 'Flowchart')}")
            lines.append("")
            lines.append("```mermaid")
            lines.append(str(item.get("mermaid", "")).strip())
            lines.append("```")
            lines.append("")

    return "\n".join(lines).strip()


def _append_generated_visuals(section_text: str, visual_assets: dict) -> str:
    generated_tables = [item for item in visual_assets.get("tables", []) if item.get("source") == "generated"]
    generated_flowcharts = [item for item in visual_assets.get("flowcharts", []) if item.get("source") == "generated"]

    if not generated_tables and not generated_flowcharts:
        return section_text

    generated_assets = {"tables": generated_tables, "flowcharts": generated_flowcharts}
    rendered = _render_visual_assets_md(generated_assets)
    return f"{section_text.rstrip()}\n\n{rendered}\n"


def _build_visual_index(section_outputs: list[dict]) -> dict:
    entries = []
    for section in section_outputs:
        visual_assets = section.get("visual_assets", {}) if isinstance(section.get("visual_assets"), dict) else {}
        table_count = len(visual_assets.get("tables", []))
        flowchart_count = len(visual_assets.get("flowcharts", []))
        entries.append(
            {
                "section_index": section.get("index"),
                "section_title": section.get("title", ""),
                "tables": table_count,
                "flowcharts": flowchart_count,
                "visual_assets_file": section.get("visual_assets_file", ""),
            }
        )
    return {"entries": entries}


def _visual_index_markdown(visual_index: dict) -> str:
    entries = visual_index.get("entries", []) if isinstance(visual_index, dict) else []
    lines = ["## Visual Asset Index", ""]
    if not entries:
        lines.append("- No visual assets were captured.")
        return "\n".join(lines).strip() + "\n"

    lines.extend(
        [
            "| Section | Tables | Flowcharts | Asset File |",
            "|---|---:|---:|---|",
        ]
    )
    for item in entries:
        section_label = f"{item.get('section_index', '?')}. {str(item.get('section_title', '')).strip() or 'Section'}"
        tables = int(item.get("tables", 0) or 0)
        flowcharts = int(item.get("flowcharts", 0) or 0)
        asset_file = str(item.get("visual_assets_file", "")).strip() or "-"
        lines.append(f"| {section_label} | {tables} | {flowcharts} | {asset_file} |")
    return "\n".join(lines).strip() + "\n"


def _build_outline(objective: str, *, title: str, section_count: int, section_pages: int, subtopics: list[str] | None = None) -> dict:
    subtopic_list = [str(item).strip() for item in (subtopics or []) if str(item).strip()]
    fallback = {
        "title": title,
        "sections": [
            {
                "id": index + 1,
                "title": f"Section {index + 1}",
                "objective": objective,
                "key_questions": [],
                "target_pages": section_pages,
            }
            for index in range(section_count)
        ],
    }
    prompt = f"""
You are planning a deep research report.

Create a coherent section-by-section outline for this objective:
{objective}

Constraints:
- report title: {title}
- sections needed: {section_count}
- target pages per section: about {section_pages}
- preferred subtopics: {subtopic_list or ['Use the objective to derive subtopics']}
- each section must contribute to one coherent final narrative
- avoid overlap; ensure logical progression
- include a methodology / data sources section near the beginning
- place the conclusion last

Return ONLY valid JSON with schema:
{{
  "title": "string",
  "sections": [
    {{
      "id": 1,
      "title": "string",
      "objective": "string",
      "key_questions": ["string"],
      "target_pages": {section_pages}
    }}
  ]
}}
"""
    data = llm_json(prompt, fallback)
    if not isinstance(data, dict):
        return fallback
    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        return fallback
    normalized_sections = []
    for index, section in enumerate(sections[:section_count]):
        if not isinstance(section, dict):
            continue
        questions = section.get("key_questions", [])
        if not isinstance(questions, list):
            questions = []
        normalized_sections.append(
            {
                "id": _safe_int(section.get("id", index + 1), index + 1, 1, 500),
                "title": str(section.get("title", f"Section {index + 1}")).strip() or f"Section {index + 1}",
                "objective": str(section.get("objective", objective)).strip() or objective,
                "key_questions": [str(item).strip() for item in questions if str(item).strip()][:12],
                "target_pages": _safe_int(section.get("target_pages", section_pages), section_pages, 1, 40),
            }
        )
    if not normalized_sections:
        return fallback
    methodology_title = "Methodology and Data Sources"
    conclusion_title = "Conclusion and Implications"
    titles = [str(item.get("title", "")).strip().lower() for item in normalized_sections]
    if methodology_title.lower() not in titles:
        normalized_sections.insert(
            min(1, len(normalized_sections)),
            {
                "id": len(normalized_sections) + 1,
                "title": methodology_title,
                "objective": "Explain the research method, source mix, date range, and evidence quality controls.",
                "key_questions": [],
                "target_pages": section_pages,
            },
        )
    titles = [str(item.get("title", "")).strip().lower() for item in normalized_sections]
    if conclusion_title.lower() not in titles:
        normalized_sections.append(
            {
                "id": len(normalized_sections) + 1,
                "title": conclusion_title,
                "objective": "Synthesize the key findings, limitations, and next-step implications.",
                "key_questions": [],
                "target_pages": section_pages,
            }
        )
    for index, item in enumerate(normalized_sections, start=1):
        item["id"] = index
    while len(normalized_sections) < section_count:
        next_index = len(normalized_sections) + 1
        normalized_sections.append(
            {
                "id": next_index,
                "title": f"Section {next_index}",
                "objective": objective,
                "key_questions": [],
                "target_pages": section_pages,
            }
        )
    return {"title": _normalize_title(data.get("title", ""), title), "sections": normalized_sections}


def _outline_markdown(outline: dict, *, fallback_title: str) -> str:
    lines = [f"# {_normalize_title(outline.get('title', ''), fallback_title)}", "", "## Section Outline"]
    sections = outline.get("sections", []) if isinstance(outline, dict) else []
    for section in sections:
        if not isinstance(section, dict):
            continue
        questions = section.get("key_questions", [])
        question_text = "; ".join(str(item).strip() for item in questions[:6] if str(item).strip()) or "n/a"
        lines.append(
            f"- {section.get('id')}. {section.get('title')}: {section.get('objective')} "
            f"| target_pages={section.get('target_pages')} | questions={question_text}"
        )
    return "\n".join(lines).strip() + "\n"


def _deep_research_analysis_markdown(
    analysis: dict,
    *,
    formats: list[str],
    citation_style: str,
    plagiarism_enabled: bool,
    web_search_enabled: bool,
    local_source_count: int,
    provided_url_count: int,
) -> str:
    budget = analysis.get("budget", {}) if isinstance(analysis, dict) else {}
    lines = [
        "# Deep Research Analysis",
        "",
        f"- Tier: {analysis.get('tier', '?')}",
        f"- Estimated pages: {analysis.get('estimated_pages', '?')}",
        f"- Estimated sources: {analysis.get('estimated_sources', '?')}",
        f"- Estimated duration: {analysis.get('estimated_duration_minutes', '?')} minutes",
        f"- Citation style: {citation_style.upper()}",
        f"- Output formats: {', '.join(fmt.upper() for fmt in formats)}",
        f"- Plagiarism check: {'enabled' if plagiarism_enabled else 'disabled'}",
        f"- Web search: {'enabled' if web_search_enabled else 'disabled'}",
        f"- Local file sources detected: {local_source_count}",
        f"- User-provided URLs: {provided_url_count}",
        f"- Date range: {analysis.get('date_range', 'all_time')}",
        "",
        "## Detected Subtopics",
    ]
    for idx, topic in enumerate(analysis.get("subtopics", []) if isinstance(analysis.get("subtopics", []), list) else [], start=1):
        lines.append(f"- {idx}. {topic}")
    if budget:
        lines.extend(
            [
                "",
                "## Session Budget",
                f"- Max tokens: {budget.get('max_tokens', 0) or 'unlimited'}",
                f"- Max sources: {budget.get('max_sources', 0) or 'unlimited'}",
                f"- Max duration: {budget.get('max_duration_minutes', 0) or 'multi-hour'} minutes",
            ]
        )
    if str(analysis.get("reason", "")).strip():
        lines.extend(["", "## Why this tier", f"- {str(analysis.get('reason', '')).strip()}"])
    return "\n".join(lines).strip() + "\n"


def _build_deep_research_confirmation_prompt(analysis_md: str, *, version: int) -> str:
    return build_plan_approval_prompt(
        analysis_md,
        scope_title=f"deep research confirmation v{version}",
        storage_note="Review the tier, subtopics, and output settings before the expensive research phases begin.",
    )


def _section_text_blocks(text: str) -> list[str]:
    blocks = []
    for part in re.split(r"\n\s*\n", str(text or "").strip()):
        cleaned = part.strip()
        if cleaned:
            blocks.append(cleaned)
    return blocks


def _build_correlation_package(objective: str, section_packages: list[dict]) -> dict:
    section_titles = [str(item.get("title", f"Section {idx}")).strip() or f"Section {idx}" for idx, item in enumerate(section_packages, start=1)]
    fallback = {
        "section_order": section_titles,
        "cross_cutting_themes": [],
        "contradictions": [],
        "briefing": "Use the outline order, avoid overlap, and explicitly cross-reference related sections where evidence intersects.",
    }
    prompt = f"""
You are the subtopic correlation engine for a deep research report.

Objective:
{objective}

Section research packages:
{json.dumps([
    {
        "title": item.get("title", ""),
        "objective": item.get("objective", ""),
        "key_questions": item.get("key_questions", []),
        "research_preview": _trim_text(item.get("research_text", ""), 1800),
        "source_count": len(item.get("sources", []) if isinstance(item.get("sources", []), list) else []),
    }
    for item in section_packages
], indent=2, ensure_ascii=False)}

Return JSON only:
{{
  "section_order": ["title 1", "title 2"],
  "cross_cutting_themes": ["theme 1", "theme 2"],
  "contradictions": ["contradiction 1"],
  "briefing": "500-1000 word editorial briefing for the writer"
}}
"""
    try:
        data = llm_json(prompt, fallback)
    except Exception:
        data = fallback
    if not isinstance(data, dict):
        data = fallback
    raw_order = data.get("section_order", [])
    if not isinstance(raw_order, list):
        raw_order = section_titles
    order: list[str] = []
    seen: set[str] = set()
    title_lookup = {title.lower(): title for title in section_titles}
    for item in raw_order:
        key = str(item).strip().lower()
        resolved = title_lookup.get(key)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        order.append(resolved)
    for title in section_titles:
        if title not in seen:
            order.append(title)
    themes = [str(item).strip() for item in data.get("cross_cutting_themes", []) if str(item).strip()] if isinstance(data.get("cross_cutting_themes", []), list) else []
    contradictions = [str(item).strip() for item in data.get("contradictions", []) if str(item).strip()] if isinstance(data.get("contradictions", []), list) else []
    briefing = str(data.get("briefing", "")).strip() or fallback["briefing"]
    nodes = [{"id": item.get("title", ""), "label": item.get("title", ""), "source_count": len(item.get("sources", []))} for item in section_packages]
    edges = []
    for left, right in zip(order, order[1:]):
        edges.append({"from": left, "to": right, "type": "depends_on", "weight": 0.6})
    if contradictions and len(order) >= 2:
        edges.append({"from": order[0], "to": order[-1], "type": "contradicts", "weight": 0.4, "note": contradictions[0]})
    return {
        "section_order": order,
        "cross_cutting_themes": themes,
        "contradictions": contradictions,
        "briefing": briefing,
        "knowledge_graph": {"nodes": nodes, "edges": edges},
    }


def _ensure_section_citations(section_text: str, section_sources: list[dict]) -> str:
    source_ids = [str(item.get("id", "")).strip() for item in section_sources if str(item.get("id", "")).strip()]
    if not source_ids:
        return section_text.strip()
    default_source = source_ids[0]
    lines = []
    citation_re = re.compile(r"\[[A-Z]\d+\]")
    for raw in str(section_text or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("```") or stripped.startswith("|") or stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\.\s", stripped):
            lines.append(line)
            continue
        if citation_re.search(stripped):
            lines.append(line)
            continue
        lines.append(f"{line} [{default_source}]")
    return "\n".join(lines).strip()


def _tokenize_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _cosine_similarity(left: str, right: str) -> float:
    left_tokens = _tokenize_words(left)
    right_tokens = _tokenize_words(right)
    if not left_tokens or not right_tokens:
        return 0.0
    left_counts: dict[str, int] = {}
    right_counts: dict[str, int] = {}
    for token in left_tokens:
        left_counts[token] = left_counts.get(token, 0) + 1
    for token in right_tokens:
        right_counts[token] = right_counts.get(token, 0) + 1
    numerator = sum(left_counts[token] * right_counts.get(token, 0) for token in left_counts)
    left_norm = math.sqrt(sum(value * value for value in left_counts.values()))
    right_norm = math.sqrt(sum(value * value for value in right_counts.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _ngram_overlap(left: str, right: str, *, n: int = 3) -> float:
    def _ngrams(value: str) -> set[tuple[str, ...]]:
        tokens = _tokenize_words(value)
        if len(tokens) < n:
            return set()
        return {tuple(tokens[idx : idx + n]) for idx in range(0, len(tokens) - n + 1)}

    left_ngrams = _ngrams(left)
    right_ngrams = _ngrams(right)
    if not left_ngrams or not right_ngrams:
        return 0.0
    return len(left_ngrams & right_ngrams) / max(1, len(left_ngrams))


def _estimate_ai_content_score(text: str) -> float:
    tokens = _tokenize_words(text)
    if not tokens:
        return 0.0
    unique_ratio = len(set(tokens)) / max(1, len(tokens))
    sentence_starts = re.findall(r"(?:^|[.!?]\s+)([A-Z][a-z]+)", str(text or ""))
    repeated_start_ratio = 0.0
    if sentence_starts:
        counts: dict[str, int] = {}
        for item in sentence_starts:
            counts[item] = counts.get(item, 0) + 1
        repeated = sum(value for value in counts.values() if value > 1)
        repeated_start_ratio = repeated / max(1, len(sentence_starts))
    citation_density = len(re.findall(r"\[[A-Z]\d+\]", str(text or ""))) / max(1, len(_section_text_blocks(text)))
    score = 55.0 * max(0.0, 0.45 - unique_ratio) + 25.0 * repeated_start_ratio + 8.0 * max(0.0, 1.0 - citation_density)
    return round(max(0.0, min(100.0, score)), 1)


def _build_plagiarism_report(section_outputs: list[dict], source_texts: list[dict]) -> dict:
    source_blocks: list[dict[str, str]] = []
    for item in source_texts:
        label = str(item.get("label", "")).strip() or "source"
        url = str(item.get("url", "")).strip()
        for block in _section_text_blocks(item.get("text", "")):
            if len(block.split()) < 12:
                continue
            source_blocks.append({"label": label, "url": url, "text": block})

    sections_payload = []
    total_paragraphs = 0
    flagged_paragraphs_total = 0
    ai_scores: list[float] = []
    for section in section_outputs:
        flagged = []
        paragraphs = [block for block in _section_text_blocks(section.get("section_text", "")) if len(block.split()) >= 12]
        total_paragraphs += len(paragraphs)
        section_ai = _estimate_ai_content_score(section.get("section_text", ""))
        ai_scores.append(section_ai)
        for paragraph in paragraphs:
            best_match = None
            best_similarity = 0.0
            best_overlap = 0.0
            for source in source_blocks[:250]:
                cosine = _cosine_similarity(paragraph, source["text"])
                overlap = _ngram_overlap(paragraph, source["text"])
                if cosine > best_similarity or overlap > best_overlap:
                    best_similarity = max(best_similarity, cosine)
                    best_overlap = max(best_overlap, overlap)
                    best_match = source
            if best_match and (best_similarity >= 0.85 or best_overlap >= 0.65):
                flagged.append(
                    {
                        "text_excerpt": _trim_text(paragraph, 240),
                        "similarity": round(max(best_similarity, best_overlap), 3),
                        "source_url": best_match.get("url", ""),
                        "type": "near-verbatim" if best_similarity >= 0.85 else "mosaic",
                        "recommendation": "rephrase or add citation",
                    }
                )
        flagged_paragraphs_total += len(flagged)
        section_score = round((len(flagged) / max(1, len(paragraphs))) * 100.0, 1) if paragraphs else 0.0
        sections_payload.append(
            {
                "section_title": section.get("title", ""),
                "plagiarism_score": section_score,
                "ai_score": section_ai,
                "flagged_paragraphs": flagged[:8],
            }
        )
    overall = round((flagged_paragraphs_total / max(1, total_paragraphs)) * 100.0, 1) if total_paragraphs else 0.0
    ai_content = round(sum(ai_scores) / max(1, len(ai_scores)), 1) if ai_scores else 0.0
    status = "PASS" if overall < 10 else "WARN" if overall <= 20 else "FAIL"
    return {
        "overall_score": overall,
        "ai_content_score": ai_content,
        "status": status,
        "sections": sections_payload,
    }


def _format_citation(entry: dict, *, style: str, index: int) -> str:
    label = str(entry.get("label", "Untitled source")).strip() or "Untitled source"
    url = str(entry.get("url", "")).strip()
    access_date = dt.datetime.utcnow().strftime("%Y-%m-%d")
    site = _source_label(url) if url else label
    year_match = re.search(r"(20\d{2}|19\d{2})", label)
    year = year_match.group(1) if year_match else dt.datetime.utcnow().strftime("%Y")
    if style == "mla":
        return f'"{label}." {site}, {year}, {url}. Accessed {access_date}.'.strip()
    if style == "chicago":
        return f'{site}. "{label}." Accessed {access_date}. {url}.'.strip()
    if style == "ieee":
        return f'[{index}] "{label}," {site}, {year}. [Online]. Available: {url}.'.strip()
    if style == "vancouver":
        return f"{index}. {label}. {site}. {year}. Available from: {url}".strip()
    if style == "harvard":
        return f"{site} ({year}) {label}. Available at: {url} (Accessed: {access_date}).".strip()
    return f"{site}. ({year}). {label}. Retrieved {access_date}, from {url}".strip()


def _bibliography_markdown(entries: list[dict], *, style: str) -> str:
    lines = [f"## Bibliography ({style.upper()})", ""]
    if not entries:
        lines.append("- No sources were available for bibliography generation.")
        return "\n".join(lines).strip() + "\n"
    for index, entry in enumerate(entries, start=1):
        citation = _format_citation(entry, style=style, index=index)
        if style in {"ieee", "vancouver"}:
            lines.append(f"- {citation}")
        else:
            lines.append(f"- [R{index}] {citation}")
    return "\n".join(lines).strip() + "\n"


def _plagiarism_report_markdown(report: dict) -> str:
    lines = ["## Appendix B - Plagiarism Report", ""]
    lines.append(f"- Overall plagiarism score: {report.get('overall_score', 0)}%")
    lines.append(f"- AI content score: {report.get('ai_content_score', 0)}%")
    lines.append(f"- Status: {report.get('status', 'PASS')}")
    sections = report.get("sections", []) if isinstance(report, dict) else []
    if not sections:
        lines.append("- No section-level findings.")
        return "\n".join(lines).strip() + "\n"
    for section in sections:
        lines.extend(
            [
                "",
                f"### {section.get('section_title', 'Section')}",
                f"- Plagiarism score: {section.get('plagiarism_score', 0)}%",
                f"- AI score: {section.get('ai_score', 0)}%",
            ]
        )
        flagged = section.get("flagged_paragraphs", []) if isinstance(section, dict) else []
        if not flagged:
            lines.append("- No flagged paragraphs.")
            continue
        for item in flagged[:5]:
            lines.append(
                f"- {item.get('type', 'flagged')}: {item.get('text_excerpt', '')} "
                f"(similarity={item.get('similarity', 0)}, source={item.get('source_url', '')})"
            )
    return "\n".join(lines).strip() + "\n"


def _long_document_subplan(outline: dict, *, objective: str, target_pages: int, research_model: str) -> dict:
    draft_selection = model_selection_for_agent("long_document_agent")
    raw_steps: list[dict[str, Any]] = []
    for index, section in enumerate(outline.get("sections", []) if isinstance(outline, dict) else [], start=1):
        if not isinstance(section, dict):
            continue
        section_title = str(section.get("title", f"Section {index}")).strip() or f"Section {index}"
        section_objective = str(section.get("objective", objective)).strip() or objective
        section_questions = section.get("key_questions", [])
        if not isinstance(section_questions, list):
            section_questions = []
        research_step_id = f"section-{index}-research"
        draft_step_id = f"section-{index}-draft"
        raw_steps.append(
            {
                "id": research_step_id,
                "title": f"Research evidence for {section_title}",
                "agent": "deep_research_agent",
                "task": (
                    f"Collect authoritative evidence, citations, and contradictions for {section_title}. "
                    f"Focus on: {section_objective}. Questions: {section_questions[:6]}"
                ),
                "depends_on": [],
                "parallel_group": "",
                "success_criteria": "Research package is strong enough to support a sourced section draft.",
                "rationale": "Front-load evidence before drafting.",
                "llm_model": research_model,
                "model_source": "state.research_model/OPENAI_DEEP_RESEARCH_MODEL",
                "substeps": [],
            }
        )
        raw_steps.append(
            {
                "id": draft_step_id,
                "title": f"Draft and enrich {section_title}",
                "agent": "long_document_agent",
                "task": (
                    f"Draft {section_title} using the approved outline, recent continuity notes, and gathered research. "
                    "Include citations and visuals when they add clarity."
                ),
                "depends_on": [research_step_id],
                "parallel_group": "",
                "success_criteria": "Section is coherent, cited, and ready to merge into the full document.",
                "rationale": "Convert research into the actual deliverable section.",
                "llm_model": draft_selection.get("model", ""),
                "model_source": draft_selection.get("source", ""),
                "substeps": [],
            }
        )
    raw_steps.append(
        {
            "id": "final-merge",
            "title": "Merge sections and produce deep research artifacts",
            "agent": "long_document_agent",
            "task": "Merge all approved sections into one compiled deep research report with executive summary, references, appendices, and export artifacts.",
            "depends_on": [step["id"] for step in raw_steps if str(step.get("id", "")).endswith("-draft")] or [step["id"] for step in raw_steps],
            "parallel_group": "",
            "success_criteria": "Compiled deep research report, references, plagiarism appendix, and manifest are written to disk.",
            "rationale": "Finish the document only after the section plan has been executed.",
            "llm_model": draft_selection.get("model", ""),
            "model_source": draft_selection.get("source", ""),
            "substeps": [],
        }
    )
    return normalize_plan_data(
        {
            "needs_clarification": False,
            "clarification_questions": [],
            "summary": (
                f"Deliver a {target_pages}-page deep research report through approved section-by-section research, "
                "drafting, and final merge."
            ),
            "steps": raw_steps,
        },
        objective,
    )


def _run_research_pass(
    client: OpenAI,
    *,
    query: str,
    model: str,
    instructions: str,
    max_tool_calls: int,
    max_output_tokens: int | None,
    poll_interval_seconds: int,
    max_wait_seconds: int,
    heartbeat_interval_seconds: int | None = None,
    heartbeat_label: str = "Research pass in progress",
    heartbeat_callback: Any | None = None,
) -> dict:
    create_kwargs = {
        "model": model,
        "input": query,
        "instructions": instructions,
        "background": True,
        "max_tool_calls": max_tool_calls,
        "reasoning": {"summary": "auto"},
        "tools": [{"type": "web_search_preview"}],
    }
    if max_output_tokens is not None and max_output_tokens > 0:
        create_kwargs["max_output_tokens"] = max_output_tokens

    response = client.responses.create(**create_kwargs)
    response_id = response.id
    status = str(getattr(response, "status", "unknown"))
    elapsed_seconds = 0
    terminal = {"completed", "failed", "cancelled", "incomplete"}
    heartbeat_every = int(heartbeat_interval_seconds or 0)
    last_heartbeat = 0

    while status not in terminal:
        if elapsed_seconds >= max_wait_seconds:
            return {
                "response_id": response_id,
                "status": "timeout",
                "elapsed_seconds": elapsed_seconds,
                "output_text": getattr(response, "output_text", "") or "",
                "raw": response.model_dump() if hasattr(response, "model_dump") else {"status": status},
            }
        time.sleep(poll_interval_seconds)
        elapsed_seconds += poll_interval_seconds
        if heartbeat_every > 0 and (elapsed_seconds - last_heartbeat) >= heartbeat_every:
            last_heartbeat = elapsed_seconds
            if heartbeat_label:
                log_task_update(DEEP_RESEARCH_LABEL, f"{heartbeat_label} ({elapsed_seconds}s elapsed).")
            if callable(heartbeat_callback):
                try:
                    heartbeat_callback(elapsed_seconds)
                except Exception:
                    pass
        response = client.responses.retrieve(response_id)
        status = str(getattr(response, "status", "unknown"))

    payload = response.model_dump() if hasattr(response, "model_dump") else {"status": status}
    output_text = getattr(response, "output_text", None) or _extract_output_text(payload)
    return {
        "response_id": response_id,
        "status": status,
        "elapsed_seconds": elapsed_seconds,
        "output_text": output_text or "",
        "raw": payload,
    }


def _format_section_prompt(
    *,
    global_objective: str,
    section: dict,
    section_index: int,
    section_count: int,
    words_target: int,
    continuity_notes: list[str],
    coherence_context_md: str,
    correlation_briefing: str,
    source_ledger_md: str,
    research_text: str,
    evidence_bank_md: str = "",
    citation_style: str = "apa",
    date_range: str = "all_time",
) -> str:
    continuity = "\n".join(f"- {item}" for item in continuity_notes[-8:]) or "- No prior continuity notes."
    key_questions = "\n".join(f"- {item}" for item in section.get("key_questions", [])) or "- None provided."
    return f"""
You are writing Section {section_index} of {section_count} in a deep research report.

Global objective:
{global_objective}

Section title:
{section.get("title", f"Section {section_index}")}

Section objective:
{section.get("objective", global_objective)}

Key questions:
{key_questions}

Continuity constraints from prior sections:
{continuity}

Markdown coherence anchors:
{coherence_context_md}

Extracted source ledger for this section:
{source_ledger_md}

Pre-collected evidence bank (cross-section reference):
{evidence_bank_md or "No evidence bank provided."}

Write a section draft of about {words_target} words.
Requirements:
- Keep conceptual continuity with prior sections.
- Keep factual claims tied to evidence gathered in the research notes below.
- Use the editorial correlation briefing to avoid overlap and to cross-reference related sections.
- Include a short "Section Takeaways" list at the end.
- Use source tags like "[S1]" inline for factual claims that come from the source ledger.
- Do not cite source ids that are not present in the source ledger.
- Do not add a references section; references will be consolidated and renumbered at the end of the document.
- Maintain a formal research tone and write for a deep-research report.
- Cite every factual paragraph.
- Use cross-reference phrasing like "As discussed in Section X..." where genuinely helpful.
- Citation style target for bibliography: {citation_style.upper()}.
- Date range emphasis: {date_range}.

Correlation briefing:
{correlation_briefing}

Research notes:
{research_text}
"""


def _section_continuity_note(section_title: str, section_text: str) -> str:
    prompt = f"""
Summarize this section into continuity notes for later chapters.
Return 6-10 concise bullets, each one line.

Section title: {section_title}
Section text:
{section_text}
"""
    return llm_text(prompt)


def _markdown_to_plain_text(markdown_text: str) -> str:
    lines: list[str] = []
    in_code = False
    for raw in (markdown_text or "").splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            lines.append(line)
            continue
        line = re.sub(r"^#{1,6}\\s+", "", line)
        line = re.sub(r"^[-*]\\s+", "- ", line)
        line = re.sub(r"^\\d+\\.\\s+", "", line)
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    # Best-effort ASCII clean-up for PDF rendering
    cleaned = cleaned.encode("ascii", errors="ignore").decode("ascii")
    return cleaned


def _markdown_to_html(markdown_text: str) -> str:
    lines = (markdown_text or "").splitlines()
    html_lines: list[str] = []
    in_code = False
    in_ul = False
    in_ol = False
    index = 0

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        if in_ol:
            html_lines.append("</ol>")
            in_ol = False

    def render_table(table_lines: list[str]) -> None:
        rows = []
        for row_line in table_lines:
            if not row_line.strip():
                continue
            parts = [cell.strip() for cell in row_line.strip().strip("|").split("|")]
            rows.append(parts)
        if not rows:
            return
        header = rows[0]
        body_rows = rows[2:] if len(rows) > 2 else rows[1:]
        html_lines.append("<table>")
        html_lines.append("<thead><tr>" + "".join(f"<th>{html.escape(cell)}</th>" for cell in header) + "</tr></thead>")
        if body_rows:
            html_lines.append("<tbody>")
            for row in body_rows:
                html_lines.append("<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>")
            html_lines.append("</tbody>")
        html_lines.append("</table>")

    while index < len(lines):
        line = lines[index]
        if line.strip().startswith("```"):
            if in_code:
                html_lines.append("</code></pre>")
                in_code = False
            else:
                close_lists()
                html_lines.append("<pre><code>")
                in_code = True
            index += 1
            continue
        if in_code:
            html_lines.append(html.escape(line))
            index += 1
            continue

        # Table detection (header + separator line)
        if "|" in line and index + 1 < len(lines):
            sep = lines[index + 1]
            if re.match(r"^\\s*\\|?\\s*[:\\-\\s|]+\\|?\\s*$", sep):
                table_block = [line, sep]
                index += 2
                while index < len(lines) and "|" in lines[index] and lines[index].strip():
                    table_block.append(lines[index])
                    index += 1
                close_lists()
                render_table(table_block)
                continue

        heading = re.match(r"^(#{1,6})\\s+(.*)$", line)
        if heading:
            close_lists()
            level = min(len(heading.group(1)), 6)
            html_lines.append(f"<h{level}>{html.escape(heading.group(2).strip())}</h{level}>")
            index += 1
            continue

        ul_item = re.match(r"^[-*]\\s+(.*)$", line)
        if ul_item:
            if not in_ul:
                close_lists()
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{html.escape(ul_item.group(1).strip())}</li>")
            index += 1
            continue

        ol_item = re.match(r"^\\d+\\.\\s+(.*)$", line)
        if ol_item:
            if not in_ol:
                close_lists()
                html_lines.append("<ol>")
                in_ol = True
            html_lines.append(f"<li>{html.escape(ol_item.group(1).strip())}</li>")
            index += 1
            continue

        if not line.strip():
            close_lists()
            html_lines.append("<p></p>")
            index += 1
            continue

        close_lists()
        html_lines.append(f"<p>{html.escape(line.strip())}</p>")
        index += 1

    close_lists()
    if in_code:
        html_lines.append("</code></pre>")

    style = (
        "<style>"
        ":root{color-scheme:light dark;--bg:#ffffff;--text:#111827;--muted:#475569;--line:#dbe4ee;--panel:#f8fafc;}"
        "@media (prefers-color-scheme:dark){:root{--bg:#0f172a;--text:#e2e8f0;--muted:#94a3b8;--line:#334155;--panel:#111827;}}"
        "body{font-family:Georgia,'Times New Roman',serif;line-height:1.6;margin:40px auto;max-width:920px;padding:0 18px;background:var(--bg);color:var(--text);}"
        "h1{font-size:30px;border-bottom:1px solid var(--line);padding-bottom:8px;}"
        "h2{font-size:22px;margin-top:32px;}"
        "h3{font-size:17px;margin-top:22px;}"
        "p{margin:10px 0;}"
        "table{border-collapse:collapse;width:100%;margin:14px 0;background:var(--panel);}"
        "th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top;}"
        "th{background:#0f172a;color:#f8fafc;}"
        "tr:nth-child(even) td{background:rgba(148,163,184,0.08);}"
        "pre{background:var(--panel);padding:12px;border-radius:6px;overflow:auto;border:1px solid var(--line);}"
        "code{font-family:'Courier New',monospace;font-size:0.95em;}"
        "ul,ol{padding-left:22px;}"
        "</style>"
    )
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>Deep Research Report</title>"
        f"{style}</head><body>\n"
        + "\n".join(html_lines)
        + "\n</body></html>"
    )


def _markdown_to_docx(markdown_text: str, output_path: str) -> None:
    if not _ensure_python_package("python-docx", "docx"):
        raise RuntimeError("python-docx not available")
    from docx import Document

    doc = Document()
    in_code = False
    for raw in (markdown_text or "").splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            para = doc.add_paragraph()
            run = para.add_run(line)
            run.font.name = "Courier New"
            continue
        if not line.strip():
            doc.add_paragraph("")
            continue
        heading_match = re.match(r"^(#{1,6})\\s+(.*)$", line)
        if heading_match:
            level = min(len(heading_match.group(1)), 6)
            doc.add_heading(heading_match.group(2).strip(), level=level)
            continue
        if re.match(r"^[-*]\\s+", line):
            doc.add_paragraph(re.sub(r"^[-*]\\s+", "", line), style="List Bullet")
            continue
        if re.match(r"^\\d+\\.\\s+", line):
            doc.add_paragraph(re.sub(r"^\\d+\\.\\s+", "", line), style="List Number")
            continue
        doc.add_paragraph(line)

    doc.save(output_path)


def _ensure_python_package(package: str, import_name: str | None = None) -> bool:
    module_name = import_name or package
    try:
        __import__(module_name)
        return True
    except Exception:
        pass

    log_task_update(DEEP_RESEARCH_LABEL, f"Attempting to install missing dependency: {package}.")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--user",
                "--break-system-packages",
                package,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        log_task_update(DEEP_RESEARCH_LABEL, f"Dependency install failed for {package}: {exc}")
        return False

    try:
        __import__(module_name)
        return True
    except Exception as exc:
        log_task_update(DEEP_RESEARCH_LABEL, f"Dependency import failed for {package} after install: {exc}")
        return False


def _wrap_pdf_lines(text: str, width: int = 92) -> list[str]:
    lines = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(paragraph, width=width) or [""])
    return lines


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _render_pdf_bytes(text: str) -> bytes:
    lines = _wrap_pdf_lines(text)
    page_height = 792
    margin_top = 742
    leading = 14
    lines_per_page = 48
    pages = [lines[i : i + lines_per_page] for i in range(0, max(len(lines), 1), lines_per_page)] or [[]]

    objects: list[bytes] = []

    def add_object(payload: str | bytes) -> int:
        objects.append(payload if isinstance(payload, bytes) else payload.encode("latin-1", errors="replace"))
        return len(objects)

    font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []
    content_ids = []

    for page_lines in pages:
        stream_lines = ["BT", "/F1 11 Tf", f"50 {margin_top} Td"]
        first_line = True
        for line in page_lines:
            escaped_line = _escape_pdf_text(line)
            if first_line:
                stream_lines.append(f"({escaped_line}) Tj")
                first_line = False
            else:
                stream_lines.append(f"0 -{leading} Td")
                stream_lines.append(f"({escaped_line}) Tj")
        if first_line:
            stream_lines.append("( ) Tj")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
        content_id = add_object(
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
        )
        content_ids.append(content_id)
        page_ids.append(add_object(""))

    pages_id = add_object("")
    for idx, page_id in enumerate(page_ids):
        page_object = (
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 {page_height}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_ids[idx]} 0 R >>"
        )
        objects[page_id - 1] = page_object.encode("latin-1")

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode("latin-1")
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    buffer = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(buffer))
        buffer.extend(f"{index} 0 obj\n".encode("ascii"))
        buffer.extend(payload)
        buffer.extend(b"\nendobj\n")

    xref_offset = len(buffer)
    buffer.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buffer.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    buffer.extend(b"trailer\n")
    buffer.extend(f"<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n".encode("ascii"))
    buffer.extend(b"startxref\n")
    buffer.extend(f"{xref_offset}\n".encode("ascii"))
    buffer.extend(b"%%EOF\n")
    return bytes(buffer)


def _export_long_document_formats(
    compiled_markdown: str,
    compiled_filename: str,
    *,
    requested_formats: list[str] | None = None,
) -> dict[str, str]:
    compiled_path = Path(resolve_output_path(compiled_filename))
    base_path = compiled_path.with_suffix("")
    html_path = base_path.with_suffix(".html")
    docx_path = base_path.with_suffix(".docx")
    pdf_path = base_path.with_suffix(".pdf")
    formats = set(_normalize_research_formats(requested_formats or DEFAULT_RESEARCH_FORMATS))

    html_text = _markdown_to_html(compiled_markdown)
    if "html" in formats or "pdf" in formats:
        html_path.write_text(html_text, encoding="utf-8")
    else:
        html_path = Path("")

    if "docx" in formats:
        try:
            _markdown_to_docx(compiled_markdown, str(docx_path))
        except Exception as exc:
            log_task_update(DEEP_RESEARCH_LABEL, f"DOCX export skipped: {exc}")
            docx_path = Path("")
    else:
        docx_path = Path("")

    pdf_written = False
    if "pdf" in formats:
        try:
            if _ensure_python_package("weasyprint"):
                from weasyprint import HTML  # type: ignore

                HTML(string=html_text).write_pdf(str(pdf_path))
                pdf_written = True
            else:
                raise RuntimeError("weasyprint not available")
        except Exception as exc:
            log_task_update(DEEP_RESEARCH_LABEL, f"HTML-to-PDF export unavailable, falling back to text PDF: {exc}")

        if not pdf_written:
            plain_text = _markdown_to_plain_text(compiled_markdown)
            pdf_path.write_bytes(_render_pdf_bytes(plain_text))
    else:
        pdf_path = Path("")

    return {
        "html": str(html_path) if str(html_path) else "",
        "docx": str(docx_path) if str(docx_path) else "",
        "pdf": str(pdf_path) if str(pdf_path) else "",
    }


def _build_compiled_markdown(
    title: str,
    objective: str,
    section_outputs: list[dict],
    executive_summary: str,
    consolidated_references: list[dict],
    *,
    citation_style: str,
    methodology_text: str,
    plagiarism_report: dict,
    source_entries: list[dict],
    research_log_lines: list[str],
    generated_at: str,
    model_name: str,
    deep_research_tier: int,
) -> str:
    escaped_title = title.replace('"', '\\"')
    lines = [
        "---",
        f'title: "{escaped_title}"',
        f"generated_at: {generated_at}",
        f"citation_style: {citation_style}",
        f"deep_research_tier: {deep_research_tier}",
        f"model: {model_name}",
        "---",
        "",
        f"# {title}",
        "",
        f"_Generated by Kendr Deep Research on {generated_at} using {model_name}_",
        "",
        "## Executive Summary",
        executive_summary.strip(),
        "",
        "## Table of Contents",
    ]
    for item in section_outputs:
        lines.append(f"- {item['index']}. {item['title']}")
    lines.append("")
    lines.extend(
        [
            "## Methodology",
            methodology_text.strip(),
            "",
        ]
    )
    for item in section_outputs:
        lines.append(f"## {item['index']}. {item['title']}")
        lines.append("")
        lines.append(item["section_text"].strip())
        lines.append("")
    bibliography_md = _bibliography_markdown(consolidated_references, style=citation_style).strip()
    lines.extend([bibliography_md, ""])
    lines.extend(["## Appendix A - Source List", ""])
    if source_entries:
        for item in source_entries:
            lines.append(f"- [{item.get('id', '')}] {item.get('label', '')} - {item.get('url', '')}")
    else:
        lines.append("- No source list was available.")
    lines.append("")
    lines.append(_plagiarism_report_markdown(plagiarism_report).strip())
    lines.append("")
    lines.extend(["## Appendix C - Research Log", ""])
    if research_log_lines:
        for line in research_log_lines:
            lines.append(f"- {line}")
    else:
        lines.append("- No research log lines were captured.")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def long_document_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "long_document_agent")
    state["long_document_calls"] = state.get("long_document_calls", 0) + 1
    call_number = state["long_document_calls"]

    objective = str(state.get("current_objective") or task_content or state.get("user_query", "")).strip()
    if not objective:
        raise ValueError("long_document_agent requires a non-empty objective.")

    # Ensure long-running document generation has persistent session memory files
    # (including soul.md) available for coherence anchoring.
    soul_file = str(state.get("memory_soul_file", "")).strip()
    if not soul_file or not Path(soul_file).exists():
        state = bootstrap_file_memory(state)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for long_document_agent.")

    target_pages = _safe_int(state.get("long_document_pages") or state.get("report_target_pages"), 50, 5, 500)
    section_pages = _safe_int(state.get("long_document_section_pages"), 5, 2, 20)
    section_count_default = max(3, math.ceil(target_pages / max(1, section_pages)))
    section_count = _safe_int(state.get("long_document_sections"), section_count_default, 1, 40)
    title = _normalize_title(state.get("long_document_title", ""), f"Deep Research Report ({target_pages} pages)")

    research_model = str(state.get("research_model", DEFAULT_DEEP_RESEARCH_MODEL)).strip() or DEFAULT_DEEP_RESEARCH_MODEL
    max_tool_calls = _safe_int(state.get("research_max_tool_calls"), 8, 1, 64)
    max_output_tokens = state.get("research_max_output_tokens")
    max_output_tokens_int = _safe_int(max_output_tokens, 0, 0, 200000) if max_output_tokens is not None else None
    poll_interval_seconds = _safe_int(state.get("research_poll_interval_seconds"), 5, 1, 60)
    max_wait_seconds = _safe_int(state.get("research_max_wait_seconds"), 3600, 60, 86400)
    heartbeat_seconds = _safe_int(state.get("research_heartbeat_seconds"), 120, 30, 3600)
    words_per_page = _safe_int(state.get("long_document_words_per_page"), 250, 150, 700)
    disable_visuals = bool(state.get("long_document_disable_visuals", False))
    include_section_references = bool(state.get("long_document_section_references", False))
    section_search_flag = state.get("long_document_section_search")
    web_search_enabled = bool(state.get("research_web_search_enabled", True))
    use_section_search = web_search_enabled if section_search_flag is None else bool(section_search_flag) and web_search_enabled
    section_search_results_count = _safe_int(state.get("long_document_section_search_results"), 6, 1, 20)
    deep_research_mode = bool(state.get("deep_research_mode", False))
    citation_style = _normalize_citation_style(state.get("research_citation_style", "apa"))
    output_formats = _normalize_research_formats(state.get("research_output_formats", DEFAULT_RESEARCH_FORMATS))
    plagiarism_enabled = bool(state.get("research_enable_plagiarism_check", True))
    date_range = str(state.get("research_date_range", "all_time") or "all_time").strip() or "all_time"
    requested_sources = [str(item).strip().lower() for item in state.get("research_sources", []) if str(item).strip()] if isinstance(state.get("research_sources", []), list) else []
    source_family_display = requested_sources or (["web"] if web_search_enabled else ["local"])
    max_sources = _safe_int(state.get("research_max_sources"), 0, 0, 400)
    checkpoint_enabled = bool(state.get("research_checkpoint_enabled", False))

    research_instructions = str(
        state.get(
            "research_instructions",
            (
                "Perform exhaustive web-grounded research for this section. Favor primary and authoritative sources, "
                "surface disagreements, and avoid unsupported claims."
            ),
        )
    ).strip()

    log_task_update(
        DEEP_RESEARCH_LABEL,
        (
            f"Deep research pass #{call_number} started. target_pages={target_pages}, "
            f"sections={section_count}, section_pages~{section_pages}, model={research_model}, "
            f"formats={','.join(output_formats)}, citation_style={citation_style}"
        ),
        objective,
    )
    _trace_research_event(
        state,
        title="Deep research run started",
        detail=(
            f"Preparing a {target_pages}-page report across about {section_count} sections with "
            f"{citation_style.upper()} citations and {', '.join(output_formats)} exports."
        ),
        status="running",
        metadata={
            "phase": "startup",
            "call_number": call_number,
            "target_pages": target_pages,
            "section_count": section_count,
            "research_model": research_model,
        },
        subtask="Initialize deep research pipeline",
    )

    state["deep_research_mode"] = deep_research_mode
    state["long_document_mode"] = True
    state["research_output_formats"] = output_formats
    state["research_citation_style"] = citation_style
    state["research_enable_plagiarism_check"] = plagiarism_enabled
    state["research_web_search_enabled"] = web_search_enabled
    state["research_date_range"] = date_range
    state["research_checkpoint_enabled"] = checkpoint_enabled
    if max_sources > 0:
        state["research_max_sources"] = max_sources
    state["deep_research_source_urls"] = _normalize_research_urls(state.get("deep_research_source_urls", []))

    collect_sources_first = bool(state.get("long_document_collect_sources_first", True))
    artifact_dir = f"deep_research_runs/deep_research_run_{call_number}"

    if bool(state.get("long_document_addendum_requested", False)):
        return _run_long_document_addendum(
            state,
            objective=objective,
            call_number=call_number,
            artifact_dir=artifact_dir,
        )

    analysis = state.get("deep_research_analysis", {})
    if not isinstance(analysis, dict) or not analysis:
        analysis = _research_depth_analysis(
            objective,
            target_pages=target_pages,
            requested_sources=requested_sources,
            date_range=date_range,
        )
        state["deep_research_analysis"] = analysis
        state["deep_research_tier"] = int(analysis.get("tier", 0) or 0)

    if (
        deep_research_mode
        and bool(analysis.get("requires_deep_research", False))
        and not bool(state.get("deep_research_confirmed", False))
        and not bool(state.get("auto_approve", False))
    ):
        analysis_md = _deep_research_analysis_markdown(
            analysis,
            formats=output_formats,
            citation_style=citation_style,
            plagiarism_enabled=plagiarism_enabled,
            web_search_enabled=web_search_enabled,
            local_source_count=len(_collect_local_drive_evidence(state)),
            provided_url_count=len(_normalize_research_urls(state.get("deep_research_source_urls", []))) if web_search_enabled else 0,
        )
        version = int(state.get("deep_research_confirmation_version", 0) or 0) + 1
        prompt = _build_deep_research_confirmation_prompt(analysis_md, version=version)
        state["deep_research_confirmation_version"] = version
        state["pending_user_input_kind"] = "deep_research_confirmation"
        state["approval_pending_scope"] = "deep_research_confirmation"
        state["pending_user_question"] = prompt
        state["draft_response"] = prompt
        state["deep_research_result_card"] = {
            "kind": "analysis",
            "title": title,
            "tier": analysis.get("tier", 0),
            "estimated_pages": analysis.get("estimated_pages", target_pages),
            "estimated_sources": analysis.get("estimated_sources", 0),
            "estimated_duration_minutes": analysis.get("estimated_duration_minutes", 0),
            "subtopics": analysis.get("subtopics", []),
            "formats": output_formats,
            "citation_style": citation_style,
            "plagiarism_enabled": plagiarism_enabled,
            "web_search_enabled": web_search_enabled,
            "local_sources": len(_collect_local_drive_evidence(state)),
            "provided_urls": len(_normalize_research_urls(state.get("deep_research_source_urls", []))) if web_search_enabled else 0,
            "date_range": date_range,
        }
        update_planning_file(
            state,
            status="awaiting_deep_research_confirmation",
            objective=objective,
            plan_text=state.get("plan", ""),
            clarifications=state.get("plan_clarification_questions", []),
            execution_note="Deep research analysis completed; awaiting confirmation before expensive research starts.",
        )
        log_task_update(DEEP_RESEARCH_LABEL, "Prepared the deep research analysis card for approval.", analysis_md)
        _trace_research_event(
            state,
            title="Deep research analysis prepared",
            detail="Analysis card is ready for approval before the expensive research pipeline starts.",
            status="completed",
            metadata={"phase": "analysis", "requires_confirmation": True, "tier": analysis.get("tier", 0)},
            subtask="Review deep research analysis",
        )
        return publish_agent_output(
            state,
            "long_document_agent",
            analysis_md,
            f"deep_research_analysis_{version}",
            recipients=["orchestrator_agent", "reviewer_agent", "report_agent"],
        )

    if deep_research_mode:
        state["deep_research_confirmed"] = True

    approved_outline = state.get("long_document_outline", {})
    if not isinstance(approved_outline, dict):
        approved_outline = {}
    needs_outline_approval = (
        state.get("long_document_plan_status") != "approved"
        or not approved_outline
        or bool(state.get("long_document_replan_requested", False))
    )

    if needs_outline_approval:
        outline_objective = objective
        feedback = str(state.get("long_document_plan_feedback", "") or "").strip()
        if feedback:
            outline_objective = (
                f"{objective}\n\nUser requested these section-plan changes:\n{feedback}"
            )
        outline = _build_outline(
            outline_objective,
            title=title,
            section_count=section_count,
            section_pages=section_pages,
            subtopics=analysis.get("subtopics", []),
        )
        outline_md = _outline_markdown(outline, fallback_title=title)
        subplan_data = _long_document_subplan(outline, objective=objective, target_pages=target_pages, research_model=research_model)
        subplan_md = outline_md.rstrip() + "\n\n" + plan_as_markdown(subplan_data)
        subplan_version = int(state.get("long_document_plan_version", 0) or 0) + 1

        write_text_file(_artifact_file(artifact_dir, "deep_research_outline.json"), json.dumps(outline, indent=2, ensure_ascii=False))
        write_text_file(_artifact_file(artifact_dir, "deep_research_outline.md"), outline_md)
        write_text_file(_artifact_file(artifact_dir, "deep_research_subplan.json"), json.dumps(subplan_data, indent=2, ensure_ascii=False))
        write_text_file(_artifact_file(artifact_dir, "deep_research_subplan.md"), subplan_md + "\n")

        outline_storage_path = resolve_output_path(_artifact_file(artifact_dir, "deep_research_outline.md"))
        subplan_storage_path = resolve_output_path(_artifact_file(artifact_dir, "deep_research_subplan.md"))
        approval_prompt = build_plan_approval_prompt(
            subplan_md,
            scope_title=f"deep research section plan v{subplan_version}",
            storage_note=f"Stored in {outline_storage_path} and {subplan_storage_path}.",
        )

        state["long_document_outline"] = outline
        state["long_document_plan_data"] = subplan_data
        state["long_document_plan_markdown"] = subplan_md
        state["long_document_plan_version"] = subplan_version
        state["long_document_plan_waiting_for_approval"] = True
        state["long_document_plan_status"] = "pending"
        state["pending_user_input_kind"] = "subplan_approval"
        state["approval_pending_scope"] = "long_document_plan"
        state["pending_user_question"] = approval_prompt
        state["draft_response"] = approval_prompt
        state["_skip_review_once"] = True
        state["_hold_planned_step_completion_once"] = True
        state["long_document_replan_requested"] = False
        state["deep_research_result_card"] = {
            "kind": "plan",
            "title": title,
            "tier": analysis.get("tier", 0),
            "subtopics": analysis.get("subtopics", []),
            "section_count": len(outline.get("sections", [])),
            "formats": output_formats,
            "web_search_enabled": web_search_enabled,
        }

        update_planning_file(
            state,
            status="awaiting_subplan_approval",
            objective=objective,
            plan_text=state.get("plan", ""),
            clarifications=state.get("plan_clarification_questions", []),
            execution_note=f"Deep research subplan v{subplan_version} generated and queued for approval.",
        )
        log_task_update(DEEP_RESEARCH_LABEL, "Prepared a section-by-section deep research plan for approval.", subplan_md)
        _trace_research_event(
            state,
            title="Research section plan prepared",
            detail=f"Generated a section-by-section plan with {len(outline.get('sections', []))} sections and queued it for approval.",
            status="completed",
            metadata={"phase": "planning", "section_count": len(outline.get("sections", [])), "version": subplan_version},
            subtask="Review section plan",
        )
        return publish_agent_output(
            state,
            "long_document_agent",
            subplan_md,
            f"deep_research_subplan_{subplan_version}",
            recipients=["orchestrator_agent", "reviewer_agent", "report_agent"],
        )

    client = OpenAI(api_key=api_key)
    evidence_bank_md = ""
    evidence_sources: list[dict] = []
    evidence_excerpt = ""
    local_entries: list[dict] = _collect_local_drive_evidence(state)
    url_entries: list[dict] = _collect_user_url_evidence(objective, state) if web_search_enabled else []
    explicit_source_entries = _merge_sources(
        _sources_from_local_entries(local_entries),
        _sources_from_url_entries(url_entries),
        max_sources=max_sources or 120,
    )
    if collect_sources_first:
        if not state.get("long_document_sources_collected", False):
            evidence_started_at = _trace_now()
            _trace_research_event(
                state,
                title="Collecting evidence bank",
                detail="Gathering shared sources, contradictions, and benchmarks before section drafting begins.",
                command=objective,
                status="running",
                started_at=evidence_started_at,
                metadata={"phase": "evidence_bank", "web_search_enabled": web_search_enabled},
                subtask="Build cross-report evidence bank",
            )
            log_task_update(DEEP_RESEARCH_LABEL, "Collecting the cross-report evidence bank.")
            if web_search_enabled:
                search_results = _collect_google_search_evidence(objective, num=int(state.get("long_document_search_results", 10) or 10))
                _trace_research_event(
                    state,
                    title="Google search results gathered",
                    detail=f"Cross-report search returned {len((search_results or {}).get('results', []))} result(s).",
                    command=objective,
                    status="completed" if not str((search_results or {}).get("error", "")).strip() else "failed",
                    metadata={
                        "phase": "evidence_bank_search",
                        "search_query": objective,
                        "urls": _trace_url_list([str(item.get("url", "")).strip() for item in (search_results or {}).get("results", [])]),
                    },
                    subtask="Search for shared report evidence",
                )
                evidence_instructions = str(
                    state.get(
                        "long_document_evidence_instructions",
                        (
                            "Collect a comprehensive evidence bank with source-backed facts, contradictions, and benchmarks. "
                            "Prefer primary sources, provide concrete numbers, and include URLs for every major claim."
                        ),
                    )
                ).strip()
                evidence_query_lines = [
                    f"Objective: {objective}",
                    f"Date range preference: {date_range}",
                    f"Requested source families: {source_family_display}",
                    "Local drive rollup summary:",
                    _trim_text(state.get("local_drive_rollup_summary", ""), 2000),
                    "Task: Build a source-backed evidence bank with URLs, disagreements, numbers, and explicit citations.",
                ]
                evidence_pass = _run_research_pass(
                    client,
                    query="\n".join(line for line in evidence_query_lines if str(line).strip()),
                    model=research_model,
                    instructions=evidence_instructions,
                    max_tool_calls=max_tool_calls,
                    max_output_tokens=max_output_tokens_int,
                    poll_interval_seconds=poll_interval_seconds,
                    max_wait_seconds=max_wait_seconds,
                    heartbeat_interval_seconds=heartbeat_seconds,
                    heartbeat_label="Evidence bank research in progress",
                    heartbeat_callback=lambda elapsed: _trace_research_event(
                        state,
                        title="Collecting evidence bank",
                        detail=f"Shared evidence bank research still running ({elapsed}s elapsed).",
                        command=objective,
                        status="running",
                        metadata={"phase": "evidence_bank", "elapsed_seconds": elapsed},
                        subtask="Build cross-report evidence bank",
                    ),
                )
                evidence_sources = _merge_sources(
                    explicit_source_entries,
                    _extract_source_entries(evidence_pass, max_sources=max_sources or 60),
                    max_sources=max_sources or 120,
                )
                evidence_notes_text = str(evidence_pass.get("output_text", "")).strip()
            else:
                search_results = {"results": [], "error": "Web search disabled by user."}
                evidence_pass = {
                    "response_id": "local_only",
                    "status": "local_only",
                    "elapsed_seconds": 0,
                    "output_text": "",
                    "raw": {"reason": "web_search_disabled"},
                }
                evidence_sources = list(explicit_source_entries)
                evidence_notes_text = _build_local_only_research_notes(
                    objective=objective,
                    focus="overall report evidence bank",
                    local_entries=local_entries,
                    url_entries=url_entries,
                )
            evidence_bank_md = _format_evidence_bank_markdown(
                objective=objective,
                local_entries=local_entries,
                url_entries=url_entries,
                search_results=search_results,
                research_notes_text=evidence_notes_text,
                source_ledger=evidence_sources,
                insufficiency_note="" if web_search_enabled else "Web search was disabled. Only local files were used to build this report.",
            )
            evidence_payload = {
                "objective": objective,
                "local_drive_entries": local_entries,
                "provided_url_entries": url_entries,
                "search_results": search_results.get("results", []) if isinstance(search_results, dict) else [],
                "web_research": evidence_pass,
                "source_ledger": evidence_sources,
                "analysis": analysis,
            }
            evidence_md_filename = _artifact_file(artifact_dir, "evidence_bank.md")
            evidence_json_filename = _artifact_file(artifact_dir, "evidence_bank.json")
            write_text_file(evidence_md_filename, evidence_bank_md)
            write_text_file(evidence_json_filename, json.dumps(evidence_payload, indent=2, ensure_ascii=False))
            if url_entries:
                write_text_file(_artifact_file(artifact_dir, "provided_url_sources.json"), json.dumps(url_entries, indent=2, ensure_ascii=False))
            state["long_document_sources_collected"] = True
            state["long_document_evidence_bank_path"] = f"{OUTPUT_DIR}/{evidence_md_filename}"
            state["long_document_evidence_bank_json_path"] = f"{OUTPUT_DIR}/{evidence_json_filename}"
            evidence_excerpt = _trim_text(evidence_bank_md, 18000)
            state["long_document_evidence_bank_excerpt"] = evidence_excerpt
            state["long_document_evidence_sources"] = evidence_sources
            evidence_status = str(evidence_pass.get("status", "")).strip() or "completed"
            evidence_completed = "completed" if evidence_status in {"completed", "local_only", "evidence_bank"} else "failed"
            evidence_detail = (
                f"Evidence bank ready with {len(evidence_sources)} consolidated sources."
                if evidence_completed == "completed"
                else f"Evidence bank finished with status '{evidence_status}'. Partial results will be used."
            )
            _trace_research_event(
                state,
                title="Collecting evidence bank",
                detail=evidence_detail,
                command=objective,
                status=evidence_completed,
                started_at=evidence_started_at,
                completed_at=_trace_now(),
                metadata={
                    "phase": "evidence_bank",
                    "response_status": evidence_status,
                    "sources": len(evidence_sources),
                    "elapsed_seconds": int(evidence_pass.get("elapsed_seconds", 0) or 0),
                    "urls": _trace_url_list([str(item.get("url", "")).strip() for item in evidence_sources]),
                },
                subtask="Build cross-report evidence bank",
            )
        else:
            evidence_bank_md = _read_text_file(state.get("long_document_evidence_bank_path", ""), "")
            evidence_excerpt = state.get("long_document_evidence_bank_excerpt", "") or _trim_text(evidence_bank_md, 18000)
            evidence_sources = state.get("long_document_evidence_sources", []) or []

    outline = approved_outline
    outline_md = _outline_markdown(outline, fallback_title=title)
    write_text_file(_artifact_file(artifact_dir, "deep_research_outline.json"), json.dumps(outline, indent=2, ensure_ascii=False))
    write_text_file(_artifact_file(artifact_dir, "deep_research_outline.md"), outline_md)
    update_planning_file(
        state,
        status="executing",
        objective=objective,
        plan_text=state.get("plan", ""),
        clarifications=state.get("plan_clarification_questions", []),
        execution_note="Deep research plan approved. Executing research, correlation, writing, and verification phases.",
    )

    research_log_lines = [
        f"Tier {analysis.get('tier', 0)} analysis confirmed.",
        f"Target pages: {target_pages}",
        f"Output formats: {', '.join(output_formats)}",
        f"Citation style: {citation_style.upper()}",
        f"Plagiarism check: {'enabled' if plagiarism_enabled else 'disabled'}",
        f"Date range: {date_range}",
    ]

    continuity_notes: list[str] = []
    section_outputs: list[dict] = []
    section_packages: list[dict] = []
    coherence_context_md = _coherence_base_context(state, objective)
    write_text_file(_artifact_file(artifact_dir, "deep_research_coherence_base.md"), coherence_context_md)

    sections = outline.get("sections", []) if isinstance(outline.get("sections", []), list) else []
    total_sections = len(sections)
    for index, section in enumerate(sections, start=1):
        section_title = str(section.get("title", f"Section {index}")).strip() or f"Section {index}"
        section_objective = str(section.get("objective", objective)).strip() or objective
        section_questions = section.get("key_questions", [])
        if not isinstance(section_questions, list):
            section_questions = []
        target_section_pages = _safe_int(section.get("target_pages"), section_pages, 1, 30)

        log_task_update(
            DEEP_RESEARCH_LABEL,
            f"Phase 1/4 - researching section {index}/{total_sections}: {section_title}",
        )
        section_research_started_at = _trace_now()
        _trace_research_event(
            state,
            title=f"Researching section {index}/{total_sections}",
            detail=section_title,
            command=section_objective,
            status="running",
            started_at=section_research_started_at,
            metadata={"phase": "section_research", "section_index": index, "section_title": section_title},
            subtask=f"Gather evidence for {section_title}",
        )

        section_search_results: dict[str, Any] = {}
        section_search_sources: list[dict] = []
        section_search_text = ""
        if use_section_search:
            search_query = f"{section_title} {section_objective}"
            section_search_results = _collect_google_search_evidence(search_query, num=section_search_results_count)
            _trace_research_event(
                state,
                title=f"Google search results for section {index}",
                detail=f"{section_title} returned {len((section_search_results or {}).get('results', []))} result(s).",
                command=search_query,
                status="completed" if not str((section_search_results or {}).get("error", "")).strip() else "failed",
                metadata={
                    "phase": "section_search",
                    "section_index": index,
                    "section_title": section_title,
                    "search_query": search_query,
                    "urls": _trace_url_list([str(item.get("url", "")).strip() for item in (section_search_results or {}).get("results", [])]),
                },
                subtask=f"Search for {section_title}",
            )
            if isinstance(section_search_results, dict) and str(section_search_results.get("error", "")).strip():
                log_task_update(
                    DEEP_RESEARCH_LABEL,
                    f"Section {index} web search error: {section_search_results.get('error')}",
                )
            section_search_sources = _sources_from_search_results(section_search_results.get("results", []))
            section_search_text = _search_results_markdown(section_search_results.get("results", []))

        if collect_sources_first and evidence_excerpt:
            local_section_notes = _build_local_only_research_notes(
                objective=objective,
                focus=f"section {index}: {section_title} — {section_objective}",
                local_entries=local_entries,
                url_entries=url_entries,
                continuity_notes=continuity_notes,
            ) if explicit_source_entries else ""
            research_pass = {
                "response_id": "evidence_bank" if web_search_enabled else f"local_only_section_{index}",
                "status": "evidence_bank" if web_search_enabled else "local_only",
                "elapsed_seconds": 0,
                "output_text": local_section_notes or evidence_excerpt,
                "raw": {"evidence_bank_path": state.get("long_document_evidence_bank_path", "")},
            }
            research_output = local_section_notes or evidence_excerpt
            if section_search_text:
                research_output = f"{section_search_text}\n\n{research_output}"
            section_sources = list(evidence_sources)
            section_sources = _merge_sources(section_sources, section_search_sources)
            source_ledger_md = _source_ledger_markdown(section_sources)
        else:
            local_section_notes = _build_local_only_research_notes(
                objective=objective,
                focus=f"section {index}: {section_title} — {section_objective}",
                local_entries=local_entries,
                url_entries=url_entries,
                continuity_notes=continuity_notes,
            ) if explicit_source_entries else ""
            if web_search_enabled:
                query_lines = [
                    f"Global objective: {objective}",
                    f"Section {index} title: {section_title}",
                    f"Section objective: {section_objective}",
                    "Key questions:",
                    *[f"- {item}" for item in section_questions[:12]],
                    "Continuity notes from previous sections:",
                    *[f"- {item}" for item in continuity_notes[-10:]],
                    "Markdown coherence anchors:",
                    _trim_text(coherence_context_md, 4000),
                ]
                research_pass = _run_research_pass(
                    client,
                    query="\n".join(query_lines),
                    model=research_model,
                    instructions=research_instructions,
                    max_tool_calls=max_tool_calls,
                    max_output_tokens=max_output_tokens_int,
                    poll_interval_seconds=poll_interval_seconds,
                    max_wait_seconds=max_wait_seconds,
                    heartbeat_interval_seconds=heartbeat_seconds,
                    heartbeat_label=f"Section {index} research in progress",
                    heartbeat_callback=lambda elapsed, idx=index, name=section_title: _trace_research_event(
                        state,
                        title=f"Researching section {idx}/{total_sections}",
                        detail=f"{name} still running ({elapsed}s elapsed).",
                        command=section_objective,
                        status="running",
                        metadata={"phase": "section_research", "section_index": idx, "section_title": name, "elapsed_seconds": elapsed},
                        subtask=f"Gather evidence for {name}",
                    ),
                )

                if str(research_pass.get("status", "")).strip() not in {"completed", ""}:
                    log_task_update(
                        DEEP_RESEARCH_LABEL,
                        f"Section {index} research status: {research_pass.get('status')}",
                    )

                research_output = str(research_pass.get("output_text", "")).strip()
            else:
                research_pass = {
                    "response_id": f"local_only_section_{index}",
                    "status": "local_only",
                    "elapsed_seconds": 0,
                    "output_text": local_section_notes,
                    "raw": {"reason": "web_search_disabled"},
                }
                research_output = local_section_notes
            if section_search_text:
                research_output = f"{section_search_text}\n\n{research_output}".strip()
            if not research_output:
                if section_search_text:
                    research_output = section_search_text
                else:
                    research_output = "Research output was empty. Use only explicitly supported claims and call out uncertainty."

            section_sources = _merge_sources(explicit_source_entries, _extract_source_entries(research_pass))
            section_sources = _merge_sources(section_sources, section_search_sources)
            source_ledger_md = _source_ledger_markdown(section_sources)
        if max_sources > 0:
            section_sources = section_sources[:max_sources]
        section_research_status = str(research_pass.get("status", "")).strip() or "completed"
        _trace_research_event(
            state,
            title=f"Researching section {index}/{total_sections}",
            detail=(
                f"{section_title} completed with {len(section_sources)} sources."
                if section_research_status in {"completed", "local_only", "evidence_bank"}
                else f"{section_title} finished with status '{section_research_status}'. Using partial research output."
            ),
            command=section_objective,
            status="completed" if section_research_status in {"completed", "local_only", "evidence_bank"} else "failed",
            started_at=section_research_started_at,
            completed_at=_trace_now(),
            metadata={
                "phase": "section_research",
                "section_index": index,
                "section_title": section_title,
                "response_status": section_research_status,
                "sources": len(section_sources),
                "elapsed_seconds": int(research_pass.get("elapsed_seconds", 0) or 0),
                "search_query": search_query if use_section_search else "",
                "urls": _trace_url_list([str(item.get("url", "")).strip() for item in section_sources]),
            },
            subtask=f"Gather evidence for {section_title}",
        )

        write_text_file(
            _artifact_file(artifact_dir, f"section_{index:02d}/research.json"),
            json.dumps(research_pass, indent=2, ensure_ascii=False),
        )
        write_text_file(_artifact_file(artifact_dir, f"section_{index:02d}/sources.json"), json.dumps(section_sources, indent=2, ensure_ascii=False))
        write_text_file(_artifact_file(artifact_dir, f"section_{index:02d}/sources.md"), _references_markdown(section_sources))
        section_packages.append(
            {
                "index": index,
                "title": section_title,
                "objective": section_objective,
                "key_questions": section_questions,
                "target_pages": target_section_pages,
                "research_pass": research_pass,
                "research_text": research_output,
                "sources": section_sources,
                "source_ledger_md": source_ledger_md,
            }
        )
        research_log_lines.append(f"Researched section {index}: {section_title} ({len(section_sources)} sources)")

    if checkpoint_enabled:
        write_text_file(
            _artifact_file(artifact_dir, "checkpoint_after_research.json"),
            json.dumps({"phase": "research", "sections": section_packages, "analysis": analysis}, indent=2, ensure_ascii=False),
        )

    log_task_update(DEEP_RESEARCH_LABEL, "Phase 2/4 - correlating subtopics and section dependencies.")
    correlation_started_at = _trace_now()
    _trace_research_event(
        state,
        title="Correlating sections",
        detail="Mapping cross-cutting themes, contradictions, and the final section order.",
        status="running",
        started_at=correlation_started_at,
        metadata={"phase": "correlation"},
        subtask="Correlate sections and dependencies",
    )
    correlation = _build_correlation_package(objective, section_packages)
    write_text_file(_artifact_file(artifact_dir, "correlation_briefing.md"), str(correlation.get("briefing", "")).strip() + "\n")
    write_text_file(_artifact_file(artifact_dir, "knowledge_graph.json"), json.dumps(correlation.get("knowledge_graph", {}), indent=2, ensure_ascii=False))
    research_log_lines.append(
        f"Correlation complete: {len(correlation.get('cross_cutting_themes', []))} themes, "
        f"{len(correlation.get('contradictions', []))} contradictions."
    )
    _trace_research_event(
        state,
        title="Correlating sections",
        detail=(
            f"Correlation complete with {len(correlation.get('cross_cutting_themes', []))} themes and "
            f"{len(correlation.get('contradictions', []))} contradictions."
        ),
        status="completed",
        started_at=correlation_started_at,
        completed_at=_trace_now(),
        metadata={
            "phase": "correlation",
            "theme_count": len(correlation.get("cross_cutting_themes", [])),
            "contradiction_count": len(correlation.get("contradictions", [])),
        },
        subtask="Correlate sections and dependencies",
    )

    packages_by_title = {str(item.get("title", "")).strip(): item for item in section_packages}
    ordered_packages = [packages_by_title[title_key] for title_key in correlation.get("section_order", []) if title_key in packages_by_title]
    if len(ordered_packages) != len(section_packages):
        ordered_packages = section_packages

    for write_index, package in enumerate(ordered_packages, start=1):
        section_title = str(package.get("title", f"Section {write_index}")).strip() or f"Section {write_index}"
        words_target = max(500, int(package.get("target_pages", section_pages) or section_pages) * words_per_page)
        log_task_update(
            DEEP_RESEARCH_LABEL,
            f"Phase 3/4 - drafting section {write_index}/{len(ordered_packages)}: {section_title}",
        )
        section_draft_started_at = _trace_now()
        _trace_research_event(
            state,
            title=f"Drafting section {write_index}/{len(ordered_packages)}",
            detail=section_title,
            status="running",
            started_at=section_draft_started_at,
            metadata={"phase": "section_drafting", "section_index": write_index, "section_title": section_title},
            subtask=f"Draft {section_title}",
        )
        section_prompt = _format_section_prompt(
            global_objective=objective,
            section=package,
            section_index=write_index,
            section_count=len(ordered_packages),
            words_target=words_target,
            continuity_notes=continuity_notes,
            coherence_context_md=coherence_context_md,
            correlation_briefing=str(correlation.get("briefing", "")).strip(),
            source_ledger_md=package.get("source_ledger_md", ""),
            research_text=package.get("research_text", ""),
            evidence_bank_md=evidence_excerpt,
            citation_style=citation_style,
            date_range=date_range,
        )
        section_text = llm_text(section_prompt).strip()
        if not section_text:
            section_text = f"## {section_title}\n\nNo section text was generated."
        section_text = _ensure_section_citations(section_text, package.get("sources", []))
        existing_tables = _extract_markdown_tables(section_text)
        existing_flowcharts = _extract_mermaid_blocks(section_text)
        generated_visuals: dict[str, Any] = {"tables": [], "flowcharts": [], "notes": ""}
        if disable_visuals:
            log_task_update(DEEP_RESEARCH_LABEL, f"Skipping visual generation for section {write_index} (disabled).")
        elif not (existing_tables and existing_flowcharts):
            generated_visuals = _generate_visual_assets(section_title, section_text, package.get("research_text", ""))
        visual_assets = _normalize_visual_assets(existing_tables, existing_flowcharts, generated_visuals)
        section_text = _append_generated_visuals(section_text, visual_assets)
        if include_section_references:
            section_text = _append_verified_references(section_text, package.get("sources", []))
        else:
            section_text = _strip_section_references(section_text)

        section_dir = _artifact_file(artifact_dir, f"section_{write_index:02d}")
        section_md_filename = _artifact_file(artifact_dir, f"section_{write_index:02d}/section.md")
        visual_assets_json_filename = _artifact_file(artifact_dir, f"section_{write_index:02d}/visual_assets.json")
        visual_assets_md_filename = _artifact_file(artifact_dir, f"section_{write_index:02d}/visual_assets.md")
        write_text_file(section_md_filename, section_text)
        write_text_file(visual_assets_json_filename, json.dumps(visual_assets, indent=2, ensure_ascii=False))
        write_text_file(visual_assets_md_filename, _render_visual_assets_md(visual_assets) + "\n")
        flowchart_files: list[str] = []
        for chart_index, chart in enumerate(visual_assets.get("flowcharts", []), start=1):
            flowchart_filename = _artifact_file(artifact_dir, f"section_{write_index:02d}/flowchart_{chart_index:02d}.mmd")
            flowchart_text = str(chart.get("mermaid", "")).strip()
            if not flowchart_text:
                continue
            write_text_file(flowchart_filename, flowchart_text + "\n")
            flowchart_files.append(f"{OUTPUT_DIR}/{flowchart_filename}")

        note = _section_continuity_note(section_title, section_text)
        continuity_notes.append(f"{section_title}:\n{note}")
        write_text_file(_artifact_file(artifact_dir, f"section_{write_index:02d}/continuity.txt"), note)
        bridge_md = (
            f"# Section {write_index} Coherence Bridge\n\n"
            f"## Section\n{section_title}\n\n"
            "## Carry-Forward Notes\n"
            f"{note.strip()}\n"
        )
        write_text_file(_artifact_file(artifact_dir, f"section_{write_index:02d}/bridge.md"), bridge_md)
        coherence_context_md = coherence_context_md + "\n\n" + f"[Section {write_index} Bridge]\n" + _trim_text(bridge_md, 2000)
        write_text_file(_artifact_file(artifact_dir, "deep_research_coherence_live.md"), coherence_context_md)

        section_outputs.append(
            {
                "index": write_index,
                "title": section_title,
                "objective": package.get("objective", objective),
                "research_status": str((package.get("research_pass") or {}).get("status", "")),
                "research_response_id": str((package.get("research_pass") or {}).get("response_id", "")),
                "research_elapsed_seconds": int((package.get("research_pass") or {}).get("elapsed_seconds", 0) or 0),
                "research_text_preview": str(package.get("research_text", ""))[:2000],
                "section_text": section_text,
                "continuity_note": note,
                "references": package.get("sources", []),
                "visual_assets": visual_assets,
                "visual_assets_file": f"{OUTPUT_DIR}/{visual_assets_json_filename}",
                "visual_assets_markdown_file": f"{OUTPUT_DIR}/{visual_assets_md_filename}",
                "flowchart_files": flowchart_files,
            }
        )
        research_log_lines.append(f"Drafted section {write_index}: {section_title}")
        state["draft_response"] = (
            f"Deep research in progress: drafted section {write_index}/{len(ordered_packages)} "
            f"({section_title}). Sources this section: {len(package.get('sources', []))}."
        )
        progress_payload = {
            "title": title,
            "objective": objective,
            "target_pages": target_pages,
            "completed_sections": write_index,
            "total_sections": len(ordered_packages),
            "tier": analysis.get("tier", 0),
            "phase": "writing",
            "sections": [
                {
                    "index": item["index"],
                    "title": item["title"],
                    "research_status": item["research_status"],
                    "references_count": len(item.get("references", [])),
                    "table_count": len((item.get("visual_assets") or {}).get("tables", [])),
                    "flowchart_count": len((item.get("visual_assets") or {}).get("flowcharts", [])),
                }
                for item in section_outputs
            ],
        }
        write_text_file(_artifact_file(artifact_dir, "deep_research_progress.json"), json.dumps(progress_payload, indent=2, ensure_ascii=False))
        _trace_research_event(
            state,
            title=f"Drafting section {write_index}/{len(ordered_packages)}",
            detail=(
                f"{section_title} drafted with {len(package.get('sources', []))} sources, "
                f"{len((visual_assets or {}).get('tables', []))} tables, and "
                f"{len((visual_assets or {}).get('flowcharts', []))} flowcharts."
            ),
            status="completed",
            started_at=section_draft_started_at,
            completed_at=_trace_now(),
            metadata={
                "phase": "section_drafting",
                "section_index": write_index,
                "section_title": section_title,
                "source_count": len(package.get("sources", [])),
                "table_count": len((visual_assets or {}).get("tables", [])),
                "flowchart_count": len((visual_assets or {}).get("flowcharts", [])),
            },
            subtask=f"Draft {section_title}",
        )

    if checkpoint_enabled:
        write_text_file(
            _artifact_file(artifact_dir, "checkpoint_after_writing.json"),
            json.dumps({"phase": "writing", "sections": section_outputs}, indent=2, ensure_ascii=False),
        )

    summary_prompt = f"""
Create a concise executive summary for this deep research report.
Objective:
{objective}

Section continuity notes:
{json.dumps(continuity_notes, indent=2, ensure_ascii=False)}
"""
    executive_summary = llm_text(summary_prompt).strip()
    if not executive_summary:
        executive_summary = "Executive summary was not generated."

    consolidated_references = _consolidate_references(section_outputs)
    if not include_section_references:
        for item in section_outputs:
            item["section_text"] = _remap_section_citations(
                item.get("section_text", ""),
                item.get("references", []),
                consolidated_references,
            )
    references_md_filename = _artifact_file(artifact_dir, "deep_research_references.md")
    references_json_filename = _artifact_file(artifact_dir, "deep_research_references.json")
    write_text_file(references_md_filename, _bibliography_markdown(consolidated_references, style=citation_style))
    write_text_file(references_json_filename, json.dumps(consolidated_references, indent=2, ensure_ascii=False))
    visual_index = _build_visual_index(section_outputs)
    visual_index_json_filename = _artifact_file(artifact_dir, "deep_research_visual_index.json")
    visual_index_md_filename = _artifact_file(artifact_dir, "deep_research_visual_index.md")
    write_text_file(visual_index_json_filename, json.dumps(visual_index, indent=2, ensure_ascii=False))
    write_text_file(visual_index_md_filename, _visual_index_markdown(visual_index))

    methodology_lines = [
        f"- Research tier: {analysis.get('tier', 0)}",
        f"- Requested page target: {target_pages}",
        f"- Citation style: {citation_style.upper()}",
        f"- Web search: {'enabled' if web_search_enabled else 'disabled'}",
        f"- Date range: {date_range}",
        f"- Source families requested: {', '.join(source_family_display)}",
        f"- Local file sources: {len(local_entries)}",
        f"- Explicit URL sources: {len(url_entries)}",
        f"- Evidence bank pre-collection: {'enabled' if collect_sources_first else 'disabled'}",
        f"- Section search support: {'enabled' if use_section_search else 'disabled'}",
        f"- Cross-cutting themes identified: {len(correlation.get('cross_cutting_themes', []))}",
        f"- Contradictions identified: {len(correlation.get('contradictions', []))}",
    ]
    methodology_text = "\n".join(methodology_lines)

    plagiarism_sources = [{"label": "Evidence bank", "url": "", "text": evidence_bank_md}]
    for package in section_packages:
        plagiarism_sources.append(
            {
                "label": str(package.get("title", "")).strip() or "Section research",
                "url": "",
                "text": str(package.get("research_text", "")).strip(),
            }
        )
    plagiarism_report = (
        _build_plagiarism_report(section_outputs, plagiarism_sources)
        if plagiarism_enabled
        else {"overall_score": 0.0, "ai_content_score": 0.0, "status": "PASS", "sections": []}
    )
    plagiarism_json_filename = _artifact_file(artifact_dir, "plagiarism_report.json")
    plagiarism_md_filename = _artifact_file(artifact_dir, "plagiarism_report.md")
    write_text_file(plagiarism_json_filename, json.dumps(plagiarism_report, indent=2, ensure_ascii=False))
    write_text_file(plagiarism_md_filename, _plagiarism_report_markdown(plagiarism_report))

    compiled_markdown = _build_compiled_markdown(
        title,
        objective,
        section_outputs,
        executive_summary,
        consolidated_references,
        citation_style=citation_style,
        methodology_text=methodology_text,
        plagiarism_report=plagiarism_report,
        source_entries=consolidated_references,
        research_log_lines=research_log_lines,
        generated_at=dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        model_name=research_model,
        deep_research_tier=int(analysis.get("tier", 0) or 0),
    )
    compiled_filename = _artifact_file(artifact_dir, "deep_research_report.md")
    write_text_file(compiled_filename, compiled_markdown)
    export_paths: dict[str, str] = {}
    compile_started_at = _trace_now()
    _trace_research_event(
        state,
        title="Compiling final report",
        detail="Merging sections, references, plagiarism appendix, and export artifacts.",
        status="running",
        started_at=compile_started_at,
        metadata={"phase": "compile"},
        subtask="Compile and export final report",
    )
    try:
        export_paths = _export_long_document_formats(compiled_markdown, compiled_filename, requested_formats=output_formats)
    except Exception as exc:
        log_task_update(DEEP_RESEARCH_LABEL, f"Format export failed: {exc}")
    manifest_filename = _artifact_file(artifact_dir, "deep_research_manifest.json")
    write_text_file(
        manifest_filename,
        json.dumps(
            {
                "title": title,
                "objective": objective,
                "tier": analysis.get("tier", 0),
                "target_pages": target_pages,
                "section_count": len(section_outputs),
                "compiled_markdown_file": f"{OUTPUT_DIR}/{compiled_filename}",
                "outline_file": f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'deep_research_outline.json')}",
                "outline_markdown_file": f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'deep_research_outline.md')}",
                "coherence_base_file": f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'deep_research_coherence_base.md')}",
                "coherence_live_file": f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'deep_research_coherence_live.md')}",
                "correlation_briefing_file": f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'correlation_briefing.md')}",
                "knowledge_graph_file": f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'knowledge_graph.json')}",
                "references_markdown_file": f"{OUTPUT_DIR}/{references_md_filename}",
                "references_json_file": f"{OUTPUT_DIR}/{references_json_filename}",
                "visual_index_markdown_file": f"{OUTPUT_DIR}/{visual_index_md_filename}",
                "visual_index_json_file": f"{OUTPUT_DIR}/{visual_index_json_filename}",
                "plagiarism_report_json": f"{OUTPUT_DIR}/{plagiarism_json_filename}",
                "plagiarism_report_markdown": f"{OUTPUT_DIR}/{plagiarism_md_filename}",
                "compiled_html_file": export_paths.get("html", ""),
                "compiled_docx_file": export_paths.get("docx", ""),
                "compiled_pdf_file": export_paths.get("pdf", ""),
                "evidence_bank_file": state.get("long_document_evidence_bank_path", ""),
                "evidence_bank_json_file": state.get("long_document_evidence_bank_json_path", ""),
            },
            indent=2,
            ensure_ascii=False,
        ),
    )

    total_tables = sum(len((item.get("visual_assets") or {}).get("tables", [])) for item in section_outputs)
    total_flowcharts = sum(len((item.get("visual_assets") or {}).get("flowcharts", [])) for item in section_outputs)
    total_words = sum(len(str(item.get("section_text", "")).split()) for item in section_outputs) + len(str(executive_summary).split())
    total_sources = len(consolidated_references)

    final_summary = (
        f"Deep research pipeline completed.\n"
        f"- Title: {title}\n"
        f"- Tier: {analysis.get('tier', 0)}\n"
        f"- Target pages: {target_pages}\n"
        f"- Sections produced: {len(section_outputs)}\n"
        f"- Words: {total_words}\n"
        f"- Sources: {total_sources}\n"
        f"- Web search: {'enabled' if web_search_enabled else 'disabled'}\n"
        f"- Local file sources: {len(local_entries)}\n"
        f"- Explicit URL sources: {len(url_entries)}\n"
        f"- Citations: {len(consolidated_references)}\n"
        f"- Plagiarism: {plagiarism_report.get('overall_score', 0)}% ({plagiarism_report.get('status', 'PASS')})\n"
        f"- Compiled markdown: {OUTPUT_DIR}/{compiled_filename}\n"
        f"- Compiled HTML: {export_paths.get('html', 'n/a') or 'n/a'}\n"
        f"- Compiled DOCX: {export_paths.get('docx', 'n/a') or 'n/a'}\n"
        f"- Compiled PDF: {export_paths.get('pdf', 'n/a') or 'n/a'}\n"
        f"- References: {OUTPUT_DIR}/{references_md_filename}\n"
        f"- Visual index: {OUTPUT_DIR}/{visual_index_md_filename}\n"
        f"- Plagiarism report: {OUTPUT_DIR}/{plagiarism_json_filename}\n"
        f"- Evidence bank: {state.get('long_document_evidence_bank_path', 'n/a')}\n"
        f"- Visual assets generated: {total_tables} tables, {total_flowcharts} flowcharts\n"
        f"- Manifest: {OUTPUT_DIR}/{manifest_filename}\n"
        "\nExecutive summary:\n"
        f"{_trim_text(executive_summary, 1800)}\n"
    )

    state["long_document_mode"] = True
    state["deep_research_mode"] = deep_research_mode
    state["deep_research_confirmed"] = deep_research_mode or bool(state.get("deep_research_confirmed", False))
    state["deep_research_tier"] = int(analysis.get("tier", 0) or 0)
    state["long_document_title"] = title
    state["long_document_outline"] = outline
    state["long_document_sections_data"] = [
        {
            "index": item["index"],
            "title": item["title"],
            "objective": item["objective"],
            "research_status": item["research_status"],
            "research_response_id": item["research_response_id"],
            "research_elapsed_seconds": item["research_elapsed_seconds"],
            "continuity_note": item["continuity_note"],
            "references_count": len(item.get("references", [])),
            "table_count": len((item.get("visual_assets") or {}).get("tables", [])),
            "flowchart_count": len((item.get("visual_assets") or {}).get("flowcharts", [])),
            "visual_assets_file": item.get("visual_assets_file", ""),
            "visual_assets_markdown_file": item.get("visual_assets_markdown_file", ""),
            "flowchart_files": item.get("flowchart_files", []),
        }
        for item in section_outputs
    ]
    state["long_document_artifact_dir"] = f"{OUTPUT_DIR}/{artifact_dir}"
    state["long_document_compiled_path"] = f"{OUTPUT_DIR}/{compiled_filename}"
    state["long_document_compiled_html_path"] = export_paths.get("html", "")
    state["long_document_compiled_docx_path"] = export_paths.get("docx", "")
    state["long_document_compiled_pdf_path"] = export_paths.get("pdf", "")
    state["long_document_manifest_path"] = f"{OUTPUT_DIR}/{manifest_filename}"
    state["long_document_outline_md_path"] = f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'deep_research_outline.md')}"
    state["long_document_coherence_base_path"] = f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'deep_research_coherence_base.md')}"
    state["long_document_coherence_live_path"] = f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'deep_research_coherence_live.md')}"
    state["long_document_references_path"] = f"{OUTPUT_DIR}/{references_md_filename}"
    state["long_document_references_json_path"] = f"{OUTPUT_DIR}/{references_json_filename}"
    state["long_document_references"] = consolidated_references
    state["long_document_visual_index_path"] = f"{OUTPUT_DIR}/{visual_index_md_filename}"
    state["long_document_visual_index_json_path"] = f"{OUTPUT_DIR}/{visual_index_json_filename}"
    state["long_document_summary"] = executive_summary
    state["deep_research_analysis"] = analysis
    state["deep_research_result_card"] = {
        "kind": "result",
        "title": title,
        "tier": analysis.get("tier", 0),
        "pages": target_pages,
        "words": total_words,
        "sources": total_sources,
        "citations": len(consolidated_references),
        "plagiarism_score": plagiarism_report.get("overall_score", 0),
        "plagiarism_status": plagiarism_report.get("status", "PASS"),
        "ai_content_score": plagiarism_report.get("ai_content_score", 0),
        "duration_minutes": int(sum(int((item.get("research_elapsed_seconds") or 0)) for item in section_outputs) / 60),
        "web_search_enabled": web_search_enabled,
        "local_sources": len(local_entries),
        "provided_urls": len(url_entries),
        "formats": output_formats,
        "report_path": f"{OUTPUT_DIR}/{compiled_filename}",
        "html_path": export_paths.get("html", ""),
        "docx_path": export_paths.get("docx", ""),
        "pdf_path": export_paths.get("pdf", ""),
        "knowledge_graph_path": f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'knowledge_graph.json')}",
        "plagiarism_report_path": f"{OUTPUT_DIR}/{plagiarism_json_filename}",
        "raw_json_path": f"{OUTPUT_DIR}/{manifest_filename}",
    }
    state["draft_response"] = final_summary
    _trace_research_event(
        state,
        title="Compiling final report",
        detail=(
            f"Final report ready with {len(section_outputs)} sections, {total_sources} sources, and "
            f"{', '.join(output_formats)} exports."
        ),
        status="completed",
        started_at=compile_started_at,
        completed_at=_trace_now(),
        metadata={
            "phase": "compile",
            "section_count": len(section_outputs),
            "source_count": total_sources,
            "word_count": total_words,
        },
        subtask="Compile and export final report",
    )

    log_task_update(DEEP_RESEARCH_LABEL, f"Completed deep research pass #{call_number}.", final_summary)
    state = publish_agent_output(
        state,
        "long_document_agent",
        final_summary,
        f"deep_research_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent", "report_agent"],
    )
    return state
