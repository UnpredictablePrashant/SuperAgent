import json
import math
import os
from pathlib import Path

from kendr.domain.local_drive import (
    extension_handler_registry as _extension_handler_registry,
    maybe_search_memory as _maybe_search_memory,
    maybe_upsert_memory as _maybe_upsert_memory,
    merge_documents as _merge_documents,
    normalize_extension_set as _normalize_extension_set,
    resolve_paths as _resolve_paths,
    route_files_by_handler as _route_files_by_handler,
    safe_slug as _safe_slug,
    scan_local_drive_tree as _scan_local_drive_tree,
    textual_sources_for_memory as _textual_sources_for_memory,
    unknown_extensions_from_manifest as _unknown_extensions_from_manifest,
)

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.research_infra import (
    IMAGE_FILE_EXTENSIONS,
    build_evidence_bundle,
    crawl_urls,
    evidence_text,
    llm_json,
    openai_analyze_image,
    llm_text,
    openai_ocr_image,
    parse_documents,
    search_result_urls,
    serp_search,
    summarize_pages,
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
            "local_drive_manifest",
            "local_drive_documents",
            "local_drive_document_summaries",
            "local_drive_summary_bank",
            "local_drive_handler_registry",
            "local_drive_handler_routes",
            "local_drive_unknown_extensions",
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


def _collect_ocr_candidate_paths(state: dict) -> list[str]:
    base_directory = (
        state.get("ocr_working_directory")
        or state.get("local_drive_working_directory")
        or state.get("working_directory")
    )
    candidates: list[str] = []

    explicit_paths = state.get("ocr_image_paths") or state.get("image_paths") or []
    candidates.extend(_resolve_paths(explicit_paths, base_directory))

    routed = state.get("local_drive_handler_routes", {})
    if isinstance(routed, dict):
        routed_images = routed.get("ocr_agent", []) if isinstance(routed.get("ocr_agent"), list) else []
        candidates.extend(_resolve_paths(routed_images, base_directory))

    manifest = state.get("local_drive_manifest", {}) if isinstance(state.get("local_drive_manifest"), dict) else {}
    manifest_selected = manifest.get("selected_files") if isinstance(manifest.get("selected_files"), list) else []
    candidates.extend(_resolve_paths(manifest_selected, base_directory))

    drive_files = state.get("local_drive_files") if isinstance(state.get("local_drive_files"), list) else []
    candidates.extend(_resolve_paths(drive_files, base_directory))

    drive_documents = state.get("local_drive_documents") if isinstance(state.get("local_drive_documents"), list) else []
    for item in drive_documents:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "") or "").strip()
        if path:
            candidates.extend(_resolve_paths([path], base_directory))

    deduped: list[str] = []
    seen: set[str] = set()
    for raw_path in candidates:
        path = str(raw_path or "").strip()
        if not path:
            continue
        suffix = Path(path).suffix.lower()
        if suffix not in IMAGE_FILE_EXTENSIONS:
            continue
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _load_extension_handler_overrides(state: dict) -> dict[str, str]:
    raw = (
        state.get("local_drive_extension_handler_registry")
        or state.get("local_drive_extension_handlers")
        or {}
    )
    if isinstance(raw, dict):
        return {
            str(key): str(value)
            for key, value in raw.items()
            if str(key).strip() and str(value).strip()
        }
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return {
                str(key): str(value)
                for key, value in parsed.items()
                if str(key).strip() and str(value).strip()
            }
    return {}


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
    base_directory = (
        state.get("document_working_directory")
        or state.get("local_drive_working_directory")
        or state.get("working_directory")
    )
    objective = state.get("current_objective") or state.get("user_query", "")
    raw_paths = state.get("document_paths") or state.get("doc_paths") or []
    paths = _resolve_paths(raw_paths, base_directory)
    if not paths and task_content and Path(task_content).exists():
        paths = _resolve_paths([task_content], base_directory)
    handler_routes = state.get("local_drive_handler_routes", {})
    routed_document_paths = []
    has_document_routing = False
    ingestion_source = "explicit_document_paths"
    if isinstance(handler_routes, dict):
        has_document_routing = "document_ingestion_agent" in handler_routes
        raw_routed = handler_routes.get("document_ingestion_agent", [])
        if isinstance(raw_routed, list):
            routed_document_paths = _resolve_paths(
                raw_routed,
                state.get("local_drive_working_directory") or state.get("working_directory"),
            )
    if not paths and routed_document_paths:
        paths = routed_document_paths
        ingestion_source = "local_drive_handler_routes"
    if not paths:
        manifest = state.get("local_drive_manifest", {}) if isinstance(state.get("local_drive_manifest"), dict) else {}
        fallback_paths = state.get("local_drive_files") or manifest.get("selected_files") or []
        if has_document_routing:
            fallback_paths = []
        if fallback_paths:
            paths = _resolve_paths(
                fallback_paths,
                state.get("local_drive_working_directory") or state.get("working_directory"),
            )
            ingestion_source = "local_drive_files"

    if not paths:
        raw_roots = (
            state.get("local_drive_paths")
            or state.get("knowledge_drive_paths")
            or state.get("drive_paths")
            or []
        )
        roots = _resolve_paths(raw_roots, state.get("local_drive_working_directory") or state.get("working_directory"))
        if roots:
            scan = _scan_local_drive_tree(
                roots,
                recursive=bool(state.get("local_drive_recursive", True)),
                include_hidden=bool(state.get("local_drive_include_hidden", False)),
                max_files=max(1, min(int(state.get("local_drive_max_files", 200)), 1000)),
                allowed_extensions=_normalize_extension_set(state.get("local_drive_extensions")),
            )
            selected_files = list(scan.get("selected_files") or [])
            if selected_files:
                state["local_drive_manifest"] = scan
                state["local_drive_files"] = selected_files
                paths = selected_files
                ingestion_source = "on_demand_local_drive_scan"

    documents = []
    attempted_paths: list[str] = []
    if paths:
        attempted_paths = list(paths)
        documents = parse_documents(
            paths,
            continue_on_error=True,
            ocr_images=bool(state.get("local_drive_enable_image_ocr", True)),
            ocr_instruction=state.get("local_drive_ocr_instruction"),
        )
    elif isinstance(state.get("local_drive_documents"), list) and state.get("local_drive_documents"):
        documents = state.get("local_drive_documents", [])
        ingestion_source = "local_drive_documents"
    elif isinstance(state.get("documents"), list) and state.get("documents"):
        documents = state.get("documents", [])
        ingestion_source = "state_documents"
    else:
        for item in state.get("local_drive_document_summaries", []) or []:
            if not isinstance(item, dict):
                continue
            summary_text = str(item.get("summary", "") or "").strip()
            if not summary_text:
                continue
            documents.append(
                {
                    "path": str(item.get("path", "") or ""),
                    "text": summary_text,
                    "metadata": {
                        "type": str(item.get("type", "") or "summary"),
                        "derived_from": "local_drive_document_summaries",
                    },
                }
            )
        if documents:
            ingestion_source = "local_drive_document_summaries"

    if not documents:
        if has_document_routing and not routed_document_paths:
            summary = (
                "No documents were routed to document_ingestion_agent from local-drive extension handling. "
                "Skipped document ingestion and continued without blocking the workflow."
            )
            _write_agent_artifacts("document_ingestion_agent", call_number, summary, [])
            state["documents"] = []
            state["document_summary"] = summary
            state["document_ingestion_skipped"] = True
            state["document_ingestion_skip_reason"] = "no_document_routes"
            state["draft_response"] = summary
            return publish_agent_output(
                state,
                "document_ingestion_agent",
                summary,
                f"document_ingestion_result_{call_number}",
                recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
            )
        raise ValueError(
            "document_ingestion_agent requires document_paths/doc_paths or prior local-drive outputs "
            "(local_drive_files/local_drive_documents/local_drive_document_summaries)."
        )

    if not attempted_paths:
        for item in documents:
            if not isinstance(item, dict):
                continue
            candidate_path = str(item.get("path", "") or "").strip()
            if candidate_path:
                attempted_paths.append(candidate_path)

    successful_files: list[str] = []
    failed_files: list[dict] = []
    for item in documents:
        if not isinstance(item, dict):
            continue
        path_value = str(item.get("path", "") or "").strip() or "(unknown)"
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        error_value = str(metadata.get("error", "") or "").strip()
        if error_value:
            failed_files.append({"path": path_value, "error": error_value})
        else:
            successful_files.append(path_value)

    raw_requested_roots = (
        state.get("local_drive_paths")
        or state.get("knowledge_drive_paths")
        or state.get("drive_paths")
        or state.get("document_root_paths")
        or []
    )
    requested_roots = _resolve_paths(raw_requested_roots, base_directory)

    def _path_within_root(path_value: str, root_value: str) -> bool:
        try:
            normalized_path = os.path.normcase(os.path.abspath(path_value))
            normalized_root = os.path.normcase(os.path.abspath(root_value))
            return os.path.commonpath([normalized_path, normalized_root]) == normalized_root
        except Exception:
            return False

    coverage_rows: list[dict] = []
    for root in requested_roots:
        matched = [item for item in attempted_paths if _path_within_root(item, root)]
        coverage_rows.append(
            {
                "root": root,
                "matched_files": matched,
                "matched_count": len(matched),
            }
        )
    uncovered_roots = [row["root"] for row in coverage_rows if not row["matched_files"]]
    coverage_status = "covered" if coverage_rows and not uncovered_roots else "partial" if coverage_rows else "not_specified"

    prompt = f"""
You are a document ingestion and extraction agent.

Objective:
{objective}

Documents:
{json.dumps(documents, indent=2, ensure_ascii=False)[:25000]}

Summarize the important facts, entities, dates, metrics, and unanswered questions.
"""
    narrative_summary = llm_text(prompt)

    confirmation_lines = [
        "Document Ingestion Confirmation",
        f"- Objective: {objective or 'not provided'}",
        f"- Ingestion source: {ingestion_source}",
        f"- Requested root path(s): {', '.join(requested_roots) if requested_roots else 'none provided'}",
        f"- Files attempted: {len(attempted_paths)}",
        f"- Files parsed successfully: {len(successful_files)}",
        f"- Files with extraction errors: {len(failed_files)}",
        f"- Path coverage status: {coverage_status}",
    ]
    if coverage_rows:
        confirmation_lines.append("")
        confirmation_lines.append("Path Coverage")
        for row in coverage_rows:
            confirmation_lines.append(f"- {row['root']}: {row['matched_count']} matched file(s)")
    if successful_files:
        confirmation_lines.append("")
        confirmation_lines.append("Sample Parsed Files")
        for item in successful_files[: min(10, len(successful_files))]:
            confirmation_lines.append(f"- {item}")
    if failed_files:
        confirmation_lines.append("")
        confirmation_lines.append("Files With Extraction Errors")
        for item in failed_files[: min(20, len(failed_files))]:
            confirmation_lines.append(f"- {item['path']} | error={item['error']}")
    if uncovered_roots:
        confirmation_lines.append("")
        confirmation_lines.append("Uncovered Requested Roots")
        for root in uncovered_roots:
            confirmation_lines.append(f"- {root}")

    summary = "\n".join(confirmation_lines + ["", "Findings", narrative_summary])
    _write_agent_artifacts("document_ingestion_agent", call_number, summary, documents)
    state["documents"] = documents
    state["document_summary"] = summary
    state["document_ingestion_source"] = ingestion_source
    state["document_ingestion_report"] = {
        "requested_roots": requested_roots,
        "coverage": coverage_rows,
        "coverage_status": coverage_status,
        "attempted_files": attempted_paths,
        "successful_files": successful_files,
        "failed_files": failed_files,
        "ingestion_source": ingestion_source,
    }
    state["document_ingestion_confirmed"] = bool(attempted_paths) and bool(successful_files)
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

    manifest = _scan_local_drive_tree(
        roots,
        recursive=recursive,
        include_hidden=include_hidden,
        max_files=max_files,
        allowed_extensions=allowed_extensions,
    )
    files = list(manifest.get("selected_files") or [])
    if not files:
        raise ValueError("local_drive_agent found no supported files in the selected path(s).")

    # Determine whether the local-drive corpus is likely insufficient for long-form output.
    target_pages = 0
    try:
        target_pages = int(state.get("long_document_pages") or state.get("report_target_pages") or 0)
    except Exception:
        target_pages = 0
    wants_long_document = bool(state.get("local_drive_force_long_document", False) or state.get("long_document_mode", False) or target_pages)
    min_files_override = 0
    try:
        min_files_override = int(state.get("local_drive_min_files_for_long_document") or 0)
    except Exception:
        min_files_override = 0
    if wants_long_document:
        if target_pages <= 0:
            target_pages = 50
        min_files_required = min_files_override or max(2, math.ceil(target_pages / 25))
    else:
        min_files_required = 0
    local_drive_insufficient = bool(wants_long_document and min_files_required > 0 and len(files) < min_files_required)
    state["local_drive_sufficiency_threshold"] = min_files_required
    state["local_drive_selected_file_count"] = len(files)
    state["local_drive_insufficient"] = local_drive_insufficient
    if local_drive_insufficient:
        state["local_drive_insufficient_files_preview"] = files[:10]

    handler_overrides = _load_extension_handler_overrides(state)
    handler_registry = _extension_handler_registry(handler_overrides)
    handler_routes = _route_files_by_handler(files, registry=handler_registry)
    unknown_extensions = _unknown_extensions_from_manifest(manifest, registry=handler_registry)

    routed_document_paths = list(handler_routes.get("document_ingestion_agent") or [])
    routed_ocr_paths = list(handler_routes.get("ocr_agent") or [])
    routed_excel_paths = list(handler_routes.get("excel_agent") or [])
    state["local_drive_handler_registry"] = handler_registry
    state["local_drive_handler_routes"] = handler_routes
    state["local_drive_unknown_extensions"] = unknown_extensions
    state["document_paths"] = routed_document_paths
    if routed_ocr_paths:
        state["ocr_image_paths"] = routed_ocr_paths
        if not state.get("image_paths"):
            state["image_paths"] = list(routed_ocr_paths)
    else:
        state["ocr_image_paths"] = []
    if routed_excel_paths:
        state["excel_file_paths"] = routed_excel_paths
        if not str(state.get("excel_file_path", "")).strip():
            state["excel_file_path"] = routed_excel_paths[0]
    else:
        state["excel_file_paths"] = []

    auto_generate_handlers = bool(state.get("local_drive_auto_generate_extension_handlers", False))
    if auto_generate_handlers and unknown_extensions:
        signature = "|".join(unknown_extensions)
        already_dispatched = bool(state.get("extension_handler_generation_dispatched", False)) and (
            str(state.get("extension_handler_generation_signature", "")).strip() == signature
        )
        if already_dispatched:
            state["extension_handler_generation_requested"] = False
            state["extension_handler_generation_signature"] = signature
            log_task_update(
                "Local Drive",
                "Unsupported extensions already processed for dynamic handler generation.",
                f"extensions: {', '.join(unknown_extensions)}",
            )
        else:
            capability_list = ", ".join(unknown_extensions)
            example_files = []
            file_entries = manifest.get("files") if isinstance(manifest.get("files"), list) else []
            for item in file_entries:
                if not isinstance(item, dict):
                    continue
                ext = str(item.get("extension", "") or "").strip().lower()
                if ext in unknown_extensions:
                    example_files.append(str(item.get("path", "")).strip())
            example_files = [item for item in example_files if item][:6]
            state["extension_handler_generation_requested"] = True
            state["extension_handler_generation_dispatched"] = False
            state["extension_handler_generation_signature"] = signature
            state["missing_capability"] = f"File extension handling: {capability_list}"
            state["requested_missing_capability"] = state["missing_capability"]
            state["agent_factory_request"] = (
                "Create a file-extension ingestion agent capability for unsupported local-drive file types. "
                f"Unsupported extensions: {capability_list}. "
                f"Example paths: {', '.join(example_files) if example_files else 'none provided'}."
            )
            log_task_update(
                "Local Drive",
                "Unsupported extensions detected; queued optional extension-handler generation request.",
                f"extensions: {capability_list}",
            )
    elif not unknown_extensions:
        state["extension_handler_generation_requested"] = False
        state["extension_handler_generation_dispatched"] = False
        state["extension_handler_generation_signature"] = ""

    log_task_update(
        "Local Drive",
        (
            f"Local drive pass #{call_number} started. "
            f"Processing {len(files)} selected file(s) from {manifest.get('file_count', 0)} discovered files."
        ),
        "\n".join(files[:20]),
    )

    documents = []
    document_summaries = []
    for index, file_path in enumerate(files, start=1):
        log_task_update(
            "Local Drive",
            f"[{index}/{len(files)}] Scanning file.",
            file_path,
        )
        parsed = parse_documents(
            [file_path],
            continue_on_error=True,
            ocr_images=image_ocr_enabled,
            ocr_instruction=ocr_instruction,
        )[0]
        documents.append(parsed)

        parsed_text = str(parsed.get("text", "") or "").strip()
        metadata = parsed.get("metadata", {}) if isinstance(parsed.get("metadata"), dict) else {}
        extraction_error = str(metadata.get("error", "") or "").strip()
        if extraction_error:
            log_task_update(
                "Local Drive",
                f"[{index}/{len(files)}] Skipped unreadable file.",
                f"{file_path}\nreason: {extraction_error}",
            )
        else:
            log_task_update(
                "Local Drive",
                f"[{index}/{len(files)}] Parsed file successfully.",
                f"{file_path}\ncharacters: {len(parsed_text)}",
            )
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

    type_counts: dict[str, int] = {}
    extraction_issues: list[str] = []
    for item in document_summaries:
        document_type = str(item.get("type", "") or "unknown").strip() or "unknown"
        type_counts[document_type] = int(type_counts.get(document_type, 0) or 0) + 1
        if str(item.get("error", "") or "").strip():
            extraction_issues.append(str(item.get("file_name", "") or item.get("path", "")).strip())

    catalog_lines = [
        "Catalog Summary",
        f"- Roots: {', '.join(roots)}",
        f"- Recursive scan: {'yes' if recursive else 'no'}",
        f"- Folders discovered: {manifest.get('folder_count', 0)}",
        f"- Files discovered: {manifest.get('file_count', 0)}",
        f"- Files selected for processing: {manifest.get('selected_file_count', 0)}",
        f"- Files excluded from processing: {manifest.get('excluded_file_count', 0)}",
        f"- Documents summarized: {len(document_summaries)}",
        f"- Extraction issues: {len(extraction_issues)}",
        "",
        "File Type Counts",
    ]
    for document_type, count in sorted(type_counts.items()):
        catalog_lines.append(f"- {document_type}: {count}")

    catalog_lines.extend(["", "Representative Files"])
    for item in document_summaries[: min(12, len(document_summaries))]:
        error = str(item.get("error", "") or "").strip() or "none"
        catalog_lines.append(
            f"- {item['file_name']} | type={item['type']} | chars={item['char_count']} | error={error}"
        )

    if extraction_issues:
        catalog_lines.extend(["", "Files With Extraction Issues"])
        for name in extraction_issues[:10]:
            catalog_lines.append(f"- {name}")

    handler_counts = {
        agent_name: len(agent_paths)
        for agent_name, agent_paths in sorted(handler_routes.items())
    }
    catalog_lines.extend(["", "Extension Handler Routing"])
    if handler_counts:
        for agent_name, count in handler_counts.items():
            catalog_lines.append(f"- {agent_name}: {count} file(s)")
    else:
        catalog_lines.append("- no routed files")
    if unknown_extensions:
        catalog_lines.append(f"- unknown_extensions: {', '.join(unknown_extensions)}")
    else:
        catalog_lines.append("- unknown_extensions: none")
    if auto_generate_handlers:
        catalog_lines.append("- auto_generate_handlers: enabled")
    else:
        catalog_lines.append("- auto_generate_handlers: disabled")

    manifest_preview = {
        "folder_count": manifest.get("folder_count", 0),
        "file_count": manifest.get("file_count", 0),
        "selected_file_count": manifest.get("selected_file_count", 0),
        "excluded_file_count": manifest.get("excluded_file_count", 0),
        "truncated": bool(manifest.get("truncated", False)),
        "folders": (manifest.get("folders") or [])[:8],
        "files": (manifest.get("files") or [])[:12],
    }

    catalog_lines.extend(
        [
            "",
            "Structured Manifest",
            "- A full per-entry filesystem manifest with metadata for each scanned file and folder was produced in the JSON artifact.",
            f"- Manifest entries: {manifest.get('entry_count', 0)} total",
            f"- Manifest preview folders: {min(len(manifest_preview['folders']), manifest.get('folder_count', 0))}",
            f"- Manifest preview files: {min(len(manifest_preview['files']), manifest.get('file_count', 0))}",
            json.dumps(manifest_preview, indent=2, ensure_ascii=False),
        ]
    )

    final_summary = "\n".join(catalog_lines + ["", "Rollup Findings", rollup_summary])

    if local_drive_insufficient and not state.get("local_drive_insufficient_approved", False) and not state.get("local_drive_insufficient_prompted", False):
        preview_names = [Path(item).name for item in files[:6]]
        preview_block = "\n".join(f"- {name}" for name in preview_names) if preview_names else "- (no files listed)"
        prompt_lines = [
            "Local-drive scan completed, but the available files look insufficient for the requested long-form report.",
            f"- Target pages: {target_pages}",
            f"- Files found: {len(files)}",
            f"- Suggested minimum files for this scope: {min_files_required}",
            "",
            "Files found (preview):",
            preview_block,
            "",
            "Do you want to continue anyway using web research and the available files, or stop and add more documents?",
            "Reply `continue` to proceed, or reply with changes / add more files to stop and revise.",
        ]
        prompt = "\n".join(prompt_lines)
        state["pending_user_input_kind"] = "drive_data_sufficiency"
        state["approval_pending_scope"] = "drive_data_sufficiency"
        state["pending_user_question"] = prompt
        state["draft_response"] = prompt
        state["_skip_review_once"] = True
        state["local_drive_insufficient_prompted"] = True

    payload = {
        "roots": roots,
        "recursive": recursive,
        "max_files": max_files,
        "allowed_extensions": sorted(allowed_extensions),
        "image_ocr_enabled": image_ocr_enabled,
        "files": files,
        "manifest": manifest,
        "handler_registry": handler_registry,
        "handler_routes": handler_routes,
        "unknown_extensions": unknown_extensions,
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
        "catalog": {
            "file_count": len(files),
            "document_count": len(document_summaries),
            "type_counts": type_counts,
            "extraction_issue_count": len(extraction_issues),
            "extraction_issues": extraction_issues,
        },
    }
    _write_agent_artifacts("local_drive_agent", call_number, final_summary, payload)

    state["local_drive_files"] = files
    state["local_drive_manifest"] = manifest
    state["local_drive_documents"] = documents
    state["local_drive_document_summaries"] = document_summaries
    state["local_drive_summary_bank"] = {item["path"]: item["summary"] for item in document_summaries}
    state["local_drive_catalog"] = payload["catalog"]
    state["local_drive_rollup_summary"] = rollup_summary
    state["documents"] = _merge_documents(state.get("documents", []), documents)
    state["local_drive_summary"] = final_summary
    state["document_summary"] = final_summary
    state["draft_response"] = final_summary
    if state.get("local_drive_index_to_memory", True):
        _maybe_upsert_memory(state, _textual_sources_for_memory(state))
    return publish_agent_output(
        state,
        "local_drive_agent",
        final_summary,
        f"local_drive_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "report_agent"],
    )


