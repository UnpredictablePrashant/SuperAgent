import json
import os
import re
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.research_infra import (
    LOCAL_DRIVE_SUPPORTED_EXTENSIONS,
    build_evidence_bundle,
    chunk_text,
    crawl_urls,
    evidence_text,
    llm_json,
    openai_analyze_image,
    llm_text,
    openai_ocr_image,
    parse_documents,
    search_memory,
    search_result_urls,
    serp_search,
    summarize_pages,
    upsert_memory_records,
)
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


AGENT_METADATA = {
    "local_drive_agent": {
        "description": (
            "Indexes a user-selected local folder, reads supported files one at a time, "
            "builds per-document summaries, and creates a reusable summary bank."
        ),
        "skills": ["local-drive", "document-ingestion", "ocr", "summarization", "knowledge-bank"],
        "input_keys": [
            "local_drive_paths",
            "local_drive_recursive",
            "local_drive_max_files",
            "local_drive_extensions",
            "local_drive_enable_image_ocr",
            "local_drive_ocr_instruction",
            "local_drive_working_directory",
            "current_objective",
        ],
        "output_keys": [
            "local_drive_files",
            "local_drive_documents",
            "local_drive_document_summaries",
            "local_drive_summary_bank",
            "document_summary",
            "draft_response",
        ],
        "requirements": [],
    }
}


def _safe_json_filename(agent_name: str, call_number: int) -> str:
    return f"{agent_name}_{call_number}.json"


def _safe_text_filename(agent_name: str, call_number: int) -> str:
    return f"{agent_name}_{call_number}.txt"


def _write_agent_artifacts(agent_name: str, call_number: int, text_output: str, structured_output=None):
    write_text_file(_safe_text_filename(agent_name, call_number), text_output)
    if structured_output is not None:
        write_text_file(
            _safe_json_filename(agent_name, call_number),
            json.dumps(structured_output, indent=2, ensure_ascii=False),
        )


def _resolve_paths(raw_paths, working_directory: str | None = None) -> list[str]:
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    results = []
    for raw_path in raw_paths or []:
        candidate = str(raw_path or "").strip()
        if not candidate:
            continue
        windows_drive_match = re.match(r"^([a-zA-Z]):[\\/](.*)$", candidate)
        if windows_drive_match:
            drive = windows_drive_match.group(1).lower()
            tail = windows_drive_match.group(2).replace("\\", "/")
            wsl_path = Path(f"/mnt/{drive}/{tail}")
            path = wsl_path if wsl_path.exists() else Path(candidate)
        else:
            path = Path(candidate)
        if not path.is_absolute():
            path = Path(working_directory or ".").resolve() / path
        results.append(str(path))
    return results


def _normalize_extension_set(raw_extensions) -> set[str]:
    if isinstance(raw_extensions, str):
        items = [item.strip() for item in raw_extensions.split(",")]
    elif isinstance(raw_extensions, list):
        items = [str(item).strip() for item in raw_extensions]
    else:
        items = []
    normalized = {f".{item.lower().lstrip('.')}" for item in items if item}
    return normalized or set(LOCAL_DRIVE_SUPPORTED_EXTENSIONS)


def _discover_local_drive_files(
    roots: list[str],
    *,
    recursive: bool,
    include_hidden: bool,
    max_files: int,
    allowed_extensions: set[str],
) -> list[str]:
    discovered = []
    seen = set()
    for root_item in roots:
        root = Path(root_item).expanduser().resolve()
        candidates = []
        if root.is_file():
            candidates = [root]
        elif root.is_dir():
            iterator = root.rglob("*") if recursive else root.glob("*")
            candidates = [path for path in iterator if path.is_file()]
        for path in sorted(candidates):
            if path in seen:
                continue
            if not include_hidden and any(part.startswith(".") for part in path.parts):
                continue
            if path.suffix.lower() not in allowed_extensions:
                continue
            discovered.append(str(path))
            seen.add(path)
            if len(discovered) >= max_files:
                return discovered
    return discovered


def _merge_documents(existing: list[dict], incoming: list[dict]) -> list[dict]:
    by_path = {}
    for item in existing or []:
        if isinstance(item, dict):
            by_path[str(item.get("path", ""))] = item
    for item in incoming or []:
        if isinstance(item, dict):
            by_path[str(item.get("path", ""))] = item
    return [item for key, item in sorted(by_path.items()) if key]


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip()).strip("_").lower()
    return slug[:64] or "document"


