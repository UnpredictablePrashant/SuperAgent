from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.coding_tasks import _extract_output_text
from tasks.file_memory import bootstrap_file_memory, update_planning_file
from tasks.planning_tasks import build_plan_approval_prompt, normalize_plan_data, plan_as_markdown
from tasks.research_infra import llm_json, llm_text
from tasks.utils import OUTPUT_DIR, log_task_update, model_selection_for_agent, write_text_file


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
            "long_document_artifact_dir",
            "long_document_compiled_path",
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


def _artifact_file(run_dir: str, filename: str) -> str:
    return f"{run_dir.rstrip('/')}/{filename.lstrip('/')}"


def _source_label(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or "source"
    path = (parsed.path or "/").strip("/")
    if not path:
        return host
    parts = [item for item in path.split("/") if item][:2]
    return f"{host}/{'/'.join(parts)}"


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
            "title": "Merge sections and produce final artifacts",
            "agent": "long_document_agent",
            "task": "Merge all approved sections into one compiled markdown document with executive summary, references, and artifact indexes.",
            "depends_on": [step["id"] for step in raw_steps if str(step.get("id", "")).endswith("-draft")] or [step["id"] for step in raw_steps],
            "parallel_group": "",
            "success_criteria": "Compiled long-form document, references, and manifest are written to disk.",
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
                f"Deliver a {target_pages}-page long-form document through approved section-by-section research, "
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
    source_ledger_md: str,
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

Extracted source ledger for this section:
{source_ledger_md}

Write a section draft of about {words_target} words.
Requirements:
- Keep conceptual continuity with prior sections.
- Keep factual claims tied to evidence gathered in the research notes below.
- Include a short "Section Takeaways" list at the end.
- Use source tags like "[S1]" inline for factual claims that come from the source ledger.
- Do not cite source ids that are not present in the source ledger.
- Include a "### References" section at the end with cited source ids and URLs.

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


def _build_compiled_markdown(
    title: str,
    objective: str,
    section_outputs: list[dict],
    executive_summary: str,
    consolidated_references: list[dict],
) -> str:
    lines = [f"# {title}", "", "## Objective", objective, "", "## Executive Summary", executive_summary.strip(), "", "## Table of Contents"]
    for item in section_outputs:
        lines.append(f"- {item['index']}. {item['title']}")
    lines.append("")
    for item in section_outputs:
        lines.append(f"## {item['index']}. {item['title']}")
        lines.append("")
        lines.append(item["section_text"].strip())
        lines.append("")
    lines.append("## Consolidated References")
    lines.append("")
    if consolidated_references:
        for item in consolidated_references:
            lines.append(f"- [{item['id']}] {item['label']} - {item['url']}")
    else:
        lines.append("- No consolidated references were extracted.")
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

    artifact_dir = f"long_document_runs/long_document_run_{call_number}"
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
            outline_objective = f"{objective}\n\nUser requested these section-plan changes:\n{feedback}"
        outline = _build_outline(outline_objective, title=title, section_count=section_count, section_pages=section_pages)
        outline_md = _outline_markdown(outline, fallback_title=title)
        subplan_data = _long_document_subplan(outline, objective=objective, target_pages=target_pages, research_model=research_model)
        subplan_md = outline_md.rstrip() + "\n\n" + plan_as_markdown(subplan_data)
        subplan_version = int(state.get("long_document_plan_version", 0) or 0) + 1

        write_text_file(_artifact_file(artifact_dir, "long_document_outline.json"), json.dumps(outline, indent=2, ensure_ascii=False))
        write_text_file(_artifact_file(artifact_dir, "long_document_outline.md"), outline_md)
        write_text_file(_artifact_file(artifact_dir, "long_document_subplan.json"), json.dumps(subplan_data, indent=2, ensure_ascii=False))
        write_text_file(_artifact_file(artifact_dir, "long_document_subplan.md"), subplan_md + "\n")

        approval_prompt = build_plan_approval_prompt(
            subplan_md,
            scope_title=f"long-document section plan v{subplan_version}",
            storage_note=(
                f"Stored in {OUTPUT_DIR}/{_artifact_file(artifact_dir, 'long_document_outline.md')} and "
                f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'long_document_subplan.md')}."
            ),
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

        update_planning_file(
            state,
            status="awaiting_subplan_approval",
            objective=objective,
            plan_text=state.get("plan", ""),
            clarifications=state.get("plan_clarification_questions", []),
            execution_note=f"Long-document subplan v{subplan_version} generated and queued for approval.",
        )
        log_task_update("Long Document", "Prepared a section-by-section subplan for approval.", subplan_md)
        return publish_agent_output(
            state,
            "long_document_agent",
            subplan_md,
            f"long_document_subplan_{subplan_version}",
            recipients=["orchestrator_agent", "reviewer_agent", "report_agent"],
        )

    outline = approved_outline
    outline_md = _outline_markdown(outline, fallback_title=title)
    write_text_file(_artifact_file(artifact_dir, "long_document_outline.json"), json.dumps(outline, indent=2, ensure_ascii=False))
    write_text_file(_artifact_file(artifact_dir, "long_document_outline.md"), outline_md)
    update_planning_file(
        state,
        status="executing",
        objective=objective,
        plan_text=state.get("plan", ""),
        clarifications=state.get("plan_clarification_questions", []),
        execution_note="Long-document subplan approved. Executing sections one by one.",
    )

    client = OpenAI(api_key=api_key)
    continuity_notes: list[str] = []
    section_outputs: list[dict] = []
    coherence_context_md = _coherence_base_context(state, objective)
    write_text_file(_artifact_file(artifact_dir, "long_document_coherence_base.md"), coherence_context_md)

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

        section_sources = _extract_source_entries(research_pass)
        source_ledger_md = _source_ledger_markdown(section_sources)

        write_text_file(
            _artifact_file(artifact_dir, f"section_{index:02d}/research.json"),
            json.dumps(research_pass, indent=2, ensure_ascii=False),
        )
        write_text_file(_artifact_file(artifact_dir, f"section_{index:02d}/sources.json"), json.dumps(section_sources, indent=2, ensure_ascii=False))
        write_text_file(_artifact_file(artifact_dir, f"section_{index:02d}/sources.md"), _references_markdown(section_sources))

        section_prompt = _format_section_prompt(
            global_objective=objective,
            section=section,
            section_index=index,
            section_count=len(outline.get("sections", [])),
            words_target=words_target,
            continuity_notes=continuity_notes,
            coherence_context_md=coherence_context_md,
            source_ledger_md=source_ledger_md,
            research_text=research_output,
        )
        section_text = llm_text(section_prompt).strip()
        if not section_text:
            section_text = f"{section_title}\n\nNo section text was generated."
        existing_tables = _extract_markdown_tables(section_text)
        existing_flowcharts = _extract_mermaid_blocks(section_text)
        generated_visuals: dict[str, Any] = {"tables": [], "flowcharts": [], "notes": ""}
        if not (existing_tables and existing_flowcharts):
            generated_visuals = _generate_visual_assets(section_title, section_text, research_output)
        visual_assets = _normalize_visual_assets(existing_tables, existing_flowcharts, generated_visuals)
        section_text = _append_generated_visuals(section_text, visual_assets)
        section_text = _append_verified_references(section_text, section_sources)

        section_md_filename = _artifact_file(artifact_dir, f"section_{index:02d}/section.md")
        visual_assets_json_filename = _artifact_file(artifact_dir, f"section_{index:02d}/visual_assets.json")
        visual_assets_md_filename = _artifact_file(artifact_dir, f"section_{index:02d}/visual_assets.md")
        write_text_file(section_md_filename, section_text)
        write_text_file(visual_assets_json_filename, json.dumps(visual_assets, indent=2, ensure_ascii=False))
        write_text_file(visual_assets_md_filename, _render_visual_assets_md(visual_assets) + "\n")
        flowchart_files: list[str] = []
        for chart_index, chart in enumerate(visual_assets.get("flowcharts", []), start=1):
            flowchart_filename = _artifact_file(artifact_dir, f"section_{index:02d}/flowchart_{chart_index:02d}.mmd")
            flowchart_text = str(chart.get("mermaid", "")).strip()
            if not flowchart_text:
                continue
            write_text_file(flowchart_filename, flowchart_text + "\n")
            flowchart_files.append(f"{OUTPUT_DIR}/{flowchart_filename}")

        note = _section_continuity_note(section_title, section_text)
        continuity_notes.append(f"{section_title}:\n{note}")
        write_text_file(_artifact_file(artifact_dir, f"section_{index:02d}/continuity.txt"), note)
        bridge_md = (
            f"# Section {index} Coherence Bridge\n\n"
            f"## Section\n{section_title}\n\n"
            "## Carry-Forward Notes\n"
            f"{note.strip()}\n"
        )
        write_text_file(_artifact_file(artifact_dir, f"section_{index:02d}/bridge.md"), bridge_md)
        coherence_context_md = (
            coherence_context_md
            + "\n\n"
            + f"[Section {index} Bridge]\n"
            + _trim_text(bridge_md, 2000)
        )
        write_text_file(_artifact_file(artifact_dir, "long_document_coherence_live.md"), coherence_context_md)

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
                "references": section_sources,
                "visual_assets": visual_assets,
                "visual_assets_file": f"{OUTPUT_DIR}/{visual_assets_json_filename}",
                "visual_assets_markdown_file": f"{OUTPUT_DIR}/{visual_assets_md_filename}",
                "flowchart_files": flowchart_files,
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
                    "references_count": len(item.get("references", [])),
                    "table_count": len((item.get("visual_assets") or {}).get("tables", [])),
                    "flowchart_count": len((item.get("visual_assets") or {}).get("flowcharts", [])),
                }
                for item in section_outputs
            ],
        }
        write_text_file(_artifact_file(artifact_dir, "long_document_progress.json"), json.dumps(progress_payload, indent=2, ensure_ascii=False))
        state["draft_response"] = (
            f"Long document in progress: completed section {index}/{len(outline.get('sections', []))} "
            f"({section_title}). References extracted this section: {len(section_sources)}. "
            f"Visuals: {len(visual_assets.get('tables', []))} tables, {len(visual_assets.get('flowcharts', []))} flowcharts."
        )

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

    consolidated_references = _consolidate_references(section_outputs)
    references_md_filename = _artifact_file(artifact_dir, "long_document_references.md")
    references_json_filename = _artifact_file(artifact_dir, "long_document_references.json")
    write_text_file(references_md_filename, _references_markdown(consolidated_references, heading="## Consolidated References", limit=200) + "\n")
    write_text_file(references_json_filename, json.dumps(consolidated_references, indent=2, ensure_ascii=False))
    visual_index = _build_visual_index(section_outputs)
    visual_index_json_filename = _artifact_file(artifact_dir, "long_document_visual_index.json")
    visual_index_md_filename = _artifact_file(artifact_dir, "long_document_visual_index.md")
    write_text_file(visual_index_json_filename, json.dumps(visual_index, indent=2, ensure_ascii=False))
    write_text_file(visual_index_md_filename, _visual_index_markdown(visual_index))

    compiled_markdown = _build_compiled_markdown(
        title,
        objective,
        section_outputs,
        executive_summary,
        consolidated_references,
    )
    compiled_filename = _artifact_file(artifact_dir, "long_document_compiled.md")
    write_text_file(compiled_filename, compiled_markdown)
    manifest_filename = _artifact_file(artifact_dir, "long_document_manifest.json")
    write_text_file(
        manifest_filename,
        json.dumps(
            {
                "title": title,
                "objective": objective,
                "target_pages": target_pages,
                "section_count": len(section_outputs),
                "compiled_markdown_file": f"{OUTPUT_DIR}/{compiled_filename}",
                "outline_file": f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'long_document_outline.json')}",
                "outline_markdown_file": f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'long_document_outline.md')}",
                "coherence_base_file": f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'long_document_coherence_base.md')}",
                "coherence_live_file": f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'long_document_coherence_live.md')}",
                "references_markdown_file": f"{OUTPUT_DIR}/{references_md_filename}",
                "references_json_file": f"{OUTPUT_DIR}/{references_json_filename}",
                "visual_index_markdown_file": f"{OUTPUT_DIR}/{visual_index_md_filename}",
                "visual_index_json_file": f"{OUTPUT_DIR}/{visual_index_json_filename}",
            },
            indent=2,
            ensure_ascii=False,
        ),
    )

    total_tables = sum(len((item.get("visual_assets") or {}).get("tables", [])) for item in section_outputs)
    total_flowcharts = sum(len((item.get("visual_assets") or {}).get("flowcharts", [])) for item in section_outputs)

    final_summary = (
        f"Long-form document pipeline completed.\n"
        f"- Title: {title}\n"
        f"- Target pages: {target_pages}\n"
        f"- Sections produced: {len(section_outputs)}\n"
        f"- Compiled markdown: {OUTPUT_DIR}/{compiled_filename}\n"
        f"- References: {OUTPUT_DIR}/{references_md_filename}\n"
        f"- Visual index: {OUTPUT_DIR}/{visual_index_md_filename}\n"
        f"- Visual assets generated: {total_tables} tables, {total_flowcharts} flowcharts\n"
        f"- Manifest: {OUTPUT_DIR}/{manifest_filename}\n"
        "\nExecutive summary:\n"
        f"{_trim_text(executive_summary, 1800)}\n"
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
    state["long_document_manifest_path"] = f"{OUTPUT_DIR}/{manifest_filename}"
    state["long_document_outline_md_path"] = f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'long_document_outline.md')}"
    state["long_document_coherence_base_path"] = f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'long_document_coherence_base.md')}"
    state["long_document_coherence_live_path"] = f"{OUTPUT_DIR}/{_artifact_file(artifact_dir, 'long_document_coherence_live.md')}"
    state["long_document_references_path"] = f"{OUTPUT_DIR}/{references_md_filename}"
    state["long_document_references_json_path"] = f"{OUTPUT_DIR}/{references_json_filename}"
    state["long_document_references"] = consolidated_references
    state["long_document_visual_index_path"] = f"{OUTPUT_DIR}/{visual_index_md_filename}"
    state["long_document_visual_index_json_path"] = f"{OUTPUT_DIR}/{visual_index_json_filename}"
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
