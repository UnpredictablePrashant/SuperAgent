from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.coding_tasks import _extract_output_text
from tasks.research_infra import llm_json, llm_text
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


DEFAULT_DEEP_RESEARCH_MODEL = os.getenv("OPENAI_DEEP_RESEARCH_MODEL", "o4-mini-deep-research")

AGENT_METADATA = {
    "long_document_agent": {
        "description": (
            "Builds exhaustive long-form documents through staged section research, "
            "cross-section coherence memory, and final merge assembly."
        ),
        "skills": ["long-form", "deep-research", "chaptering", "synthesis", "reporting"],
        "input_keys": [
            "current_objective",
            "long_document_mode",
            "long_document_pages",
            "long_document_sections",
            "long_document_section_pages",
            "long_document_title",
            "research_model",
            "research_max_tool_calls",
            "research_max_output_tokens",
            "research_poll_interval_seconds",
            "research_max_wait_seconds",
        ],
        "output_keys": [
            "long_document_title",
            "long_document_outline",
            "long_document_sections_data",
            "long_document_compiled_path",
            "long_document_outline_md_path",
            "long_document_coherence_base_path",
            "long_document_coherence_live_path",
            "long_document_summary",
            "draft_response",
        ],
        "requirements": ["openai"],
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


def _build_outline(objective: str, *, title: str, section_count: int, section_pages: int) -> dict:
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
You are planning a long-form research monograph.

Create a coherent section-by-section outline for this objective:
{objective}

Constraints:
- report title: {title}
- sections needed: {section_count}
- target pages per section: about {section_pages}
- each section must contribute to one coherent final narrative
- avoid overlap; ensure logical progression

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
    research_text: str,
) -> str:
    continuity = "\n".join(f"- {item}" for item in continuity_notes[-8:]) or "- No prior continuity notes."
    key_questions = "\n".join(f"- {item}" for item in section.get("key_questions", [])) or "- None provided."
    return f"""
You are writing Section {section_index} of {section_count} in a long-form research document.

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

Write a section draft of about {words_target} words.
Requirements:
- Keep conceptual continuity with prior sections.
- Keep factual claims tied to evidence gathered in the research notes below.
- Include a short "Section Takeaways" list at the end.
- Use concise inline source attributions like "(Source: ...)" for key factual claims.

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


def _build_compiled_markdown(title: str, objective: str, section_outputs: list[dict], executive_summary: str) -> str:
    lines = [f"# {title}", "", "## Objective", objective, "", "## Executive Summary", executive_summary.strip(), "", "## Table of Contents"]
    for item in section_outputs:
        lines.append(f"- {item['index']}. {item['title']}")
    lines.append("")
    for item in section_outputs:
        lines.append(f"## {item['index']}. {item['title']}")
        lines.append("")
        lines.append(item["section_text"].strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def long_document_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "long_document_agent")
    state["long_document_calls"] = state.get("long_document_calls", 0) + 1
    call_number = state["long_document_calls"]

    objective = str(state.get("current_objective") or task_content or state.get("user_query", "")).strip()
    if not objective:
        raise ValueError("long_document_agent requires a non-empty objective.")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for long_document_agent.")

    target_pages = _safe_int(state.get("long_document_pages") or state.get("report_target_pages"), 50, 5, 500)
    section_pages = _safe_int(state.get("long_document_section_pages"), 5, 2, 20)
    section_count_default = max(3, math.ceil(target_pages / max(1, section_pages)))
    section_count = _safe_int(state.get("long_document_sections"), section_count_default, 1, 40)
    title = _normalize_title(state.get("long_document_title", ""), f"Long-Form Research Report ({target_pages} pages)")

    research_model = str(state.get("research_model", DEFAULT_DEEP_RESEARCH_MODEL)).strip() or DEFAULT_DEEP_RESEARCH_MODEL
    max_tool_calls = _safe_int(state.get("research_max_tool_calls"), 8, 1, 64)
    max_output_tokens = state.get("research_max_output_tokens")
    max_output_tokens_int = _safe_int(max_output_tokens, 0, 0, 200000) if max_output_tokens is not None else None
    poll_interval_seconds = _safe_int(state.get("research_poll_interval_seconds"), 5, 1, 60)
    max_wait_seconds = _safe_int(state.get("research_max_wait_seconds"), 3600, 60, 86400)
    words_per_page = _safe_int(state.get("long_document_words_per_page"), 420, 250, 700)

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
        "Long Document",
        (
            f"Long-document pass #{call_number} started. target_pages={target_pages}, "
            f"sections={section_count}, section_pages~{section_pages}, model={research_model}"
        ),
        objective,
    )

    outline = _build_outline(objective, title=title, section_count=section_count, section_pages=section_pages)
    write_text_file(f"long_document_outline_{call_number}.json", json.dumps(outline, indent=2, ensure_ascii=False))
    outline_md = [f"# {outline.get('title', title)}", "", "## Outline"]
    for section in outline.get("sections", []):
        outline_md.append(f"- {section.get('id')}. {section.get('title')}: {section.get('objective')}")
    write_text_file(f"long_document_outline_{call_number}.md", "\n".join(outline_md).strip() + "\n")

    client = OpenAI(api_key=api_key)
    continuity_notes: list[str] = []
    section_outputs: list[dict] = []
    coherence_context_md = _coherence_base_context(state, objective)
    write_text_file(f"long_document_coherence_base_{call_number}.md", coherence_context_md)

    for index, section in enumerate(outline.get("sections", []), start=1):
        section_title = str(section.get("title", f"Section {index}")).strip() or f"Section {index}"
        section_objective = str(section.get("objective", objective)).strip() or objective
        section_questions = section.get("key_questions", [])
        if not isinstance(section_questions, list):
            section_questions = []
        target_section_pages = _safe_int(section.get("target_pages"), section_pages, 1, 30)
        words_target = max(500, target_section_pages * words_per_page)

        log_task_update(
            "Long Document",
            f"Researching section {index}/{len(outline.get('sections', []))}: {section_title}",
        )

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
        )

        research_output = str(research_pass.get("output_text", "")).strip()
        if not research_output:
            research_output = "Research output was empty. Use only explicitly supported claims and call out uncertainty."

        write_text_file(
            f"long_document_section_{index:02d}_research_{call_number}.json",
            json.dumps(research_pass, indent=2, ensure_ascii=False),
        )

        section_prompt = _format_section_prompt(
            global_objective=objective,
            section=section,
            section_index=index,
            section_count=len(outline.get("sections", [])),
            words_target=words_target,
            continuity_notes=continuity_notes,
            coherence_context_md=coherence_context_md,
            research_text=research_output,
        )
        section_text = llm_text(section_prompt).strip()
        if not section_text:
            section_text = f"{section_title}\n\nNo section text was generated."

        write_text_file(f"long_document_section_{index:02d}_{call_number}.md", section_text)

        note = _section_continuity_note(section_title, section_text)
        continuity_notes.append(f"{section_title}:\n{note}")
        write_text_file(f"long_document_section_{index:02d}_continuity_{call_number}.txt", note)
        bridge_md = (
            f"# Section {index} Coherence Bridge\n\n"
            f"## Section\n{section_title}\n\n"
            "## Carry-Forward Notes\n"
            f"{note.strip()}\n"
        )
        write_text_file(f"long_document_section_{index:02d}_bridge_{call_number}.md", bridge_md)
        coherence_context_md = (
            coherence_context_md
            + "\n\n"
            + f"[Section {index} Bridge]\n"
            + _trim_text(bridge_md, 2000)
        )
        write_text_file(f"long_document_coherence_live_{call_number}.md", coherence_context_md)

        section_outputs.append(
            {
                "index": index,
                "title": section_title,
                "objective": section_objective,
                "research_status": str(research_pass.get("status", "")),
                "research_response_id": str(research_pass.get("response_id", "")),
                "research_elapsed_seconds": int(research_pass.get("elapsed_seconds", 0) or 0),
                "research_text_preview": research_output[:2000],
                "section_text": section_text,
                "continuity_note": note,
            }
        )

        progress_payload = {
            "title": title,
            "objective": objective,
            "target_pages": target_pages,
            "completed_sections": index,
            "total_sections": len(outline.get("sections", [])),
            "sections": [
                {
                    "index": item["index"],
                    "title": item["title"],
                    "research_status": item["research_status"],
                    "research_response_id": item["research_response_id"],
                }
                for item in section_outputs
            ],
        }
        write_text_file(f"long_document_progress_{call_number}.json", json.dumps(progress_payload, indent=2, ensure_ascii=False))

    summary_prompt = f"""
Create a concise executive summary for this long-form report.
Objective:
{objective}

Section continuity notes:
{json.dumps(continuity_notes, indent=2, ensure_ascii=False)}
"""
    executive_summary = llm_text(summary_prompt).strip()
    if not executive_summary:
        executive_summary = "Executive summary was not generated."

    compiled_markdown = _build_compiled_markdown(title, objective, section_outputs, executive_summary)
    compiled_filename = f"long_document_compiled_{call_number}.md"
    write_text_file(compiled_filename, compiled_markdown)
    manifest_filename = f"long_document_manifest_{call_number}.json"
    write_text_file(
        manifest_filename,
        json.dumps(
            {
                "title": title,
                "objective": objective,
                "target_pages": target_pages,
                "section_count": len(section_outputs),
                "compiled_markdown_file": f"{OUTPUT_DIR}/{compiled_filename}",
                "outline_file": f"{OUTPUT_DIR}/long_document_outline_{call_number}.json",
                "outline_markdown_file": f"{OUTPUT_DIR}/long_document_outline_{call_number}.md",
                "coherence_base_file": f"{OUTPUT_DIR}/long_document_coherence_base_{call_number}.md",
                "coherence_live_file": f"{OUTPUT_DIR}/long_document_coherence_live_{call_number}.md",
            },
            indent=2,
            ensure_ascii=False,
        ),
    )

    final_summary = (
        f"Long-form document pipeline completed.\n"
        f"- Title: {title}\n"
        f"- Target pages: {target_pages}\n"
        f"- Sections produced: {len(section_outputs)}\n"
        f"- Compiled markdown: {OUTPUT_DIR}/{compiled_filename}\n"
        f"- Manifest: {OUTPUT_DIR}/{manifest_filename}\n"
    )

    state["long_document_mode"] = True
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
        }
        for item in section_outputs
    ]
    state["long_document_compiled_path"] = f"{OUTPUT_DIR}/{compiled_filename}"
    state["long_document_manifest_path"] = f"{OUTPUT_DIR}/{manifest_filename}"
    state["long_document_outline_md_path"] = f"{OUTPUT_DIR}/long_document_outline_{call_number}.md"
    state["long_document_coherence_base_path"] = f"{OUTPUT_DIR}/long_document_coherence_base_{call_number}.md"
    state["long_document_coherence_live_path"] = f"{OUTPUT_DIR}/long_document_coherence_live_{call_number}.md"
    state["long_document_summary"] = executive_summary
    state["draft_response"] = final_summary

    log_task_update("Long Document", f"Completed long-form document pass #{call_number}.", final_summary)
    state = publish_agent_output(
        state,
        "long_document_agent",
        final_summary,
        f"long_document_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent", "report_agent"],
    )
    return state