def _textual_sources_for_memory(state: dict) -> list[dict]:
    records = []
    for page in state.get("web_crawl_pages", []) or []:
        if page.get("text"):
            for index, chunk in enumerate(chunk_text(page["text"])):
                records.append(
                    {
                        "source": page.get("url", "web"),
                        "text": chunk,
                        "payload": {"source_type": "web_page", "chunk_index": index},
                    }
                )
    for document in state.get("documents", []) or []:
        if document.get("text"):
            for index, chunk in enumerate(chunk_text(document["text"])):
                records.append(
                    {
                        "source": document.get("path", "document"),
                        "text": chunk,
                        "payload": {"source_type": "document", "chunk_index": index},
                    }
                )
    for item in state.get("ocr_results", []) or []:
        if item.get("text"):
            records.append(
                {
                    "source": item.get("path", "ocr"),
                    "text": item["text"],
                    "payload": {"source_type": "ocr"},
                }
            )
    for item in state.get("local_drive_document_summaries", []) or []:
        summary_text = (item or {}).get("summary", "")
        if summary_text:
            records.append(
                {
                    "source": f"{item.get('path', 'document')}#summary",
                    "text": summary_text,
                    "payload": {"source_type": "document_summary", "document_type": item.get("type", "unknown")},
                }
            )
    return records


def _maybe_upsert_memory(state: dict, records: list[dict]):
    try:
        result = upsert_memory_records(records)
        state["memory_index_result"] = result
        return result
    except Exception as exc:
        state["memory_index_error"] = str(exc)
        return {"indexed": 0, "collection": "unavailable", "error": str(exc)}


def _maybe_search_memory(state: dict, query: str, top_k: int = 5) -> list[dict]:
    try:
        return search_memory(query, top_k=top_k)
    except Exception as exc:
        state["memory_search_error"] = str(exc)
        return []


