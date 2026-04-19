from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from kendr.persistence import (
    get_superrag_session,
    insert_superrag_chat_message,
    insert_superrag_ingestion,
    list_superrag_chat_messages,
    list_superrag_ingestions,
    list_superrag_sessions,
    upsert_superrag_session,
)
from kendr.providers import get_microsoft_graph_access_token

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.research_output import render_phase0_report
from tasks.research_infra import (
    LOCAL_DRIVE_SUPPORTED_EXTENSIONS,
    chunk_text,
    crawl_urls,
    llm_text,
    parse_documents,
    search_memory,
    upsert_memory_records,
)
from tasks.utils import log_task_update, write_text_file


AGENT_METADATA = {
    "superrag_agent": {
        "description": (
            "Builds and operates persistent session-based RAG knowledge systems from mixed sources "
            "(OneDrive, URLs, local paths, and databases) with vector indexing and chat retrieval."
        ),
        "skills": [
            "rag",
            "session-management",
            "vector-indexing",
            "onedrive-ingestion",
            "database-schema-intelligence",
            "source-grounded-chat",
        ],
        "input_keys": [
            "superrag_mode",
            "superrag_session_id",
            "superrag_new_session",
            "superrag_local_paths",
            "superrag_urls",
            "superrag_db_url",
            "superrag_chat_query",
            "superrag_onedrive_enabled",
            "superrag_onedrive_path",
        ],
        "output_keys": [
            "superrag_active_session_id",
            "superrag_sessions",
            "superrag_build_report",
            "superrag_chat_result",
            "superrag_status",
            "draft_response",
        ],
        "requirements": ["openai"],
        "display_name": "Super-RAG",
        "category": "data",
        "intent_patterns": [
            "search my documents", "ask my knowledge base", "rag query",
            "query my files", "search uploaded docs", "vector search",
            "build knowledge base", "index my documents",
        ],
        "active_when": ["env:OPENAI_API_KEY"],
        "config_hint": "Add your OpenAI API key and optionally connect OneDrive in Setup.",
    }
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(value: str, default: str = "session") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", str(value or "").strip()).strip("_.:-")
    return slug[:96] if slug else default


def _owner_key(state: dict) -> str:
    channel = str(state.get("incoming_channel", "webchat") or "webchat").strip().lower()
    workspace_id = str(state.get("incoming_workspace_id", "default") or "default").strip()
    sender_id = str(state.get("incoming_sender_id", "local_user") or "local_user").strip()
    return f"{channel}:{workspace_id}:{sender_id}"


def _collection_for_session(session_id: str) -> str:
    return f"superrag_{_safe_slug(session_id, default='default').replace(':', '_').replace('.', '_').lower()}"


def _extract_urls(text: str) -> list[str]:
    matches = re.findall(r"https?://[^\s)\]>,]+", str(text or ""), flags=re.IGNORECASE)
    deduped = []
    for item in matches:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _extract_db_url(text: str) -> str:
    pattern = r"(?:postgresql|postgres|mysql|mariadb|sqlite|mssql|oracle)(?:\+[^:]+)?://[^\s)\]>,]+"
    match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
    return match.group(0) if match else ""


def _extract_session_from_text(text: str) -> str:
    match = re.search(r"(?:session|rag-session|superrag-session)\s*[:=]?\s*([a-zA-Z0-9_.:-]{3,120})", str(text or ""), flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _infer_mode(state: dict, task_content: str) -> str:
    explicit = str(
        state.get("superrag_mode")
        or state.get("superrag_action")
        or state.get("rag_mode")
        or ""
    ).strip().lower()
    if explicit:
        aliases = {
            "build": "build",
            "index": "build",
            "ingest": "build",
            "chat": "chat",
            "ask": "chat",
            "qa": "chat",
            "switch": "switch",
            "use": "switch",
            "list": "list",
            "status": "status",
        }
        return aliases.get(explicit, explicit)

    text = " ".join(
        [
            str(task_content or ""),
            str(state.get("current_objective", "")),
            str(state.get("user_query", "")),
        ]
    ).lower()
    if "list" in text and "session" in text:
        return "list"
    if any(marker in text for marker in ("switch session", "use session", "change session", "set session")):
        return "switch"
    if any(marker in text for marker in ("session status", "rag status", "index status")):
        return "status"

    has_sources = any(
        [
            bool(state.get("superrag_local_paths")),
            bool(state.get("superrag_urls")),
            bool(state.get("superrag_db_url")),
            bool(state.get("superrag_onedrive_enabled")),
            bool(state.get("superrag_onedrive_path")),
            bool(_extract_db_url(text)),
            bool(_extract_urls(text)),
        ]
    )
    if has_sources:
        return "build"
    if any(marker in text for marker in ("chat with", "ask", "question", "query")):
        return "chat"
    if "superrag" in text or "rag" in text:
        return "status"
    return "build"


def _as_list(value) -> list[str]:
    if isinstance(value, str):
        if not value.strip():
            return []
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _normalize_roots(raw_roots, working_directory: str) -> list[str]:
    roots = []
    for raw_root in _as_list(raw_roots):
        path = Path(raw_root).expanduser()
        if not path.is_absolute():
            path = Path(working_directory).resolve() / path
        roots.append(str(path.resolve()))
    return roots


def _discover_local_files(
    roots: list[str],
    *,
    recursive: bool,
    include_hidden: bool,
    max_files: int,
    extensions: set[str],
) -> tuple[list[str], int]:
    files: list[str] = []
    total_size = 0
    seen: set[Path] = set()
    for root_item in roots:
        root = Path(root_item).expanduser().resolve()
        candidates = []
        if root.is_file():
            candidates = [root]
        elif root.is_dir():
            candidates = list(root.rglob("*")) if recursive else list(root.glob("*"))
        for item in sorted(candidates):
            if not item.is_file() or item in seen:
                continue
            if not include_hidden and any(part.startswith(".") for part in item.parts):
                continue
            if item.suffix.lower() not in extensions:
                continue
            seen.add(item)
            files.append(str(item))
            try:
                total_size += item.stat().st_size
            except Exception:
                pass
            if len(files) >= max_files:
                return files, total_size
    return files, total_size


def _default_session_id(state: dict) -> str:
    owner = _safe_slug(_owner_key(state), default="owner").replace(":", "_")
    return f"{owner}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


def _ensure_session(state: dict, *, requested_session_id: str = "", create_if_missing: bool = True) -> dict:
    session_id = _safe_slug(requested_session_id or state.get("superrag_active_session_id") or "")
    if not session_id:
        session_id = _default_session_id(state)

    current = get_superrag_session(session_id)
    if current:
        return current
    if not create_if_missing:
        return {}

    now = _now_iso()
    session = {
        "session_id": session_id,
        "collection_name": _collection_for_session(session_id),
        "owner_key": _owner_key(state),
        "title": f"superRAG session {session_id}",
        "status": "ready",
        "source_summary": {},
        "stats": {"documents": 0, "chunks": 0, "indexed": 0},
        "schema_kb": {},
        "created_at": now,
        "updated_at": now,
        "last_used_at": now,
    }
    upsert_superrag_session(session)
    return get_superrag_session(session_id) or session


def _stable_record_id(session_id: str, source: str, chunk_index: int, text: str) -> str:
    digest = hashlib.sha1(f"{session_id}|{source}|{chunk_index}|{text[:100]}".encode("utf-8", errors="ignore")).hexdigest()
    return f"sr_{digest[:24]}"


def _estimate_processing_seconds(*, source_items: int, estimated_chunks: int, db_tables: int) -> int:
    # Rough heuristic for user-facing ETA before heavy embedding/upsert operations.
    base = 12
    source_cost = source_items * 1
    chunk_cost = int(estimated_chunks * 0.08)
    db_cost = db_tables * 2
    return max(10, base + source_cost + chunk_cost + db_cost)


def _format_eta(seconds: int) -> str:
    minutes, rem = divmod(max(0, int(seconds)), 60)
    if minutes <= 0:
        return f"{rem}s"
    return f"{minutes}m {rem}s"


def _superrag_dependency_error(stage: str, exc: Exception) -> ValueError:
    return ValueError(
        f"superRAG {stage} failed. Confirm OPENAI_API_KEY and local ChromaDB access (or a reachable QDRANT_URL), then re-run `kendr setup status`. Root cause: {exc}"
    )


def _write_mode_artifacts(mode: str, call_number: int, summary: str, payload: dict):
    write_text_file(f"superrag_{mode}_{call_number}.txt", summary)
    write_text_file(f"superrag_{mode}_{call_number}.json", json.dumps(payload, indent=2, ensure_ascii=False))


def _ingestion_event(
    state: dict,
    *,
    session_id: str,
    source_type: str,
    source_ref: str,
    item_count: int,
    chunk_count: int,
    status: str,
    detail: dict,
):
    insert_superrag_ingestion(
        {
            "ingestion_id": f"ing_{uuid.uuid4().hex}",
            "session_id": session_id,
            "run_id": state.get("run_id", ""),
            "source_type": source_type,
            "source_ref": source_ref,
            "item_count": item_count,
            "chunk_count": chunk_count,
            "status": status,
            "detail": detail,
            "created_at": _now_iso(),
        }
    )


def _ingest_local_documents(state: dict, roots: list[str]) -> tuple[list[dict], dict]:
    recursive = bool(state.get("superrag_local_recursive", True))
    include_hidden = bool(state.get("superrag_local_include_hidden", False))
    max_files = max(1, min(int(state.get("superrag_local_max_files", 300) or 300), 3000))
    extensions = {item.lower() for item in _as_list(state.get("superrag_local_extensions"))}
    if not extensions:
        extensions = set(LOCAL_DRIVE_SUPPORTED_EXTENSIONS)

    files, total_size = _discover_local_files(
        roots,
        recursive=recursive,
        include_hidden=include_hidden,
        max_files=max_files,
        extensions=extensions,
    )
    if not files:
        return [], {
            "roots": roots,
            "files": 0,
            "total_size_bytes": 0,
            "note": "No supported files found.",
        }

    docs = parse_documents(
        files,
        continue_on_error=True,
        ocr_images=bool(state.get("superrag_enable_image_ocr", True)),
        ocr_instruction=state.get("superrag_ocr_instruction"),
    )
    normalized: list[dict] = []
    for item in docs:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        normalized.append(
            {
                "source": str(item.get("path", "")),
                "source_type": "local_file",
                "text": str(item.get("text", "") or ""),
                "metadata": {
                    "source_type": "local_file",
                    "document_type": metadata.get("type", "unknown"),
                    "error": metadata.get("error", ""),
                },
            }
        )
    return normalized, {
        "roots": roots,
        "files": len(files),
        "total_size_bytes": total_size,
    }


def _ingest_url_documents(state: dict, urls: list[str]) -> tuple[list[dict], dict]:
    max_pages = max(1, min(int(state.get("superrag_url_max_pages", 20) or 20), 200))
    same_domain = bool(state.get("superrag_url_same_domain", False))
    pages = crawl_urls(urls, max_pages=max_pages, same_domain=same_domain)
    docs: list[dict] = []
    for page in pages:
        text = str(page.get("text", "") or "").strip()
        if not text:
            continue
        docs.append(
            {
                "source": str(page.get("url", "")),
                "source_type": "url",
                "text": text,
                "metadata": {
                    "source_type": "url",
                    "content_type": page.get("content_type", ""),
                    "error": page.get("error", ""),
                },
            }
        )
    return docs, {
        "requested_urls": len(urls),
        "pages_fetched": len(pages),
        "pages_with_text": len(docs),
        "max_pages": max_pages,
    }


def _graph_json(url: str, access_token: str, timeout: int = 45) -> dict:
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _download_url_bytes(url: str, timeout: int = 90) -> bytes:
    request = Request(url, headers={"User-Agent": os.getenv("RESEARCH_USER_AGENT", "superrag/1.0")})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _iter_onedrive_files(access_token: str, onedrive_path: str, max_files: int) -> list[dict]:
    path = str(onedrive_path or "").strip().strip("/")
    if path:
        first_url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{path}:/children?$top=200"
    else:
        first_url = "https://graph.microsoft.com/v1.0/me/drive/root/children?$top=200"

    queue = [first_url]
    files: list[dict] = []
    while queue and len(files) < max_files:
        current = queue.pop(0)
        payload = _graph_json(current, access_token)
        for item in payload.get("value", []) or []:
            if "folder" in item and item.get("id"):
                queue.append(f"https://graph.microsoft.com/v1.0/me/drive/items/{item['id']}/children?$top=200")
                continue
            if "file" not in item:
                continue
            files.append(item)
            if len(files) >= max_files:
                break
        next_link = payload.get("@odata.nextLink")
        if next_link:
            queue.append(next_link)
    return files


def _ingest_onedrive_documents(state: dict, session_stage_dir: Path) -> tuple[list[dict], dict]:
    access_token = get_microsoft_graph_access_token()
    if not access_token:
        raise ValueError("Microsoft Graph access token is required for OneDrive ingestion.")

    max_files = max(1, min(int(state.get("superrag_onedrive_max_files", 200) or 200), 2000))
    max_download_mb = max(1, min(int(state.get("superrag_onedrive_max_download_mb", 25) or 25), 200))
    max_download_bytes = max_download_mb * 1024 * 1024
    onedrive_path = str(state.get("superrag_onedrive_path") or "").strip()

    stage_dir = session_stage_dir / "onedrive"
    stage_dir.mkdir(parents=True, exist_ok=True)

    items = _iter_onedrive_files(access_token, onedrive_path, max_files=max_files)
    docs: list[dict] = []
    skipped_large = 0
    parse_errors = 0

    for index, item in enumerate(items, start=1):
        size = int(item.get("size", 0) or 0)
        if size > max_download_bytes:
            skipped_large += 1
            continue
        download_url = item.get("@microsoft.graph.downloadUrl")
        if not download_url:
            continue

        name = str(item.get("name", f"file_{index}"))
        suffix = Path(name).suffix.lower()
        if suffix and suffix not in LOCAL_DRIVE_SUPPORTED_EXTENSIONS:
            continue

        try:
            data = _download_url_bytes(download_url)
            target = stage_dir / f"{index:05d}_{_safe_slug(Path(name).stem, default='file')}{suffix}"
            target.write_bytes(data)
            parsed = parse_documents(
                [str(target)],
                continue_on_error=True,
                ocr_images=bool(state.get("superrag_enable_image_ocr", True)),
                ocr_instruction=state.get("superrag_ocr_instruction"),
            )[0]
            metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
            if metadata.get("error"):
                parse_errors += 1
            docs.append(
                {
                    "source": f"onedrive://{item.get('id', '')}/{name}",
                    "source_type": "onedrive",
                    "text": str(parsed.get("text", "") or ""),
                    "metadata": {
                        "source_type": "onedrive",
                        "drive_item_id": item.get("id", ""),
                        "name": name,
                        "size": size,
                        "document_type": metadata.get("type", suffix.lstrip(".")),
                        "error": metadata.get("error", ""),
                    },
                }
            )
        except Exception:
            parse_errors += 1

    return docs, {
        "onedrive_path": onedrive_path or "/",
        "items_scanned": len(items),
        "documents_ingested": len(docs),
        "skipped_large_files": skipped_large,
        "parse_errors": parse_errors,
        "max_download_mb": max_download_mb,
    }


def _serialize_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    return json.dumps(value, ensure_ascii=False)


def _scan_database_documents(state: dict) -> tuple[list[dict], dict, dict]:
    db_url = str(state.get("superrag_db_url") or "").strip()
    if not db_url:
        return [], {}, {}

    try:
        from sqlalchemy import MetaData, Table, create_engine, func, inspect, select
    except Exception as exc:
        raise ValueError("Database ingestion requires SQLAlchemy. Install dependency 'sqlalchemy'.") from exc

    sample_rows = max(1, min(int(state.get("superrag_db_sample_rows", 30) or 30), 300))
    max_tables = max(1, min(int(state.get("superrag_db_max_tables", 100) or 100), 1000))
    target_schema = str(state.get("superrag_db_schema") or "").strip() or None
    explicit_tables = set(_as_list(state.get("superrag_db_tables")))

    engine = create_engine(db_url)
    inspector = inspect(engine)
    schemas = [target_schema] if target_schema else [None]

    docs: list[dict] = []
    schema_kb: dict = {"database_url": db_url, "schemas": []}
    analysis = {
        "database_url": db_url,
        "tables_scanned": 0,
        "rows_sampled": 0,
        "estimated_total_rows": 0,
    }

    try:
        for schema in schemas:
            table_names = inspector.get_table_names(schema=schema)
            if explicit_tables:
                table_names = [name for name in table_names if name in explicit_tables]
            table_names = table_names[:max_tables]
            schema_entry = {"schema": schema or "default", "tables": []}

            for table_name in table_names:
                table_obj = Table(table_name, MetaData(), autoload_with=engine, schema=schema)
                columns = inspector.get_columns(table_name, schema=schema)
                pk = inspector.get_pk_constraint(table_name, schema=schema)
                fks = inspector.get_foreign_keys(table_name, schema=schema)

                row_count = 0
                sampled_rows: list[dict] = []
                with engine.connect() as conn:
                    try:
                        row_count = int(conn.execute(select(func.count()).select_from(table_obj)).scalar_one() or 0)
                    except Exception:
                        row_count = 0
                    try:
                        rows = conn.execute(select(table_obj).limit(sample_rows)).fetchall()
                        for row in rows:
                            mapped = {}
                            for key, value in dict(row._mapping).items():
                                mapped[str(key)] = _serialize_value(value)
                            sampled_rows.append(mapped)
                    except Exception:
                        sampled_rows = []

                analysis["tables_scanned"] += 1
                analysis["rows_sampled"] += len(sampled_rows)
                analysis["estimated_total_rows"] += max(0, row_count)

                column_lines = [f"- {col.get('name')} ({col.get('type')})" for col in columns]
                fk_lines = []
                for fk in fks:
                    constrained = ", ".join(fk.get("constrained_columns") or [])
                    referred_table = fk.get("referred_table") or ""
                    referred_cols = ", ".join(fk.get("referred_columns") or [])
                    fk_lines.append(f"- {constrained} -> {referred_table}({referred_cols})")

                schema_text = "\n".join(
                    [
                        f"Database table: {(schema + '.') if schema else ''}{table_name}",
                        f"Estimated rows: {row_count}",
                        f"Primary key: {', '.join(pk.get('constrained_columns') or []) or 'none'}",
                        "Columns:",
                        "\n".join(column_lines) if column_lines else "- none",
                        "Foreign keys:",
                        "\n".join(fk_lines) if fk_lines else "- none",
                    ]
                )
                docs.append(
                    {
                        "source": f"db://{table_name}#schema",
                        "source_type": "database_schema",
                        "text": schema_text,
                        "metadata": {
                            "source_type": "database_schema",
                            "table": table_name,
                            "schema": schema or "",
                            "row_count": row_count,
                        },
                    }
                )

                for idx, row in enumerate(sampled_rows, start=1):
                    docs.append(
                        {
                            "source": f"db://{table_name}#row_{idx}",
                            "source_type": "database_row",
                            "text": f"Table {(schema + '.') if schema else ''}{table_name} sample row {idx}: {json.dumps(row, ensure_ascii=False)}",
                            "metadata": {
                                "source_type": "database_row",
                                "table": table_name,
                                "schema": schema or "",
                                "row_index": idx,
                            },
                        }
                    )

                schema_entry["tables"].append(
                    {
                        "table": table_name,
                        "schema": schema or "",
                        "estimated_rows": row_count,
                        "columns": [{"name": col.get("name"), "type": str(col.get("type"))} for col in columns],
                        "primary_key": pk.get("constrained_columns") or [],
                        "foreign_keys": fks,
                        "sample_rows": sampled_rows,
                    }
                )
            schema_kb["schemas"].append(schema_entry)
    finally:
        try:
            engine.dispose()
        except Exception:
            pass

    return docs, schema_kb, analysis


def _documents_to_records(session_id: str, docs: list[dict], chunk_size: int, overlap: int) -> tuple[list[dict], int]:
    records = []
    chunk_count = 0
    for doc in docs:
        text = str(doc.get("text", "") or "").strip()
        if not text:
            continue
        source = str(doc.get("source", ""))
        payload = dict(doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {})
        payload["session_id"] = session_id
        payload["source"] = source
        payload["source_type"] = payload.get("source_type") or doc.get("source_type", "unknown")

        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        for index, chunk in enumerate(chunks):
            records.append(
                {
                    "id": _stable_record_id(session_id, source, index, chunk),
                    "source": source,
                    "text": chunk,
                    "payload": {**payload, "chunk_index": index},
                }
            )
        chunk_count += len(chunks)
    return records, chunk_count


def _pick_chat_query(state: dict, task_content: str) -> str:
    explicit = str(state.get("superrag_chat_query") or state.get("rag_query") or "").strip()
    if explicit:
        return explicit
    if task_content and task_content.strip():
        return task_content.strip()
    return str(state.get("current_objective") or state.get("user_query") or "").strip()


def _summarize_session(session: dict) -> str:
    source_summary = session.get("source_summary") if isinstance(session.get("source_summary"), dict) else {}
    stats = session.get("stats") if isinstance(session.get("stats"), dict) else {}
    return (
        f"Session: {session.get('session_id', '')}\n"
        f"Collection: {session.get('collection_name', '')}\n"
        f"Status: {session.get('status', '')}\n"
        f"Updated: {session.get('updated_at', '')}\n"
        f"Documents: {stats.get('documents', 0)} | Chunks: {stats.get('chunks', 0)} | Indexed: {stats.get('indexed', 0)}\n"
        f"Sources: {json.dumps(source_summary, ensure_ascii=False)}"
    )


def _source_mix_summary_lines(source_summary: dict) -> list[str]:
    if not isinstance(source_summary, dict) or not source_summary:
        return ["- none"]

    lines: list[str] = []
    local = source_summary.get("local") if isinstance(source_summary.get("local"), dict) else {}
    if local:
        files = int(local.get("files", 0) or 0)
        roots = len(local.get("roots") or []) if isinstance(local.get("roots"), list) else 0
        lines.append(f"- local: {files} file(s) across {roots} root path(s)")

    urls = source_summary.get("urls") if isinstance(source_summary.get("urls"), dict) else {}
    if urls:
        pages = int(urls.get("pages_with_text", 0) or 0)
        requested = int(urls.get("requested_urls", 0) or 0)
        lines.append(f"- urls: {pages} page(s) with text from {requested} seed URL(s)")

    database = source_summary.get("database") if isinstance(source_summary.get("database"), dict) else {}
    if database:
        tables = int(database.get("tables_scanned", 0) or 0)
        sampled = int(database.get("rows_sampled", 0) or 0)
        lines.append(f"- database: {tables} table(s) scanned and {sampled} sampled row(s)")

    onedrive = source_summary.get("onedrive") if isinstance(source_summary.get("onedrive"), dict) else {}
    if onedrive:
        docs = int(onedrive.get("documents_ingested", 0) or 0)
        scanned = int(onedrive.get("items_scanned", 0) or 0)
        lines.append(f"- onedrive: {docs} document(s) ingested from {scanned} scanned item(s)")

    return lines or ["- none"]


def _render_sources_section(citations: list[dict]) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        source = str(citation.get("source", "") or "").strip()
        if not source or source in seen:
            continue
        seen.add(source)
        score = citation.get("score")
        if isinstance(score, (int, float)):
            lines.append(f"- {source} (score={float(score):.3f})")
        else:
            lines.append(f"- {source}")
    if not lines:
        return ""
    return "Sources:\n" + "\n".join(lines)


def _ensure_sources_section(answer: str, citations: list[dict]) -> str:
    answer_text = str(answer or "").strip()
    sources_block = _render_sources_section(citations)
    if not sources_block:
        return answer_text
    if "sources:" in answer_text.lower():
        return answer_text
    if not answer_text:
        return sources_block
    return f"{answer_text}\n\n{sources_block}"


def _build_summary_next_steps(session_id: str) -> list[str]:
    return [
        f"Reuse superrag_mode=chat with superrag_session_id={session_id} to ask focused questions against this indexed corpus.",
        "Validate the highest-impact answers against the cited source files or URLs before sharing them externally.",
        "Rebuild the session after adding new documents so retrieval stays aligned with the latest evidence.",
    ]


def _hit_metadata(hit: dict) -> dict:
    if isinstance(hit.get("metadata"), dict):
        return hit["metadata"]
    if isinstance(hit.get("payload"), dict):
        return hit["payload"]
    return {}


def _hit_source(hit: dict, fallback_rank: int = 0) -> str:
    meta = _hit_metadata(hit)
    source = str(hit.get("source") or meta.get("source") or "").strip()
    if source:
        return source
    return f"unknown://superrag-hit/{fallback_rank or 0}"


def _hit_score(hit: dict) -> float | None:
    try:
        value = hit.get("score")
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _hit_dedup_key(hit: dict, fallback_rank: int = 0) -> tuple[str, str]:
    meta = _hit_metadata(hit)
    source = _hit_source(hit, fallback_rank=fallback_rank)
    chunk_index = str(meta.get("chunk_index", "") or "").strip()
    if chunk_index:
        return source, chunk_index
    normalized_text = " ".join(str(hit.get("text", "") or "").split())[:240]
    return source, normalized_text


def _select_chat_hits(raw_hits: list[dict], *, top_k: int, per_source_limit: int) -> tuple[list[dict], dict]:
    enumerated_hits = list(enumerate(raw_hits, start=1))
    ranked_hits = sorted(
        enumerated_hits,
        key=lambda item: (
            _hit_score(item[1]) is None,
            -(_hit_score(item[1]) or 0.0),
            item[0],
        ),
    )

    deduped_hits: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    for original_rank, hit in ranked_hits:
        dedup_key = _hit_dedup_key(hit, fallback_rank=original_rank)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        deduped_hits.append(hit)

    selected_hits: list[dict] = []
    deferred_hits: list[dict] = []
    source_counts: dict[str, int] = {}
    for hit in deduped_hits:
        source = _hit_source(hit)
        if source_counts.get(source, 0) == 0 and len(selected_hits) < top_k:
            selected_hits.append(hit)
            source_counts[source] = 1
        else:
            deferred_hits.append(hit)

    for hit in deferred_hits:
        if len(selected_hits) >= top_k:
            break
        source = _hit_source(hit)
        if source_counts.get(source, 0) >= per_source_limit:
            continue
        selected_hits.append(hit)
        source_counts[source] = source_counts.get(source, 0) + 1

    retrieval_summary = {
        "strategy": "score_desc_source_diversity",
        "raw_hit_count": len(raw_hits),
        "deduped_hit_count": len(deduped_hits),
        "selected_hit_count": len(selected_hits),
        "distinct_source_count": len(source_counts),
        "per_source_limit": per_source_limit,
        "selected_sources": list(source_counts.keys()),
    }
    return selected_hits, retrieval_summary


def _build_mode(state: dict, task_content: str, call_number: int) -> tuple[str, dict]:
    requested_session = str(state.get("superrag_session_id") or _extract_session_from_text(task_content) or "").strip()
    if bool(state.get("superrag_new_session", False)):
        requested_session = f"{_safe_slug(requested_session or _default_session_id(state), default='session')}_{datetime.now(timezone.utc).strftime('%H%M%S')}"

    session = _ensure_session(state, requested_session_id=requested_session, create_if_missing=True)
    session_id = session.get("session_id", _default_session_id(state))
    collection_name = session.get("collection_name", _collection_for_session(session_id))

    stage_dir = Path(state.get("run_output_dir") or "output").resolve() / "superrag" / _safe_slug(session_id, "session")
    stage_dir.mkdir(parents=True, exist_ok=True)

    query_text = " ".join(
        [
            str(state.get("user_query", "")),
            str(state.get("current_objective", "")),
            str(task_content or ""),
        ]
    )

    raw_urls = _as_list(state.get("superrag_urls"))
    if not raw_urls:
        raw_urls = _extract_urls(query_text)

    db_url = str(state.get("superrag_db_url") or "").strip() or _extract_db_url(query_text)

    local_roots = _normalize_roots(
        state.get("superrag_local_paths") or state.get("superrag_paths") or [],
        str(state.get("working_directory") or "."),
    )
    if not local_roots and bool(state.get("superrag_include_working_directory", True)):
        local_roots = [str(Path(state.get("working_directory") or ".").resolve())]

    use_onedrive = bool(state.get("superrag_onedrive_enabled", False) or state.get("superrag_onedrive_path"))

    # Stage 1: preflight analysis for ETA.
    preflight_local_files, preflight_local_size = _discover_local_files(
        local_roots,
        recursive=bool(state.get("superrag_local_recursive", True)),
        include_hidden=bool(state.get("superrag_local_include_hidden", False)),
        max_files=max(1, min(int(state.get("superrag_local_max_files", 300) or 300), 3000)),
        extensions=set(LOCAL_DRIVE_SUPPORTED_EXTENSIONS),
    )
    preflight_db_tables = 0
    if db_url:
        try:
            from sqlalchemy import create_engine, inspect

            engine = create_engine(db_url)
            inspector = inspect(engine)
            table_names = inspector.get_table_names(schema=str(state.get("superrag_db_schema") or "").strip() or None)
            preflight_db_tables = len(table_names)
            engine.dispose()
        except Exception:
            preflight_db_tables = 0

    estimated_items = len(preflight_local_files) + len(raw_urls)
    rough_chunks = int(max(0, preflight_local_size) / 3000) + (len(raw_urls) * 8) + (preflight_db_tables * 20)
    eta_seconds = _estimate_processing_seconds(
        source_items=estimated_items,
        estimated_chunks=rough_chunks,
        db_tables=preflight_db_tables,
    )
    log_task_update(
        "superRAG",
        (
            "Preflight analysis complete. "
            f"Estimated processing time: {_format_eta(eta_seconds)} for about {max(1, rough_chunks)} chunks. "
            "Please be patient while ingestion and indexing are running."
        ),
    )

    all_docs: list[dict] = []
    source_summary: dict = {}

    if local_roots:
        log_task_update("superRAG", f"Ingesting local content from {len(local_roots)} root path(s).")
        local_docs, local_report = _ingest_local_documents(state, local_roots)
        all_docs.extend(local_docs)
        source_summary["local"] = local_report
        local_chunk_count = sum(len(chunk_text(str(item.get("text", "") or ""))) for item in local_docs)
        _ingestion_event(
            state,
            session_id=session_id,
            source_type="local",
            source_ref=",".join(local_roots[:4]),
            item_count=len(local_docs),
            chunk_count=local_chunk_count,
            status="ok",
            detail=local_report,
        )

    if raw_urls:
        log_task_update("superRAG", f"Crawling URL sources ({len(raw_urls)} seed URL(s)).")
        url_docs, url_report = _ingest_url_documents(state, raw_urls)
        all_docs.extend(url_docs)
        source_summary["urls"] = url_report
        url_chunk_count = sum(len(chunk_text(str(item.get("text", "") or ""))) for item in url_docs)
        _ingestion_event(
            state,
            session_id=session_id,
            source_type="url",
            source_ref=",".join(raw_urls[:4]),
            item_count=len(url_docs),
            chunk_count=url_chunk_count,
            status="ok",
            detail=url_report,
        )

    schema_kb = {}
    db_analysis = {}
    if db_url:
        log_task_update("superRAG", "Scanning database schema and sampling rows for knowledge indexing.")
        db_docs, schema_kb, db_analysis = _scan_database_documents({**state, "superrag_db_url": db_url})
        all_docs.extend(db_docs)
        source_summary["database"] = db_analysis
        db_chunk_count = sum(len(chunk_text(str(item.get("text", "") or ""))) for item in db_docs)
        _ingestion_event(
            state,
            session_id=session_id,
            source_type="database",
            source_ref=db_url,
            item_count=len(db_docs),
            chunk_count=db_chunk_count,
            status="ok",
            detail=db_analysis,
        )

    if use_onedrive:
        log_task_update("superRAG", "Ingesting OneDrive files from Microsoft Graph.")
        one_docs, one_report = _ingest_onedrive_documents(state, stage_dir)
        all_docs.extend(one_docs)
        source_summary["onedrive"] = one_report
        one_chunk_count = sum(len(chunk_text(str(item.get("text", "") or ""))) for item in one_docs)
        _ingestion_event(
            state,
            session_id=session_id,
            source_type="onedrive",
            source_ref=str(state.get("superrag_onedrive_path") or "/"),
            item_count=len(one_docs),
            chunk_count=one_chunk_count,
            status="ok",
            detail=one_report,
        )

    if not all_docs:
        raise ValueError(
            "No ingested documents were found. Provide at least one source via superrag_local_paths, superrag_urls, superrag_db_url, or OneDrive settings."
        )

    log_task_update("superRAG", f"Preparing vector chunks from {len(all_docs)} document(s).")
    chunk_size = max(200, min(int(state.get("superrag_chunk_size", 1000) or 1000), 4000))
    overlap = max(0, min(int(state.get("superrag_chunk_overlap", 120) or 120), chunk_size // 2))
    records, total_chunks = _documents_to_records(session_id, all_docs, chunk_size=chunk_size, overlap=overlap)

    log_task_update(
        "superRAG",
        (
            f"Indexing {len(records)} chunk(s) into vector collection '{collection_name}'. "
            "This stage can take some time for larger datasets."
        ),
    )
    try:
        index_result = upsert_memory_records(records, collection_name=collection_name)
    except Exception as exc:  # noqa: BLE001
        raise _superrag_dependency_error("indexing", exc) from exc

    now = _now_iso()
    stats = {
        "documents": len(all_docs),
        "chunks": total_chunks,
        "indexed": int(index_result.get("indexed", 0) or 0),
        "collection": collection_name,
        "eta_seconds": eta_seconds,
    }
    updated = {
        "session_id": session_id,
        "collection_name": collection_name,
        "owner_key": _owner_key(state),
        "title": str(state.get("superrag_session_title") or session.get("title") or f"superRAG session {session_id}"),
        "status": "ready",
        "source_summary": source_summary,
        "stats": stats,
        "schema_kb": schema_kb,
        "created_at": session.get("created_at", now),
        "updated_at": now,
        "last_used_at": now,
    }
    upsert_superrag_session(updated)

    resolved_session = get_superrag_session(session_id) or updated
    source_mix_summary = _source_mix_summary_lines(source_summary)
    coverage_summary = [
        f"Session: {session_id}",
        f"Collection: {collection_name}",
        f"Documents indexed: {stats['documents']}",
        f"Chunks indexed: {stats['indexed']}",
        *source_mix_summary,
    ]
    recommended_next_steps = _build_summary_next_steps(session_id)
    summary = render_phase0_report(
        title="superRAG Build Summary",
        objective=str(state.get("user_query") or task_content or f"Build superRAG session {session_id}"),
        findings=(
            f"superRAG build completed and session '{session_id}' is ready for retrieval-backed chat. "
            f"The vector collection contains {stats['indexed']} indexed chunk(s) across {stats['documents']} document(s)."
        ),
        coverage_lines=coverage_summary,
        next_steps=recommended_next_steps,
        sources_lines=[item.get("source", "") for item in all_docs[:15]],
    )
    payload = {
        "mode": "build",
        "session": resolved_session,
        "source_summary": source_summary,
        "source_mix_summary": source_mix_summary,
        "coverage_summary": coverage_summary,
        "recommended_next_steps": recommended_next_steps,
        "index_result": index_result,
        "stats": stats,
        "sample_sources": [item.get("source", "") for item in all_docs[:15]],
    }

    state["superrag_active_session_id"] = session_id
    state["superrag_session_id"] = session_id
    state["superrag_session"] = resolved_session
    state["superrag_build_report"] = payload
    state["superrag_status"] = "ready"

    _write_mode_artifacts("build", call_number, summary, payload)
    return summary, payload


def _list_mode(state: dict, call_number: int) -> tuple[str, dict]:
    owner = _owner_key(state)
    include_all = bool(state.get("superrag_list_all", False))
    limit = max(1, min(int(state.get("superrag_list_limit", 20) or 20), 200))
    sessions = list_superrag_sessions(limit=limit, owner_key="" if include_all else owner)

    lines = [f"superRAG sessions ({len(sessions)}):"]
    for item in sessions:
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        lines.append(
            f"- {item.get('session_id', '')} | status={item.get('status', '')} | docs={stats.get('documents', 0)} | chunks={stats.get('chunks', 0)} | updated={item.get('updated_at', '')}"
        )
    if not sessions:
        lines.append("- none")

    summary = "\n".join(lines)
    payload = {
        "mode": "list",
        "owner_key": owner,
        "include_all": include_all,
        "sessions": sessions,
    }
    state["superrag_sessions"] = sessions
    state["superrag_status"] = "ready"
    _write_mode_artifacts("list", call_number, summary, payload)
    return summary, payload


def _switch_mode(state: dict, task_content: str, call_number: int) -> tuple[str, dict]:
    target = str(
        state.get("superrag_session_id")
        or state.get("superrag_switch_to")
        or _extract_session_from_text(task_content)
        or _extract_session_from_text(state.get("user_query", ""))
        or ""
    ).strip()
    if not target:
        raise ValueError("switch mode requires superrag_session_id (or mention 'session <id>' in the query).")

    session = get_superrag_session(target)
    if not session:
        raise ValueError(f"superRAG session not found: {target}")

    now = _now_iso()
    upsert_superrag_session(
        {
            "session_id": session.get("session_id", target),
            "collection_name": session.get("collection_name", _collection_for_session(target)),
            "owner_key": session.get("owner_key", _owner_key(state)),
            "title": session.get("title", f"superRAG session {target}"),
            "status": session.get("status", "ready"),
            "source_summary": session.get("source_summary", {}),
            "stats": session.get("stats", {}),
            "schema_kb": session.get("schema_kb", {}),
            "created_at": session.get("created_at", now),
            "updated_at": now,
            "last_used_at": now,
        }
    )
    resolved = get_superrag_session(target) or session

    state["superrag_active_session_id"] = target
    state["superrag_session_id"] = target
    state["superrag_session"] = resolved
    state["superrag_status"] = "ready"

    summary = (
        f"Active superRAG session switched to '{target}'.\n"
        f"Collection: {resolved.get('collection_name', '')}\n"
        "Use superrag_mode=chat with this session to query indexed knowledge."
    )
    payload = {"mode": "switch", "session": resolved}
    _write_mode_artifacts("switch", call_number, summary, payload)
    return summary, payload


def _status_mode(state: dict, task_content: str, call_number: int) -> tuple[str, dict]:
    session_id = str(
        state.get("superrag_session_id")
        or state.get("superrag_active_session_id")
        or _extract_session_from_text(task_content)
        or _extract_session_from_text(state.get("user_query", ""))
        or ""
    ).strip()
    if not session_id:
        raise ValueError("status mode requires an active superrag_session_id.")

    session = get_superrag_session(session_id)
    if not session:
        raise ValueError(f"superRAG session not found: {session_id}")

    ingestions = list_superrag_ingestions(session_id=session_id, limit=30)
    chats = list_superrag_chat_messages(session_id=session_id, limit=10)

    summary = _summarize_session(session)
    payload = {
        "mode": "status",
        "session": session,
        "ingestions": ingestions,
        "recent_chat_messages": chats,
    }
    state["superrag_session"] = session
    state["superrag_status"] = "ready"
    _write_mode_artifacts("status", call_number, summary, payload)
    return summary, payload


def _chat_mode(state: dict, task_content: str, call_number: int) -> tuple[str, dict]:
    session_id = str(
        state.get("superrag_session_id")
        or state.get("superrag_active_session_id")
        or _extract_session_from_text(task_content)
        or _extract_session_from_text(state.get("user_query", ""))
        or ""
    ).strip()
    if not session_id:
        raise ValueError("chat mode requires superrag_session_id or an active superRAG session.")

    session = get_superrag_session(session_id)
    if not session:
        raise ValueError(f"superRAG session not found: {session_id}")

    collection = session.get("collection_name") or _collection_for_session(session_id)
    query = _pick_chat_query(state, task_content)
    if not query:
        raise ValueError("chat mode requires a non-empty question.")

    top_k = max(1, min(int(state.get("superrag_top_k", 8) or 8), 40))
    per_source_limit = max(1, min(int(state.get("superrag_max_hits_per_source", 2) or 2), 5))
    try:
        raw_hits = search_memory(query, top_k=max(top_k * 3, top_k), collection_name=collection)
    except Exception as exc:  # noqa: BLE001
        raise _superrag_dependency_error("chat retrieval", exc) from exc
    hits, retrieval_summary = _select_chat_hits(raw_hits, top_k=top_k, per_source_limit=per_source_limit)
    context_blocks = []
    citations = []
    for index, hit in enumerate(hits, start=1):
        meta = _hit_metadata(hit)
        source = _hit_source(hit, fallback_rank=index)
        text = str(hit.get("text", "") or "")
        score = hit.get("score")
        citations.append(
            {
                "rank": index,
                "source": source,
                "score": score,
                "source_type": meta.get("source_type", ""),
            }
        )
        context_blocks.append(
            f"[{index}] source={source} score={score}\n{text[:1800]}"
        )

    if not context_blocks:
        answer = (
            "No indexed context was found for this query in the selected superRAG session. "
            "Try rebuilding the session with more sources, or ask a more specific question."
        )
    else:
        prompt = f"""
You are the superRAG session chat assistant.

Session:
{json.dumps({'session_id': session_id, 'collection': collection, 'title': session.get('title', '')}, ensure_ascii=False)}

User question:
{query}

Retrieved context chunks:
{chr(10).join(context_blocks)}

Rules:
- Base your answer on the retrieved context only.
- If the context is insufficient, explicitly say what is missing.
- Add a short "Sources" section listing source identifiers used.
""".strip()
        answer = llm_text(prompt)

    now = _now_iso()
    insert_superrag_chat_message(
        {
            "message_id": f"chat_{uuid.uuid4().hex}",
            "session_id": session_id,
            "run_id": state.get("run_id", ""),
            "role": "user",
            "content": query,
            "citations": [],
            "created_at": now,
        }
    )
    answer = _ensure_sources_section(answer, citations)
    insert_superrag_chat_message(
        {
            "message_id": f"chat_{uuid.uuid4().hex}",
            "session_id": session_id,
            "run_id": state.get("run_id", ""),
            "role": "assistant",
            "content": answer,
            "citations": citations,
            "created_at": _now_iso(),
        }
    )

    upsert_superrag_session(
        {
            "session_id": session_id,
            "collection_name": collection,
            "owner_key": session.get("owner_key", _owner_key(state)),
            "title": session.get("title", f"superRAG session {session_id}"),
            "status": "ready",
            "source_summary": session.get("source_summary", {}),
            "stats": session.get("stats", {}),
            "schema_kb": session.get("schema_kb", {}),
            "created_at": session.get("created_at", now),
            "updated_at": _now_iso(),
            "last_used_at": _now_iso(),
        }
    )

    summary = answer
    payload = {
        "mode": "chat",
        "session_id": session_id,
        "collection": collection,
        "query": query,
        "hits": hits,
        "raw_hit_count": len(raw_hits),
        "hit_count": len(hits),
        "citations": citations,
        "answer": answer,
        "source_summary": session.get("source_summary", {}),
        "source_mix_summary": _source_mix_summary_lines(session.get("source_summary", {})),
        "retrieval_summary": retrieval_summary,
    }
    state["superrag_active_session_id"] = session_id
    state["superrag_session_id"] = session_id
    state["superrag_chat_result"] = payload
    state["superrag_status"] = "ready"
    _write_mode_artifacts("chat", call_number, summary, payload)
    return summary, payload


def superrag_agent(state):
    _, task_content, _ = begin_agent_session(state, "superrag_agent")
    state["superrag_calls"] = state.get("superrag_calls", 0) + 1
    call_number = state["superrag_calls"]

    mode = _infer_mode(state, task_content)
    log_task_update("superRAG", f"Mode selected: {mode} (call #{call_number}).")

    if mode == "list":
        summary, payload = _list_mode(state, call_number)
    elif mode == "switch":
        summary, payload = _switch_mode(state, task_content, call_number)
    elif mode == "status":
        summary, payload = _status_mode(state, task_content, call_number)
    elif mode == "chat":
        summary, payload = _chat_mode(state, task_content, call_number)
    else:
        summary, payload = _build_mode(state, task_content, call_number)

    state["superrag_mode"] = mode
    state["superrag_last_result"] = payload
    state["draft_response"] = summary

    return publish_agent_output(
        state,
        "superrag_agent",
        summary,
        f"superrag_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "report_agent"],
    )
