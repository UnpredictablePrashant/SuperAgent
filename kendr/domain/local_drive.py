from __future__ import annotations

from datetime import UTC, datetime
import os
import re
from pathlib import Path
from typing import Any, Mapping

from tasks.research_infra import LOCAL_DRIVE_SUPPORTED_EXTENSIONS, chunk_text, search_memory, upsert_memory_records


DEFAULT_EXTENSION_HANDLER_REGISTRY: dict[str, str] = {
    ".txt": "document_ingestion_agent",
    ".md": "document_ingestion_agent",
    ".json": "document_ingestion_agent",
    ".html": "document_ingestion_agent",
    ".htm": "document_ingestion_agent",
    ".csv": "document_ingestion_agent",
    ".pdf": "document_ingestion_agent",
    ".doc": "document_ingestion_agent",
    ".docx": "document_ingestion_agent",
    ".xls": "document_ingestion_agent",
    ".xlsx": "excel_agent",
    ".xlsm": "excel_agent",
    ".ppt": "document_ingestion_agent",
    ".pptx": "document_ingestion_agent",
    ".pptm": "document_ingestion_agent",
    ".png": "ocr_agent",
    ".jpg": "ocr_agent",
    ".jpeg": "ocr_agent",
    ".bmp": "ocr_agent",
    ".gif": "ocr_agent",
    ".webp": "ocr_agent",
    ".tif": "ocr_agent",
    ".tiff": "ocr_agent",
}