def access_control_agent(state):
    _, task_content, _ = begin_agent_session(state, "access_control_agent")
    state["access_control_calls"] = state.get("access_control_calls", 0) + 1
    call_number = state["access_control_calls"]
    request_text = task_content or state.get("current_objective") or state.get("user_query", "")
    target = state.get("research_target", "")

    prompt = f"""
You are an access control and privacy governance agent for a research system.

Assess whether the requested research is acceptable, what data classes are involved, and what restrictions should apply.

Request:
{request_text}

Target:
{target}

Return ONLY valid JSON:
{{
  "decision": "allow|allow_with_restrictions|deny",
  "risk_level": "low|medium|high",
  "allowed_sources": ["public_web", "documents", "search", "news", "internal_docs"],
  "disallowed_actions": ["example"],
  "redaction_rules": ["example"],
  "reason": "brief explanation"
}}
"""
    result = llm_json(
        prompt,
        {
            "decision": "allow_with_restrictions",
            "risk_level": "medium",
            "allowed_sources": ["public_web", "search", "news", "documents"],
            "disallowed_actions": ["collect highly sensitive personal data"],
            "redaction_rules": ["avoid unnecessary PII"],
            "reason": "Fallback policy applied.",
        },
    )
    summary = (
        f"Decision: {result['decision']}\nRisk: {result['risk_level']}\n"
        f"Allowed Sources: {', '.join(result.get('allowed_sources', []))}\n"
        f"Reason: {result.get('reason', '')}"
    )
    _write_agent_artifacts("access_control_agent", call_number, summary, result)
    state["access_control_report"] = result
    state["draft_response"] = summary
    log_task_update("Access Control", f"Policy pass #{call_number} saved to {OUTPUT_DIR}/access_control_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "access_control_agent",
        summary,
        f"access_control_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )


def web_crawl_agent(state):
    _, task_content, _ = begin_agent_session(state, "web_crawl_agent")
    state["web_crawl_calls"] = state.get("web_crawl_calls", 0) + 1
    call_number = state["web_crawl_calls"]

    urls = list(state.get("crawl_seed_urls") or state.get("urls_to_crawl") or [])
    if not urls and state.get("search_results"):
        urls = search_result_urls(state["search_results"])
    if not urls:
        query = state.get("search_query") or task_content or state.get("current_objective") or state.get("user_query", "")
        if not query:
            raise ValueError("web_crawl_agent needs seed URLs, search results, or a query.")
        search_payload = serp_search(query, num=int(state.get("crawl_search_results", 5)))
        state["crawl_search_results"] = search_payload
        urls = search_result_urls(search_payload)

    max_pages = int(state.get("crawl_max_pages", 5))
    same_domain = bool(state.get("crawl_same_domain", False))

    log_task_update("Web Crawl", f"Crawl pass #{call_number} started.", "\n".join(urls[:max_pages]))
    pages = crawl_urls(urls, max_pages=max_pages, same_domain=same_domain)
    summary = summarize_pages(
        pages,
        state.get("current_objective") or state.get("user_query", ""),
        "research agents inside a multi-agent system",
    )
    _write_agent_artifacts("web_crawl_agent", call_number, summary, pages)
    state["web_crawl_pages"] = pages
    state["web_crawl_summary"] = summary
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "web_crawl_agent",
        summary,
        f"web_crawl_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def document_ingestion_agent(state):
    _, task_content, _ = begin_agent_session(state, "document_ingestion_agent")
    state["document_ingestion_calls"] = state.get("document_ingestion_calls", 0) + 1
    call_number = state["document_ingestion_calls"]

    raw_paths = state.get("document_paths") or state.get("doc_paths") or []
    paths = _resolve_paths(raw_paths, state.get("document_working_directory"))
    if not paths and task_content and Path(task_content).exists():
        paths = [task_content]
    if not paths:
        raise ValueError("document_ingestion_agent requires 'document_paths' or 'doc_paths'.")

    documents = parse_documents(paths)
    prompt = f"""
You are a document ingestion and extraction agent.

Objective:
{state.get("current_objective") or state.get("user_query", "")}

Documents:
{json.dumps(documents, indent=2, ensure_ascii=False)[:25000]}

Summarize the important facts, entities, dates, metrics, and unanswered questions.
"""
    summary = llm_text(prompt)
    _write_agent_artifacts("document_ingestion_agent", call_number, summary, documents)
    state["documents"] = documents
    state["document_summary"] = summary
    state["draft_response"] = summary
    if state.get("document_index_to_memory", True):
        _maybe_upsert_memory(state, _textual_sources_for_memory(state))
    return publish_agent_output(
        state,
        "document_ingestion_agent",
        summary,
        f"document_ingestion_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def local_drive_agent(state):
    _, task_content, _ = begin_agent_session(state, "local_drive_agent")
    state["local_drive_calls"] = state.get("local_drive_calls", 0) + 1
    call_number = state["local_drive_calls"]

    base_directory = state.get("local_drive_working_directory") or state.get("working_directory")
    raw_roots = (
        state.get("local_drive_paths")
        or state.get("knowledge_drive_paths")
        or state.get("drive_paths")
        or state.get("document_root_paths")
        or []
    )
    if not raw_roots and task_content:
        try:
            if Path(task_content).exists():
                raw_roots = [task_content]
        except Exception:
            raw_roots = []
    if not raw_roots and base_directory:
        raw_roots = [base_directory]
    roots = _resolve_paths(raw_roots, base_directory)
    if not roots:
        raise ValueError("local_drive_agent requires 'local_drive_paths' or a valid working_directory.")

    recursive = bool(state.get("local_drive_recursive", True))
    include_hidden = bool(state.get("local_drive_include_hidden", False))
    max_files = max(1, min(int(state.get("local_drive_max_files", 200)), 1000))
    allowed_extensions = _normalize_extension_set(state.get("local_drive_extensions"))
    image_ocr_enabled = bool(state.get("local_drive_enable_image_ocr", True))
    ocr_instruction = state.get("local_drive_ocr_instruction")
    objective = state.get("current_objective") or state.get("user_query", "")

    files = _discover_local_drive_files(
        roots,
        recursive=recursive,
        include_hidden=include_hidden,
        max_files=max_files,
        allowed_extensions=allowed_extensions,
    )
    if not files:
        raise ValueError("local_drive_agent found no supported files in the selected path(s).")

    log_task_update(
        "Local Drive",
        f"Local drive pass #{call_number} started. Processing {len(files)} file(s).",
        "\n".join(files[:20]),
    )

    documents = []
    document_summaries = []
    for index, file_path in enumerate(files, start=1):
        parsed = parse_documents(
            [file_path],
            continue_on_error=True,
            ocr_images=image_ocr_enabled,
            ocr_instruction=ocr_instruction,
        )[0]
        documents.append(parsed)

        parsed_text = str(parsed.get("text", "") or "").strip()
        metadata = parsed.get("metadata", {}) if isinstance(parsed.get("metadata"), dict) else {}
        document_type = str(metadata.get("type", Path(file_path).suffix.lstrip(".").lower() or "unknown"))
        if parsed_text:
            prompt = f"""
You are a document-reading sub-agent.

Task objective:
{objective}

Document path:
{file_path}

Document type:
{document_type}

Extracted content:
{parsed_text[:16000]}

Write a concise summary with:
- what this document is about
- critical facts, numbers, dates, and entities
- decisions or action items
- data quality concerns or missing pieces
"""
            summary = llm_text(prompt)
        else:
            summary = f"No readable text extracted. Reason: {metadata.get('error', 'empty document after extraction')}"

        summary_item = {
            "index": index,
            "path": file_path,
            "file_name": Path(file_path).name,
            "type": document_type,
            "summary": summary,
            "char_count": len(parsed_text),
            "error": metadata.get("error", ""),
        }
        document_summaries.append(summary_item)

        artifact_name = f"local_drive_doc_summary_{call_number}_{index:03d}_{_safe_slug(Path(file_path).stem)}.txt"
        artifact_body = "\n".join(
            [
                f"File: {summary_item['file_name']}",
                f"Path: {summary_item['path']}",
                f"Type: {summary_item['type']}",
                f"Characters: {summary_item['char_count']}",
                f"Error: {summary_item['error'] or 'none'}",
                "",
                summary_item["summary"],
            ]
        )
        write_text_file(artifact_name, artifact_body)

    rollup_input = {
        "objective": objective,
        "document_count": len(document_summaries),
        "documents": [
            {
                "index": item["index"],
                "path": item["path"],
                "type": item["type"],
                "summary": item["summary"],
                "error": item["error"],
            }
            for item in document_summaries
        ],
    }
    rollup_prompt = f"""
You are a knowledge-synthesis agent. Build one actionable summary from these document summaries.

Return:
- 5-10 bullet key findings
- contradictions or missing data
- recommended next tasks for report generation
- list of highest-priority source files to inspect deeper

Input:
{json.dumps(rollup_input, indent=2, ensure_ascii=False)[:28000]}
"""
    rollup_summary = llm_text(rollup_prompt)

    payload = {
        "roots": roots,
        "recursive": recursive,
        "max_files": max_files,
        "allowed_extensions": sorted(allowed_extensions),
        "image_ocr_enabled": image_ocr_enabled,
        "files": files,
        "documents": [
            {
                "path": item.get("path", ""),
                "type": (item.get("metadata") or {}).get("type", ""),
                "char_count": len(item.get("text", "") or ""),
                "error": (item.get("metadata") or {}).get("error", ""),
            }
            for item in documents
        ],
        "document_summaries": document_summaries,
    }
    _write_agent_artifacts("local_drive_agent", call_number, rollup_summary, payload)

    state["local_drive_files"] = files
    state["local_drive_documents"] = documents
    state["local_drive_document_summaries"] = document_summaries
    state["local_drive_summary_bank"] = {item["path"]: item["summary"] for item in document_summaries}
    state["documents"] = _merge_documents(state.get("documents", []), documents)
    state["local_drive_summary"] = rollup_summary
    state["document_summary"] = rollup_summary
    state["draft_response"] = rollup_summary
    if state.get("local_drive_index_to_memory", True):
        _maybe_upsert_memory(state, _textual_sources_for_memory(state))
    return publish_agent_output(
        state,
        "local_drive_agent",
        rollup_summary,
        f"local_drive_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "report_agent"],
    )


def ocr_agent(state):
    _, task_content, _ = begin_agent_session(state, "ocr_agent")
    state["ocr_calls"] = state.get("ocr_calls", 0) + 1
    call_number = state["ocr_calls"]
    paths = _resolve_paths(state.get("ocr_image_paths") or state.get("image_paths") or [], state.get("ocr_working_directory"))
    if not paths and task_content and Path(task_content).exists():
        paths = [task_content]
    if not paths:
        raise ValueError("ocr_agent requires 'ocr_image_paths' or 'image_paths'.")

    log_task_update("OCR Agent", f"OCR pass #{call_number} started.", "\n".join(paths))
    results = [openai_ocr_image(path, state.get("ocr_instruction")) for path in paths]
    prompt = f"""
You are an OCR review agent.
Summarize the extracted text, tables, and notable fields from these OCR results.

OCR Results:
{json.dumps(results, indent=2, ensure_ascii=False)[:25000]}
"""
    summary = llm_text(prompt)
    _write_agent_artifacts("ocr_agent", call_number, summary, results)
    state["ocr_results"] = results
    state["ocr_summary"] = summary
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "ocr_agent",
        summary,
        f"ocr_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def image_agent(state):
    _, task_content, _ = begin_agent_session(state, "image_agent")
    state["image_agent_calls"] = state.get("image_agent_calls", 0) + 1
    call_number = state["image_agent_calls"]
    paths = _resolve_paths(
        state.get("image_analysis_paths") or state.get("image_paths") or [],
        state.get("image_working_directory"),
    )
    if not paths and task_content and Path(task_content).exists():
        paths = [task_content]
    if not paths:
        raise ValueError("image_agent requires 'image_analysis_paths' or 'image_paths'.")

    log_task_update("Image Agent", f"Image analysis pass #{call_number} started.", "\n".join(paths))
    results = [openai_analyze_image(path, state.get("image_instruction")) for path in paths]
    prompt = f"""
You are an image understanding agent.

Objective:
{state.get("current_objective") or state.get("user_query", "")}

Image analysis results:
{json.dumps(results, indent=2, ensure_ascii=False)[:25000]}

Produce a meaningful summary. Highlight:
- what is in the image
- text or labels if relevant
- probable context or intent
- important anomalies, trends, or signals
- any actionable or decision-useful insights
"""
    summary = llm_text(prompt)
    _write_agent_artifacts("image_agent", call_number, summary, results)
    state["image_analysis_results"] = results
    state["image_analysis_summary"] = summary
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "image_agent",
        summary,
        f"image_analysis_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def entity_resolution_agent(state):
    _, task_content, _ = begin_agent_session(state, "entity_resolution_agent")
    state["entity_resolution_calls"] = state.get("entity_resolution_calls", 0) + 1
    call_number = state["entity_resolution_calls"]
    candidates = state.get("entity_candidates") or [state.get("research_target") or task_content or state.get("current_objective") or state.get("user_query", "")]
    evidence = build_evidence_bundle(state)

    prompt = f"""
You are an entity resolution agent.

Resolve the candidate entities into canonical entities with aliases, domains, handles, entity types, and confidence scores.

Candidates:
{json.dumps(candidates, ensure_ascii=False)}

Evidence:
{evidence_text(evidence)}

Return ONLY valid JSON:
{{
  "entities": [
    {{
      "canonical_name": "name",
      "entity_type": "person|company|organization|group|unknown",
      "aliases": ["alias"],
      "domains": ["example.com"],
      "handles": ["@handle"],
      "confidence": 0.0,
      "notes": "reasoning"
    }}
  ]
}}
"""
    result = llm_json(prompt, {"entities": []})
    summary = json.dumps(result, indent=2, ensure_ascii=False)
    _write_agent_artifacts("entity_resolution_agent", call_number, summary, result)
    state["entity_resolution"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "entity_resolution_agent",
        summary,
        f"entity_resolution_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def knowledge_graph_agent(state):
    _, task_content, _ = begin_agent_session(state, "knowledge_graph_agent")
    state["knowledge_graph_calls"] = state.get("knowledge_graph_calls", 0) + 1
    call_number = state["knowledge_graph_calls"]
    evidence = build_evidence_bundle(state)

    prompt = f"""
You are a knowledge graph construction agent.

Build a graph of entities, events, documents, and relationships from the available evidence.

Focus:
{task_content or state.get("current_objective") or state.get("user_query", "")}

Evidence:
{evidence_text(evidence)}

Return ONLY valid JSON:
{{
  "nodes": [{{"id": "node1", "label": "Name", "type": "entity|event|document"}}],
  "edges": [{{"source": "node1", "target": "node2", "relation": "affiliated_with", "evidence": "brief"}}],
  "summary": "brief graph summary"
}}
"""
    result = llm_json(prompt, {"nodes": [], "edges": [], "summary": "No graph generated."})
    summary = result.get("summary", "No graph summary.")
    _write_agent_artifacts("knowledge_graph_agent", call_number, summary, result)
    state["knowledge_graph"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "knowledge_graph_agent",
        summary,
        f"knowledge_graph_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def timeline_agent(state):
    _, task_content, _ = begin_agent_session(state, "timeline_agent")
    state["timeline_calls"] = state.get("timeline_calls", 0) + 1
    call_number = state["timeline_calls"]
    evidence = build_evidence_bundle(state)

    prompt = f"""
You are a timeline reconstruction agent.

Build a dated sequence of important events for the target. Prefer concrete dates; if only approximate dates are known, say so explicitly.

Focus:
{task_content or state.get("research_target") or state.get("current_objective") or state.get("user_query", "")}

Evidence:
{evidence_text(evidence)}

Return ONLY valid JSON:
{{
  "events": [
    {{
      "date": "YYYY-MM-DD or approximate date",
      "event": "what happened",
      "confidence": "low|medium|high",
      "source_hint": "where it came from"
    }}
  ],
  "summary": "brief timeline summary"
}}
"""
    result = llm_json(prompt, {"events": [], "summary": "No timeline generated."})
    summary = result.get("summary", "No timeline summary.")
    _write_agent_artifacts("timeline_agent", call_number, summary, result)
    state["timeline"] = result.get("events", [])
    state["timeline_summary"] = summary
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "timeline_agent",
        summary,
        f"timeline_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def source_verification_agent(state):
    _, task_content, _ = begin_agent_session(state, "source_verification_agent")
    state["source_verification_calls"] = state.get("source_verification_calls", 0) + 1
    call_number = state["source_verification_calls"]
    claims = state.get("claims_to_verify") or []
    evidence = build_evidence_bundle(state)

    prompt = f"""
You are a source verification agent.

Assess the quality and corroboration of claims and evidence. Flag weak sourcing, contradictions, and unverifiable claims.

Claims:
{json.dumps(claims, indent=2, ensure_ascii=False)}

Evidence:
{evidence_text(evidence)}

Return ONLY valid JSON:
{{
  "overall_confidence": "low|medium|high",
  "claim_assessments": [
    {{
      "claim": "text",
      "status": "verified|partially_verified|unverified|contradicted",
      "confidence": "low|medium|high",
      "notes": "brief notes"
    }}
  ],
  "summary": "brief verification summary"
}}
"""
    result = llm_json(
        prompt,
        {"overall_confidence": "medium", "claim_assessments": [], "summary": "No verification summary."},
    )
    summary = result.get("summary", "No verification summary.")
    _write_agent_artifacts("source_verification_agent", call_number, summary, result)
    state["verification_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "source_verification_agent",
        summary,
        f"source_verification_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def people_research_agent(state):
    _, task_content, _ = begin_agent_session(state, "people_research_agent")
    state["people_research_calls"] = state.get("people_research_calls", 0) + 1
    call_number = state["people_research_calls"]
    target = state.get("person_name") or state.get("research_target") or task_content or state.get("current_objective") or state.get("user_query", "")
    memory_hits = _maybe_search_memory(state, target, top_k=int(state.get("memory_top_k", 5))) if state.get("use_vector_memory", True) else []
    evidence = build_evidence_bundle(state)
    evidence["memory_hits"] = memory_hits

    prompt = f"""
You are a people research agent.

Target person:
{target}

Evidence:
{evidence_text(evidence)}

Return ONLY valid JSON:
{{
  "name": "person name",
  "summary": "executive summary",
  "roles": ["role"],
  "organizations": ["org"],
  "locations": ["location"],
  "notable_events": ["event"],
  "risks_or_uncertainties": ["risk"]
}}
"""
    result = llm_json(
        prompt,
        {
            "name": target,
            "summary": "No people profile generated.",
            "roles": [],
            "organizations": [],
            "locations": [],
            "notable_events": [],
            "risks_or_uncertainties": [],
        },
    )
    summary = result.get("summary", "No people profile generated.")
    _write_agent_artifacts("people_research_agent", call_number, summary, result)
    state["people_profile"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "people_research_agent",
        summary,
        f"people_research_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def company_research_agent(state):
    _, task_content, _ = begin_agent_session(state, "company_research_agent")
    state["company_research_calls"] = state.get("company_research_calls", 0) + 1
    call_number = state["company_research_calls"]
    target = state.get("company_name") or state.get("research_target") or task_content or state.get("current_objective") or state.get("user_query", "")
    memory_hits = _maybe_search_memory(state, target, top_k=int(state.get("memory_top_k", 5))) if state.get("use_vector_memory", True) else []
    evidence = build_evidence_bundle(state)
    evidence["memory_hits"] = memory_hits

    prompt = f"""
You are a company research agent.

Target company or organization:
{target}

Evidence:
{evidence_text(evidence)}

Return ONLY valid JSON:
{{
  "name": "company name",
  "summary": "executive summary",
  "industry": "industry or unknown",
  "leadership": ["name - role"],
  "products_or_services": ["item"],
  "risks": ["risk"],
  "important_dates": ["date - event"]
}}
"""
    result = llm_json(
        prompt,
        {
            "name": target,
            "summary": "No company profile generated.",
            "industry": "unknown",
            "leadership": [],
            "products_or_services": [],
            "risks": [],
            "important_dates": [],
        },
    )
    summary = result.get("summary", "No company profile generated.")
    _write_agent_artifacts("company_research_agent", call_number, summary, result)
    state["company_profile"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "company_research_agent",
        summary,
        f"company_research_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def relationship_mapping_agent(state):
    _, task_content, _ = begin_agent_session(state, "relationship_mapping_agent")
    state["relationship_mapping_calls"] = state.get("relationship_mapping_calls", 0) + 1
    call_number = state["relationship_mapping_calls"]
    evidence = build_evidence_bundle(state)

    prompt = f"""
You are a relationship mapping agent.

Map meaningful relationships among people, companies, organizations, groups, and events.

Focus:
{task_content or state.get("research_target") or state.get("current_objective") or state.get("user_query", "")}

Evidence:
{evidence_text(evidence)}

Return ONLY valid JSON:
{{
  "relationships": [
    {{
      "source": "entity A",
      "target": "entity B",
      "relation": "employs|founded|partnered_with|member_of|invested_in|connected_to",
      "confidence": "low|medium|high",
      "notes": "brief note"
    }}
  ],
  "summary": "brief relationship summary"
}}
"""
    result = llm_json(prompt, {"relationships": [], "summary": "No relationships generated."})
    summary = result.get("summary", "No relationship summary.")
    _write_agent_artifacts("relationship_mapping_agent", call_number, summary, result)
    state["relationship_map"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "relationship_mapping_agent",
        summary,
        f"relationship_mapping_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def news_monitor_agent(state):
    _, task_content, _ = begin_agent_session(state, "news_monitor_agent")
    state["news_monitor_calls"] = state.get("news_monitor_calls", 0) + 1
    call_number = state["news_monitor_calls"]
    query = state.get("news_query") or task_content or state.get("research_target") or state.get("current_objective") or state.get("user_query", "")
    payload = serp_search(query, num=int(state.get("news_num_results", 10)), extra_params={"tbm": "nws"})
    articles = payload.get("news_results", []) or payload.get("organic_results", [])

    prompt = f"""
You are a news monitoring agent.

Query:
{query}

News results:
{json.dumps(articles, indent=2, ensure_ascii=False)}

Summarize the recent developments, why they matter, and any trend or sentiment changes.
"""
    summary = llm_text(prompt)
    result = {"query": query, "articles": articles, "summary": summary}
    _write_agent_artifacts("news_monitor_agent", call_number, summary, result)
    state["news_monitor_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "news_monitor_agent",
        summary,
        f"news_monitor_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def compliance_risk_agent(state):
    _, task_content, _ = begin_agent_session(state, "compliance_risk_agent")
    state["compliance_risk_calls"] = state.get("compliance_risk_calls", 0) + 1
    call_number = state["compliance_risk_calls"]
    target = state.get("research_target") or task_content or state.get("current_objective") or state.get("user_query", "")
    query = state.get("compliance_query") or f"{target} lawsuit sanctions fraud regulatory action adverse media"
    search_payload = None
    if os.getenv("SERP_API_KEY"):
        search_payload = serp_search(query, num=int(state.get("compliance_search_results", 8)))
    evidence = build_evidence_bundle(state)
    evidence["adverse_search"] = search_payload

    prompt = f"""
You are a compliance and risk agent.

Target:
{target}

Evidence:
{evidence_text(evidence)}

Assess reputational, legal, sanctions, fraud, regulatory, and data quality risks.

Return ONLY valid JSON:
{{
  "risk_level": "low|medium|high",
  "risk_flags": [
    {{
      "category": "legal|sanctions|fraud|regulatory|reputation|data_gap",
      "severity": "low|medium|high",
      "detail": "brief detail"
    }}
  ],
  "summary": "brief risk summary"
}}
"""
    result = llm_json(prompt, {"risk_level": "medium", "risk_flags": [], "summary": "No risk summary generated."})
    summary = result.get("summary", "No risk summary generated.")
    _write_agent_artifacts("compliance_risk_agent", call_number, summary, result)
    state["compliance_risk_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "compliance_risk_agent",
        summary,
        f"compliance_risk_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def structured_data_agent(state):
    _, task_content, _ = begin_agent_session(state, "structured_data_agent")
    state["structured_data_calls"] = state.get("structured_data_calls", 0) + 1
    call_number = state["structured_data_calls"]
    evidence = build_evidence_bundle(state)

    prompt = f"""
You are a structured data extraction agent.

Convert the available evidence into normalized facts for downstream graphing, reporting, and verification.

Focus:
{task_content or state.get("research_target") or state.get("current_objective") or state.get("user_query", "")}

Evidence:
{evidence_text(evidence)}

Return ONLY valid JSON:
{{
  "facts": [
    {{
      "subject": "entity",
      "predicate": "relationship or attribute",
      "object": "value",
      "confidence": "low|medium|high",
      "source_hint": "where from"
    }}
  ],
  "summary": "brief extraction summary"
}}
"""
    result = llm_json(prompt, {"facts": [], "summary": "No structured facts generated."})
    summary = result.get("summary", "No structured facts generated.")
    _write_agent_artifacts("structured_data_agent", call_number, summary, result)
    state["structured_facts"] = result.get("facts", [])
    state["structured_data_report"] = result
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "structured_data_agent",
        summary,
        f"structured_data_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def memory_index_agent(state):
    _, task_content, _ = begin_agent_session(state, "memory_index_agent")
    state["memory_index_calls"] = state.get("memory_index_calls", 0) + 1
    call_number = state["memory_index_calls"]
    records = _textual_sources_for_memory(state)
    if task_content and not records:
        records = [{"source": "task_content", "text": task_content, "payload": {"source_type": "manual"}}]

    if not records:
        raise ValueError("memory_index_agent found no text sources in state to index.")

    result = _maybe_upsert_memory(state, records)
    query = state.get("memory_query") or state.get("research_target") or state.get("current_objective") or state.get("user_query", "")
    matches = _maybe_search_memory(state, query, top_k=int(state.get("memory_top_k", 5))) if query else []
    summary = (
        f"Indexed {result['indexed']} records into vector memory collection '{result['collection']}'.\n"
        f"Top matches for '{query}':\n"
        + "\n".join(f"- {item.get('source', '')}: {item.get('text', '')[:180]}" for item in matches)
    )
    payload = {"index_result": result, "matches": matches}
    _write_agent_artifacts("memory_index_agent", call_number, summary, payload)
    state["memory_index_result"] = result
    state["memory_search_results"] = matches
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "memory_index_agent",
        summary,
        f"memory_index_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def citation_agent(state):
    _, task_content, _ = begin_agent_session(state, "citation_agent")
    state["citation_calls"] = state.get("citation_calls", 0) + 1
    call_number = state["citation_calls"]
    citations = []

    for page in state.get("web_crawl_pages", []) or []:
        citations.append(
            {
                "title": page.get("url", "web page"),
                "url": page.get("url", ""),
                "source_type": "web_page",
                "note": page.get("text", "")[:200],
            }
        )
    for doc in state.get("documents", []) or []:
        citations.append(
            {
                "title": Path(doc.get("path", "")).name or "document",
                "url": doc.get("path", ""),
                "source_type": doc.get("metadata", {}).get("type", "document"),
                "note": doc.get("text", "")[:200],
            }
        )
    for article in (state.get("news_monitor_report", {}) or {}).get("articles", []):
        citations.append(
            {
                "title": article.get("title", "news result"),
                "url": article.get("link", ""),
                "source_type": "news",
                "note": article.get("snippet", "")[:200],
            }
        )

    if task_content:
        citations.append({"title": "task_context", "url": "", "source_type": "task", "note": task_content[:200]})

    prompt = f"""
You are a citation formatting agent.

Standardize and de-duplicate these citations. Keep only useful entries.

Raw citations:
{json.dumps(citations, indent=2, ensure_ascii=False)}

Return ONLY valid JSON:
{{
  "citations": [
    {{
      "title": "source title",
      "url": "url or path",
      "source_type": "web_page|news|document|task",
      "note": "why it matters"
    }}
  ],
  "summary": "brief citation summary"
}}
"""
    result = llm_json(prompt, {"citations": citations, "summary": "Fallback citations generated."})
    summary = result.get("summary", "No citation summary.")
    _write_agent_artifacts("citation_agent", call_number, summary, result)
    state["citations"] = result.get("citations", [])
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "citation_agent",
        summary,
        f"citation_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )
