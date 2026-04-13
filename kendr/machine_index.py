from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import platform
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_DEFAULT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".kendr",
}

_KNOWN_TOOLS = [
    "docker",
    "git",
    "python",
    "python3",
    "node",
    "npm",
    "code",
    "kubectl",
    "terraform",
]

_WINDOWS_UNINSTALL_ROOTS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kendr_dir(working_directory: str) -> Path:
    root = Path(str(working_directory or ".")).expanduser().resolve()
    path = root / ".kendr"
    path.mkdir(parents=True, exist_ok=True)
    return path


def machine_index_db_path(working_directory: str) -> Path:
    return _kendr_dir(working_directory) / "machine_index.sqlite"


def software_inventory_path(working_directory: str) -> Path:
    return _kendr_dir(working_directory) / "software_inventory.json"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def ensure_machine_index_schema(working_directory: str) -> Path:
    db_path = machine_index_db_path(working_directory)
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_index (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                file_hash TEXT NOT NULL,
                file_type TEXT NOT NULL,
                root_path TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                change_type TEXT NOT NULL,
                path TEXT NOT NULL,
                old_size INTEGER,
                new_size INTEGER,
                old_mtime_ns INTEGER,
                new_mtime_ns INTEGER,
                detected_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS machine_sync_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.commit()
    return db_path


def _detect_file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".rb", ".php", ".c", ".cpp", ".h"}:
        return "code"
    if suffix in {".md", ".txt", ".rst", ".log"}:
        return "text"
    if suffix in {".json", ".yaml", ".yml", ".toml", ".ini", ".xml"}:
        return "config"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}:
        return "image"
    if suffix in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}:
        return "document"
    return "other"


def _hash_file(path: Path) -> str:
    size = path.stat().st_size
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        if size <= 1_000_000:
            h.update(handle.read())
        else:
            head = handle.read(524_288)
            handle.seek(max(size - 524_288, 0))
            tail = handle.read(524_288)
            h.update(head)
            h.update(tail)
            h.update(str(size).encode("utf-8"))
    return h.hexdigest()


def _normalize_roots(roots: list[str], working_directory: str) -> list[Path]:
    resolved: list[Path] = []
    if not roots:
        roots = [working_directory]
    for item in roots:
        raw = str(item or "").strip()
        if not raw:
            continue
        try:
            root = Path(raw).expanduser().resolve()
        except Exception:
            continue
        if root.exists() and root.is_dir():
            resolved.append(root)
    unique = []
    seen = set()
    for root in resolved:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _iter_files(root: Path, skip_dirs: set[str]) -> list[Path]:
    files: list[Path] = []
    for current_root, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in skip_dirs]
        cur = Path(current_root)
        for name in names:
            candidate = cur / name
            try:
                if candidate.is_file():
                    files.append(candidate)
            except Exception:
                continue
    return files


def run_file_index_sync(
    *,
    working_directory: str,
    roots: list[str] | None = None,
    max_files: int = 250_000,
) -> dict[str, Any]:
    db_path = ensure_machine_index_schema(working_directory)
    scan_roots = _normalize_roots(list(roots or []), working_directory)
    root_strs = [str(root) for root in scan_roots]
    skip_dirs = set(_DEFAULT_SKIP_DIRS)

    run_started = _utc_now()
    scanned = 0
    created = 0
    modified = 0
    deleted = 0
    errors = 0
    seen_paths: set[str] = set()

    with _connect(db_path) as conn:
        for root in scan_roots:
            for path in _iter_files(root, skip_dirs):
                if scanned >= max_files:
                    break
                scanned += 1
                path_str = str(path)
                seen_paths.add(path_str)
                try:
                    stat = path.stat()
                    size = int(stat.st_size)
                    mtime_ns = int(stat.st_mtime_ns)
                    file_hash = _hash_file(path)
                    file_type = _detect_file_type(path)
                except Exception:
                    errors += 1
                    continue

                row = conn.execute(
                    "SELECT size, mtime_ns, file_hash FROM file_index WHERE path = ?",
                    (path_str,),
                ).fetchone()
                if row is None:
                    created += 1
                    conn.execute(
                        """
                        INSERT INTO file_index(path, size, mtime_ns, file_hash, file_type, root_path, last_seen_at)
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (path_str, size, mtime_ns, file_hash, file_type, str(root), run_started),
                    )
                    conn.execute(
                        """
                        INSERT INTO file_changes(change_type, path, old_size, new_size, old_mtime_ns, new_mtime_ns, detected_at)
                        VALUES('created', ?, NULL, ?, NULL, ?, ?)
                        """,
                        (path_str, size, mtime_ns, run_started),
                    )
                else:
                    old_size = int(row["size"])
                    old_mtime_ns = int(row["mtime_ns"])
                    old_hash = str(row["file_hash"])
                    changed = old_size != size or old_mtime_ns != mtime_ns or old_hash != file_hash
                    if changed:
                        modified += 1
                        conn.execute(
                            """
                            INSERT INTO file_changes(change_type, path, old_size, new_size, old_mtime_ns, new_mtime_ns, detected_at)
                            VALUES('modified', ?, ?, ?, ?, ?, ?)
                            """,
                            (path_str, old_size, size, old_mtime_ns, mtime_ns, run_started),
                        )
                    conn.execute(
                        """
                        UPDATE file_index
                        SET size = ?, mtime_ns = ?, file_hash = ?, file_type = ?, root_path = ?, last_seen_at = ?
                        WHERE path = ?
                        """,
                        (size, mtime_ns, file_hash, file_type, str(root), run_started, path_str),
                    )
            if scanned >= max_files:
                break

        if root_strs:
            placeholders = ",".join("?" for _ in root_strs)
            query = f"SELECT path, size, mtime_ns FROM file_index WHERE root_path IN ({placeholders})"
            candidates = conn.execute(query, tuple(root_strs)).fetchall()
            for row in candidates:
                path_str = str(row["path"])
                if path_str in seen_paths:
                    continue
                deleted += 1
                conn.execute(
                    """
                    INSERT INTO file_changes(change_type, path, old_size, new_size, old_mtime_ns, new_mtime_ns, detected_at)
                    VALUES('deleted', ?, ?, NULL, ?, NULL, ?)
                    """,
                    (path_str, int(row["size"]), int(row["mtime_ns"]), run_started),
                )
                conn.execute("DELETE FROM file_index WHERE path = ?", (path_str,))

        conn.execute(
            """
            INSERT INTO machine_sync_meta(key, value) VALUES('file_index_last_synced', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (run_started,),
        )
        conn.commit()

    return {
        "db_path": str(db_path),
        "roots": root_strs,
        "scanned_files": scanned,
        "created": created,
        "modified": modified,
        "deleted": deleted,
        "errors": errors,
        "file_index_last_synced": run_started,
        "max_files_reached": scanned >= max_files,
    }


def _safe_version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        output = (result.stdout or result.stderr or "").strip().splitlines()
        return output[0].strip() if output else ""
    except Exception:
        return ""


def _normalize_app_name(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _inventory_key(name: str, path: str = "") -> str:
    base = re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_") or "app"
    if path:
        suffix = hashlib.sha1(str(path).strip().lower().encode("utf-8")).hexdigest()[:8]
        return f"{base}_{suffix}"
    return base


def _tool_inventory(now: str) -> dict[str, Any]:
    software: dict[str, Any] = {}
    for tool in _KNOWN_TOOLS:
        path = shutil.which(tool) or ""
        installed = bool(path)
        version = ""
        if installed:
            version = _safe_version([tool, "--version"])
        software[tool] = {
            "installed": installed,
            "path": path,
            "version": version,
            "updated_at": now,
            "source": "path_probe",
        }
    return software


def _windows_registry_apps(now: str) -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    try:
        import winreg  # type: ignore
    except Exception:
        return []

    apps: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    hives = [("machine", winreg.HKEY_LOCAL_MACHINE), ("user", winreg.HKEY_CURRENT_USER)]

    for hive_label, hive in hives:
        for root in _WINDOWS_UNINSTALL_ROOTS:
            try:
                key = winreg.OpenKey(hive, root)
            except OSError:
                continue
            try:
                subkey_count = winreg.QueryInfoKey(key)[0]
            except OSError:
                subkey_count = 0
            for idx in range(subkey_count):
                try:
                    subkey_name = winreg.EnumKey(key, idx)
                    subkey = winreg.OpenKey(key, subkey_name)
                except OSError:
                    continue
                try:
                    values: dict[str, Any] = {}
                    value_count = winreg.QueryInfoKey(subkey)[1]
                    for value_idx in range(value_count):
                        try:
                            name, value, _ = winreg.EnumValue(subkey, value_idx)
                            values[str(name)] = value
                        except OSError:
                            continue
                    display_name = _normalize_app_name(str(values.get("DisplayName") or ""))
                    if not display_name:
                        continue
                    if int(values.get("SystemComponent") or 0) == 1:
                        continue
                    parent_name = _normalize_app_name(str(values.get("ParentDisplayName") or ""))
                    if parent_name:
                        continue
                    uninstall = str(values.get("UninstallString") or "").strip()
                    install_location = str(values.get("InstallLocation") or "").strip()
                    display_icon = str(values.get("DisplayIcon") or "").strip().strip('"')
                    publisher = _normalize_app_name(str(values.get("Publisher") or ""))
                    version = _normalize_app_name(str(values.get("DisplayVersion") or ""))
                    path = install_location or display_icon or uninstall
                    dedupe_key = (display_name.lower(), path.lower())
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    apps.append({
                        "name": display_name,
                        "version": version,
                        "path": path,
                        "publisher": publisher,
                        "updated_at": now,
                        "source": f"windows_registry_{hive_label}",
                    })
                finally:
                    try:
                        winreg.CloseKey(subkey)
                    except Exception:
                        pass
            try:
                winreg.CloseKey(key)
            except Exception:
                pass
    return apps


def _merge_app_records(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    merged: dict[tuple[str, str], dict[str, str]] = {}
    for raw in items:
        name = _normalize_app_name(str(raw.get("name") or ""))
        path = str(raw.get("path") or "").strip()
        if not name:
            continue
        key = (name.lower(), path.lower())
        current = merged.get(key)
        candidate = {
            "name": name,
            "version": _normalize_app_name(str(raw.get("version") or "")),
            "path": path,
            "publisher": _normalize_app_name(str(raw.get("publisher") or "")),
            "updated_at": str(raw.get("updated_at") or "").strip(),
            "source": str(raw.get("source") or "").strip(),
        }
        if current is None:
            merged[key] = candidate
            continue
        if not current.get("version") and candidate.get("version"):
            current["version"] = candidate["version"]
        if not current.get("publisher") and candidate.get("publisher"):
            current["publisher"] = candidate["publisher"]
        if not current.get("path") and candidate.get("path"):
            current["path"] = candidate["path"]
        if not current.get("source") and candidate.get("source"):
            current["source"] = candidate["source"]
    return sorted(merged.values(), key=lambda item: (item.get("name", "").lower(), item.get("path", "").lower()))


def _apps_to_software_map(apps: list[dict[str, str]]) -> dict[str, Any]:
    software: dict[str, Any] = {}
    for app in apps:
        key = _inventory_key(app.get("name", ""), app.get("path", ""))
        software[key] = {
            "installed": True,
            "path": app.get("path", ""),
            "version": app.get("version", ""),
            "publisher": app.get("publisher", ""),
            "updated_at": app.get("updated_at", ""),
            "display_name": app.get("name", ""),
            "source": app.get("source", ""),
        }
    return software


def _bytes_to_gb(value: int) -> float:
    if value <= 0:
        return 0.0
    return round(value / (1024 ** 3), 2)


def _detect_total_memory_bytes() -> int:
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys or 0)
        except Exception:
            return 0
    if hasattr(os, "sysconf"):
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            page_count = int(os.sysconf("SC_PHYS_PAGES"))
            if page_size > 0 and page_count > 0:
                return page_size * page_count
        except Exception:
            return 0
    return 0


def collect_system_info(working_directory: str) -> dict[str, Any]:
    root = Path(str(working_directory or ".")).expanduser().resolve()
    total_memory = _detect_total_memory_bytes()
    disk_total = 0
    disk_free = 0
    try:
        usage = shutil.disk_usage(str(root.anchor or root))
        disk_total = int(usage.total or 0)
        disk_free = int(usage.free or 0)
    except Exception:
        pass

    return {
        "hostname": socket.gethostname(),
        "platform": sys.platform,
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "cpu_count": int(os.cpu_count() or 0),
        "total_memory_bytes": total_memory,
        "total_memory_gb": _bytes_to_gb(total_memory),
        "disk_root": str(root.anchor or root),
        "disk_total_bytes": disk_total,
        "disk_total_gb": _bytes_to_gb(disk_total),
        "disk_free_bytes": disk_free,
        "disk_free_gb": _bytes_to_gb(disk_free),
        "workspace_root": str(root),
    }


def run_software_inventory_sync(working_directory: str) -> dict[str, Any]:
    inventory_file = software_inventory_path(working_directory)
    now = _utc_now()
    path_tools = _tool_inventory(now)
    windows_apps = _windows_registry_apps(now)
    apps = _merge_app_records(windows_apps)
    software: dict[str, Any]
    if apps:
        software = _apps_to_software_map(apps)
        for tool_name, item in path_tools.items():
            path = str(item.get("path") or "").strip()
            if not item.get("installed") or not path:
                continue
            if any(str(app.get("path") or "").strip().lower() == path.lower() for app in apps):
                continue
            apps.append({
                "name": tool_name,
                "version": str(item.get("version") or "").strip(),
                "path": path,
                "publisher": "",
                "updated_at": now,
                "source": "path_probe",
            })
            software[_inventory_key(tool_name, path)] = {
                "installed": True,
                "path": path,
                "version": str(item.get("version") or "").strip(),
                "publisher": "",
                "updated_at": now,
                "display_name": tool_name,
                "source": "path_probe",
            }
        apps = _merge_app_records(apps)
    else:
        software = path_tools
        apps = [
            {
                "name": str(name),
                "version": str(item.get("version", "") or "").strip(),
                "path": str(item.get("path", "") or "").strip(),
                "publisher": "",
                "updated_at": str(item.get("updated_at", "") or "").strip(),
                "source": str(item.get("source", "") or "").strip(),
            }
            for name, item in software.items()
            if isinstance(item, dict) and item.get("installed")
        ]
        apps = _merge_app_records(apps)

    payload = {
        "last_synced_at": now,
        "software": software,
        "apps": apps,
        "platform": sys.platform,
    }
    inventory_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "software_inventory_path": str(inventory_file),
        "software_inventory_last_synced": now,
        "software": software,
        "apps": apps,
        "installed_count": len(apps),
    }


def machine_sync_status(working_directory: str) -> dict[str, Any]:
    db_path = ensure_machine_index_schema(working_directory)
    inventory_file = software_inventory_path(working_directory)

    file_last = ""
    file_count = 0
    recent_changes_24h = 0
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM machine_sync_meta WHERE key = 'file_index_last_synced'"
        ).fetchone()
        if row:
            file_last = str(row["value"] or "")
        c = conn.execute("SELECT COUNT(*) AS c FROM file_index").fetchone()
        file_count = int((c["c"] if c else 0) or 0)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        rc = conn.execute(
            "SELECT COUNT(*) AS c FROM file_changes WHERE detected_at >= ?",
            (cutoff,),
        ).fetchone()
        recent_changes_24h = int((rc["c"] if rc else 0) or 0)

    software_last = ""
    installed_count = 0
    discovered_apps: list[dict[str, str]] = []
    if inventory_file.exists():
        try:
            payload = json.loads(inventory_file.read_text(encoding="utf-8"))
            software_last = str(payload.get("last_synced_at", "") or "")
            software = payload.get("software", {})
            apps_payload = payload.get("apps")
            if isinstance(apps_payload, list):
                discovered_apps = _merge_app_records([item for item in apps_payload if isinstance(item, dict)])
                installed_count = len(discovered_apps)
            elif isinstance(software, dict):
                installed_count = sum(1 for item in software.values() if isinstance(item, dict) and item.get("installed"))
                apps: list[dict[str, str]] = []
                for name, item in software.items():
                    if not isinstance(item, dict) or not item.get("installed"):
                        continue
                    app_name = _normalize_app_name(str(item.get("display_name") or name or ""))
                    if not app_name:
                        continue
                    apps.append(
                        {
                            "name": app_name,
                            "version": str(item.get("version", "") or "").strip(),
                            "path": str(item.get("path", "") or "").strip(),
                            "publisher": str(item.get("publisher", "") or "").strip(),
                            "updated_at": str(item.get("updated_at", "") or "").strip(),
                            "source": str(item.get("source", "") or "").strip(),
                        }
                    )
                discovered_apps = _merge_app_records(apps)
        except Exception:
            pass

    return {
        "file_index_last_synced": file_last,
        "software_inventory_last_synced": software_last,
        "indexed_files": file_count,
        "recent_changes_24h": recent_changes_24h,
        "installed_software_count": installed_count,
        "discovered_apps": discovered_apps,
        "system_info": collect_system_info(working_directory),
    }


def machine_sync_details(working_directory: str, *, max_files: int = 20_000) -> dict[str, Any]:
    root = str(Path(working_directory or ".").expanduser().resolve())
    status = machine_sync_status(root)
    db_path = ensure_machine_index_schema(root)

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT path, root_path, size, file_type, last_seen_at
            FROM file_index
            ORDER BY root_path ASC, path ASC
            LIMIT ?
            """,
            (int(max_files),),
        ).fetchall()
        total_row = conn.execute("SELECT COUNT(*) AS c FROM file_index").fetchone()
        total_files = int((total_row["c"] if total_row else 0) or 0)

    tree_roots: list[dict[str, Any]] = []
    root_nodes: dict[str, dict[str, Any]] = {}
    indexed_files: list[dict[str, Any]] = []

    for row in rows:
        path_str = str(row["path"] or "")
        root_path = str(row["root_path"] or "")
        if not path_str or not root_path:
            continue
        root_node = root_nodes.get(root_path)
        if root_node is None:
            root_node = {
                "name": Path(root_path).name or root_path,
                "path": root_path,
                "type": "directory",
                "children": [],
                "_child_map": {},
            }
            root_nodes[root_path] = root_node
            tree_roots.append(root_node)

        try:
            relative = os.path.relpath(path_str, root_path)
        except Exception:
            relative = path_str
        parts = [part for part in Path(relative).parts if part not in {"."}]
        cursor = root_node
        current_path = root_path
        for part in parts[:-1]:
            current_path = os.path.join(current_path, part)
            child_map = cursor.setdefault("_child_map", {})
            child = child_map.get(part)
            if child is None:
                child = {
                    "name": part,
                    "path": current_path,
                    "type": "directory",
                    "children": [],
                    "_child_map": {},
                }
                child_map[part] = child
                cursor["children"].append(child)
            cursor = child

        filename = parts[-1] if parts else Path(path_str).name
        cursor["children"].append(
            {
                "name": filename,
                "path": path_str,
                "type": "file",
                "size": int(row["size"] or 0),
                "file_type": str(row["file_type"] or "").strip(),
                "last_seen_at": str(row["last_seen_at"] or "").strip(),
            }
        )
        indexed_files.append(
            {
                "path": path_str,
                "root_path": root_path,
                "size": int(row["size"] or 0),
                "file_type": str(row["file_type"] or "").strip(),
                "last_seen_at": str(row["last_seen_at"] or "").strip(),
            }
        )

    def _finalize(node: dict[str, Any]) -> dict[str, Any]:
        children = node.get("children", [])
        normalized: list[dict[str, Any]] = []
        for child in children:
            if isinstance(child, dict) and child.get("type") == "directory":
                normalized.append(_finalize(child))
            else:
                normalized.append(child)
        normalized.sort(key=lambda item: (0 if item.get("type") == "directory" else 1, str(item.get("name", "")).lower()))
        node["children"] = normalized
        node.pop("_child_map", None)
        return node

    tree = [_finalize(node) for node in tree_roots]
    tree.sort(key=lambda item: str(item.get("name", "")).lower())

    return {
        "working_directory": root,
        "status": status,
        "system_info": dict(status.get("system_info") or {}),
        "apps": list(status.get("discovered_apps") or []),
        "roots": [str(node.get("path", "")) for node in tree],
        "tree": tree,
        "indexed_files": indexed_files,
        "truncated": total_files > len(rows),
        "max_files": int(max_files),
    }


def run_machine_sync(
    *,
    working_directory: str,
    scope: str = "machine",
    roots: list[str] | None = None,
    max_files: int = 250_000,
) -> dict[str, Any]:
    normalized_scope = str(scope or "machine").strip().lower()
    if normalized_scope not in {"machine", "software", "files"}:
        normalized_scope = "machine"

    software_result: dict[str, Any] = {}
    file_result: dict[str, Any] = {}

    if normalized_scope in {"machine", "software"}:
        software_result = run_software_inventory_sync(working_directory)
    if normalized_scope in {"machine", "files"}:
        file_result = run_file_index_sync(
            working_directory=working_directory,
            roots=roots,
            max_files=max_files,
        )

    status = machine_sync_status(working_directory)
    return {
        "scope": normalized_scope,
        "working_directory": str(Path(working_directory).expanduser().resolve()),
        "software_result": software_result,
        "file_result": file_result,
        "status": status,
        "synced_at": _utc_now(),
    }