def ocr_agent(state):
    _, task_content, _ = begin_agent_session(state, "ocr_agent")
    state["ocr_calls"] = state.get("ocr_calls", 0) + 1
    call_number = state["ocr_calls"]
    paths = _collect_ocr_candidate_paths(state)
    if not paths and task_content and Path(task_content).exists():
        task_path = str(Path(task_content).resolve())
        if Path(task_path).suffix.lower() in IMAGE_FILE_EXTENSIONS:
            paths = [task_path]
    if not paths:
        summary = (
            "No image files were found for OCR. "
            "Skipped OCR step and continued without blocking the workflow."
        )
        _write_agent_artifacts("ocr_agent", call_number, summary, [])
        state["ocr_results"] = []
        state["ocr_summary"] = summary
        state["ocr_skipped"] = True
        state["ocr_skip_reason"] = "no_image_paths"
        state["draft_response"] = summary
        log_task_update("OCR Agent", f"OCR pass #{call_number} skipped: no image files detected.")
        return publish_agent_output(
            state,
            "ocr_agent",
            summary,
            f"ocr_result_{call_number}",
            recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
        )

    log_task_update("OCR Agent", f"OCR pass #{call_number} started.", "\n".join(paths))
    results = []
    failed_files = []
    successful_files = []
    for index, path in enumerate(paths, start=1):
        log_task_update(
            "OCR Agent",
            f"[{index}/{len(paths)}] Running OCR.",
            path,
        )
        try:
            item = openai_ocr_image(path, state.get("ocr_instruction"))
            item["error"] = ""
            results.append(item)
            successful_files.append(path)
            log_task_update(
                "OCR Agent",
                f"[{index}/{len(paths)}] OCR extracted text.",
                f"{path}\ncharacters: {len(str(item.get('text', '') or ''))}",
            )
        except Exception as exc:
            error_text = str(exc)
            failed_files.append({"path": path, "error": error_text})
            results.append({"path": path, "text": "", "error": error_text, "raw": {}})
            log_task_update(
                "OCR Agent",
                f"[{index}/{len(paths)}] OCR skipped unreadable image.",
                f"{path}\nreason: {error_text}",
            )

    prompt = f"""
You are an OCR review agent.
Summarize the extracted text, tables, and notable fields from these OCR results.

OCR Results:
{json.dumps(results, indent=2, ensure_ascii=False)[:25000]}
"""
    summary = llm_text(prompt)
    if failed_files:
        summary = (
            f"{summary}\n\nOCR file handling summary:\n"
            f"- Attempted: {len(paths)}\n"
            f"- Succeeded: {len(successful_files)}\n"
            f"- Skipped: {len(failed_files)}"
        )
    _write_agent_artifacts("ocr_agent", call_number, summary, results)
    state["ocr_results"] = results
    state["ocr_summary"] = summary
    state["ocr_failed_files"] = failed_files
    state["ocr_successful_files"] = successful_files
    state["ocr_skipped"] = False
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