def extension_handler_registry(
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    registry = dict(DEFAULT_EXTENSION_HANDLER_REGISTRY)
    if not isinstance(overrides, Mapping):
        return registry
    for raw_extension, raw_handler in overrides.items():
        extension = f".{str(raw_extension or '').strip().lower().lstrip('.')}"
        handler = str(raw_handler or "").strip()
        if not extension or extension == "." or not handler:
            continue
        registry[extension] = handler
    return registry


def route_files_by_handler(
    file_paths: list[str],
    *,
    registry: Mapping[str, str] | None = None,
    default_handler: str = "document_ingestion_agent",
) -> dict[str, list[str]]:
    selected_registry = extension_handler_registry(registry)
    routes: dict[str, list[str]] = {}
    for raw_path in file_paths or []:
        path = str(raw_path or "").strip()
        if not path:
            continue
        extension = Path(path).suffix.lower()
        handler = selected_registry.get(extension, default_handler)
        if not handler:
            continue
        routes.setdefault(handler, []).append(path)
    return routes


def unknown_extensions_from_manifest(
    manifest: Mapping[str, Any] | None,
    *,
    registry: Mapping[str, str] | None = None,
) -> list[str]:
    selected_registry = extension_handler_registry(registry)
    unknown: set[str] = set()
    if not isinstance(manifest, Mapping):
        return []
    files = manifest.get("files", [])
    if not isinstance(files, list):
        return []
    for item in files:
        if not isinstance(item, Mapping):
            continue
        extension = str(item.get("extension", "") or "").strip().lower()
        if extension and extension not in selected_registry:
            unknown.add(extension)
    return sorted(unknown)


def resolve_paths(raw_paths: str | list[str] | None, working_directory: str | None = None) -> list[str]:
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


def normalize_extension_set(raw_extensions: str | list[str] | None) -> set[str]:
    if isinstance(raw_extensions, str):
        items = [item.strip() for item in raw_extensions.split(",")]
    elif isinstance(raw_extensions, list):
        items = [str(item).strip() for item in raw_extensions]
    else:
        items = []
    normalized = {f".{item.lower().lstrip('.')}" for item in items if item}
    return normalized or set(LOCAL_DRIVE_SUPPORTED_EXTENSIONS)


def discover_local_drive_files(
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


def _is_hidden_path(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _iso_timestamp(value: float) -> str:
    try:
        return datetime.fromtimestamp(value, UTC).isoformat()
    except Exception:
        return ""


def _relative_path(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
        text = str(relative).replace("\\", "/")
        return text or "."
    except Exception:
        return path.name or str(path)


def _manifest_entry(
    path: Path,
    *,
    root: Path,
    entry_type: str,
    selected_for_processing: bool | None = None,
    exclusion_reason: str = "",
) -> dict[str, Any]:
    stat = path.stat()
    relative_path = _relative_path(root, path)
    return {
        "path": str(path),
        "root": str(root),
        "relative_path": relative_path,
        "name": path.name or str(path),
        "entry_type": entry_type,
        "depth": 0 if relative_path == "." else len(Path(relative_path).parts),
        "extension": path.suffix.lower() if path.is_file() else "",
        "size_bytes": int(stat.st_size) if path.is_file() else 0,
        "modified_at": _iso_timestamp(float(stat.st_mtime)),
        "created_at": _iso_timestamp(float(stat.st_ctime)),
        "is_hidden": _is_hidden_path(path),
        "readable": bool(os.access(path, os.R_OK)),
        "selected_for_processing": selected_for_processing,
        "exclusion_reason": exclusion_reason,
    }


def scan_local_drive_tree(
    roots: list[str],
    *,
    recursive: bool,
    include_hidden: bool,
    max_files: int,
    allowed_extensions: set[str],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    folders: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    selected_files: list[str] = []
    seen: set[str] = set()
    truncated = False

    def _record(entry: dict[str, Any]) -> None:
        path_key = str(entry.get("path", "")).strip()
        if not path_key or path_key in seen:
            return
        seen.add(path_key)
        entries.append(entry)
        if entry.get("entry_type") == "directory":
            folders.append(entry)
        elif entry.get("entry_type") == "file":
            files.append(entry)

    def _record_file(path: Path, *, root: Path) -> None:
        nonlocal truncated
        suffix = path.suffix.lower()
        selected = False
        exclusion_reason = ""
        if suffix not in allowed_extensions:
            exclusion_reason = "unsupported_extension"
        elif len(selected_files) >= max_files:
            exclusion_reason = "max_files_limit"
            truncated = True
        else:
            selected = True
            selected_files.append(str(path))
        _record(
            _manifest_entry(
                path,
                root=root,
                entry_type="file",
                selected_for_processing=selected,
                exclusion_reason=exclusion_reason,
            )
        )

    for root_item in roots:
        root = Path(root_item).expanduser().resolve()
        if not root.exists():
            continue
        if root.is_file():
            if include_hidden or not _is_hidden_path(root):
                _record_file(root, root=root.parent if root.parent.exists() else root)
            continue
        if not root.is_dir():
            continue

        _record(_manifest_entry(root, root=root, entry_type="directory"))

        if recursive:
            for current_root, dirnames, filenames in os.walk(root, topdown=True):
                current_path = Path(current_root)
                dirnames.sort()
                filenames.sort()
                if not include_hidden:
                    dirnames[:] = [name for name in dirnames if not name.startswith(".")]
                    filenames = [name for name in filenames if not name.startswith(".")]
                for dirname in dirnames:
                    dir_path = current_path / dirname
                    _record(_manifest_entry(dir_path, root=root, entry_type="directory"))
                for filename in filenames:
                    file_path = current_path / filename
                    _record_file(file_path, root=root)
        else:
            children = sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
            for child in children:
                if not include_hidden and child.name.startswith("."):
                    continue
                if child.is_dir():
                    _record(_manifest_entry(child, root=root, entry_type="directory"))
                elif child.is_file():
                    _record_file(child, root=root)

    return {
        "roots": roots,
        "recursive": recursive,
        "include_hidden": include_hidden,
        "max_files": max_files,
        "allowed_extensions": sorted(allowed_extensions),
        "selected_files": selected_files,
        "entries": entries,
        "folders": folders,
        "files": files,
        "entry_count": len(entries),
        "folder_count": len(folders),
        "file_count": len(files),
        "selected_file_count": len(selected_files),
        "excluded_file_count": len([item for item in files if not item.get("selected_for_processing")]),
        "truncated": truncated,
    }


def merge_documents(existing: list[dict], incoming: list[dict]) -> list[dict]:
    by_path = {}
    for item in existing or []:
        if isinstance(item, dict):
            by_path[str(item.get("path", ""))] = item
    for item in incoming or []:
        if isinstance(item, dict):
            by_path[str(item.get("path", ""))] = item
    return [item for key, item in sorted(by_path.items()) if key]


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip()).strip("_").lower()
    return slug[:64] or "document"


def textual_sources_for_memory(state: dict[str, Any]) -> list[dict]:
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


def maybe_upsert_memory(state: dict[str, Any], records: list[dict]):
    try:
        result = upsert_memory_records(records)
        state["memory_index_result"] = result
        return result
    except Exception as exc:
        state["memory_index_error"] = str(exc)
        return {"indexed": 0, "collection": "unavailable", "error": str(exc)}


def maybe_search_memory(state: dict[str, Any], query: str, top_k: int = 5) -> list[dict]:
    try:
        return search_memory(query, top_k=top_k)
    except Exception as exc:
        state["memory_search_error"] = str(exc)
        return []
