"""Project Manager — kendr project workspace backend.

Stores a registry of known project directories and provides:
  - File tree reading
  - File content access
  - Shell command execution
  - Long-running project service management
  - Git operations (status, pull, push, commit, clone, branch)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import shutil
import socket
import subprocess
import threading
import time
import calendar
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from kendr.execution_trace import duration_label

_log = logging.getLogger("kendr.project_manager")


def _normalize_path(path: str) -> str:
    """Expand ~ and resolve to an absolute real path."""
    return str(Path(path).expanduser().resolve())


_store_lock = threading.Lock()

_MAX_FILE_SIZE = 256 * 1024  # 256 KB
_MAX_TREE_DEPTH = 6
_IGNORED_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".env",
    "dist", "build", ".next", ".nuxt", ".cache", "coverage",
    ".mypy_cache", ".pytest_cache", ".tox", "eggs", ".eggs",
}
_IGNORED_EXTS = {".pyc", ".pyo", ".so", ".dylib", ".dll"}


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _discover_project_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    markers = (".git", "pyproject.toml", "package.json", "requirements.txt")
    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in markers):
            return candidate
    return None


def _dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".kendr_write_test"
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _projects_store_path() -> str:
    explicit_store = str(os.getenv("KENDR_PROJECTS_STORE", "")).strip()
    if explicit_store:
        return str(Path(explicit_store).expanduser())

    candidates: list[Path] = []
    explicit_home = str(os.getenv("KENDR_HOME", "")).strip()
    if explicit_home:
        candidates.append(Path(explicit_home).expanduser())
    candidates.append(Path.home() / ".kendr")
    project_root = _discover_project_root()
    if project_root is not None:
        candidates.append(project_root / ".kendr")
    candidates.append(Path.cwd() / ".kendr")

    last_candidate = candidates[-1]
    for candidate in candidates:
        if _dir_writable(candidate):
            return str(candidate / "projects.json")
        last_candidate = candidate
    return str(last_candidate / "projects.json")


def _ensure_store_shape(store: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(store, dict):
        store = {}
    projects = store.get("projects")
    if not isinstance(projects, dict):
        projects = {}
    store["projects"] = projects
    if "active" not in store:
        store["active"] = None
    for project_id, proj in list(projects.items()):
        if not isinstance(proj, dict):
            projects[project_id] = {}
            proj = projects[project_id]
        services = proj.get("services")
        if not isinstance(services, dict):
            proj["services"] = {}
    return store


def _load_store() -> dict:
    store_path = _projects_store_path()
    try:
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        if os.path.isfile(store_path):
            with open(store_path, "r", encoding="utf-8") as fh:
                return _ensure_store_shape(json.load(fh))
    except Exception as exc:
        _log.warning("Could not load projects store: %s", exc)
    return _ensure_store_shape({"projects": {}, "active": None})


def _save_store(store: dict) -> None:
    store_path = _projects_store_path()
    try:
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        with open(store_path, "w", encoding="utf-8") as fh:
            json.dump(_ensure_store_shape(store), fh, indent=2)
    except Exception as exc:
        _log.warning("Could not save projects store: %s", exc)


# ---------------------------------------------------------------------------
# Project registry
# ---------------------------------------------------------------------------

def list_projects() -> list[dict]:
    with _store_lock:
        store = _load_store()
        # Auto-migrate any stored paths that still contain un-expanded ~ or
        # were stored relative to cwd (e.g. /workspace/~/foo).
        dirty = False
        for proj in store.get("projects", {}).values():
            raw = proj.get("path", "")
            if not raw:
                continue
            try:
                fixed = _normalize_path(raw)
                if fixed != raw and os.path.isdir(fixed):
                    proj["path"] = fixed
                    dirty = True
            except Exception:
                pass
            if not isinstance(proj.get("services"), dict):
                proj["services"] = {}
                dirty = True
        if dirty:
            try:
                _save_store(store)
            except Exception:
                pass
    projects = list(store.get("projects", {}).values())
    projects.sort(key=lambda p: p.get("name", "").lower())
    return projects


def get_active_project() -> dict | None:
    with _store_lock:
        store = _load_store()
    active_id = store.get("active")
    if active_id:
        return store.get("projects", {}).get(active_id)
    projects = list(store.get("projects", {}).values())
    return projects[0] if projects else None


def set_active_project(project_id: str) -> bool:
    with _store_lock:
        store = _load_store()
        if project_id not in store.get("projects", {}):
            return False
        store["active"] = project_id
        _save_store(store)
    return True


def add_project(path: str, name: str = "") -> dict:
    path = _normalize_path(path)
    if not os.path.isdir(path):
        raise ValueError(f"Directory does not exist: {path}")
    project_id = _path_to_id(path)
    display_name = name.strip() or os.path.basename(path)
    git_remote = _detect_git_remote(path)
    entry = {
        "id": project_id,
        "name": display_name,
        "path": path,
        "git_remote": git_remote,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "services": {},
    }
    with _store_lock:
        store = _load_store()
        existing = store.setdefault("projects", {}).get(project_id, {})
        if isinstance(existing.get("services"), dict) and existing["services"]:
            entry["services"] = existing["services"]
        store.setdefault("projects", {})[project_id] = entry
        if store.get("active") is None:
            store["active"] = project_id
        _save_store(store)
    return entry


def get_project(project_id: str) -> dict | None:
    store = _load_store()
    return store.get("projects", {}).get(project_id)


def remove_project(project_id: str) -> bool:
    with _store_lock:
        store = _load_store()
        entry = store.get("projects", {}).get(project_id)
        if not entry:
            return False
        services = list((entry.get("services") or {}).values())
        del store["projects"][project_id]
        if store.get("active") == project_id:
            remaining = list(store.get("projects", {}).keys())
            store["active"] = remaining[0] if remaining else None
        _save_store(store)
    for service in services:
        _stop_service_process(service)
    return True


def delete_project_and_files(project_id: str) -> dict:
    """Remove from store and permanently delete all project files from disk."""
    import shutil as _shutil
    with _store_lock:
        store = _load_store()
        entry = store.get("projects", {}).get(project_id)
        if not entry:
            return {"ok": False, "error": "Project not found"}
        project_path = entry.get("path", "")
        services = list((entry.get("services") or {}).values())
        del store["projects"][project_id]
        if store.get("active") == project_id:
            remaining = list(store.get("projects", {}).keys())
            store["active"] = remaining[0] if remaining else None
        _save_store(store)
    stopped_services = 0
    for service in services:
        stopped_services += int(_stop_service_process(service))
    if project_path and os.path.isdir(project_path):
        try:
            _shutil.rmtree(project_path)
            return {"ok": True, "deleted_path": project_path, "stopped_services": stopped_services}
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "deleted_path": project_path,
                "stopped_services": stopped_services,
            }
    return {
        "ok": True,
        "deleted_path": None,
        "warning": "Directory not found on disk",
        "stopped_services": stopped_services,
    }


def init_project_from_scratch(name: str, parent_dir: str = "", stack: str = "") -> dict:
    """Create a new project folder, init git, set up .gitignore and output dir."""
    name = name.strip()
    if not name:
        raise ValueError("Project name is required")
    parent = os.path.abspath(parent_dir) if parent_dir.strip() else os.getcwd()
    project_path = os.path.join(parent, name)
    if os.path.exists(project_path):
        raise ValueError(f"Directory already exists: {project_path}")
    os.makedirs(project_path, exist_ok=False)
    os.makedirs(os.path.join(project_path, "output"), exist_ok=True)
    gitignore_lines = [
        "# kendr output",
        "output/",
        "",
        "# Python",
        "__pycache__/",
        "*.pyc",
        ".venv/",
        "venv/",
        ".env",
        "",
        "# Node",
        "node_modules/",
        "dist/",
        "build/",
        ".next/",
        "",
        "# General",
        ".DS_Store",
        "*.log",
    ]
    if stack:
        gitignore_lines += _stack_gitignore_extras(stack)
    with open(os.path.join(project_path, ".gitignore"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(gitignore_lines) + "\n")
    readme_lines = [f"# {name}", "", "Created with kendr.", ""]
    with open(os.path.join(project_path, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(readme_lines))
    import subprocess as _sp
    _sp.run(["git", "init"], cwd=project_path, capture_output=True, timeout=10)
    _sp.run(["git", "add", ".gitignore", "README.md"], cwd=project_path, capture_output=True, timeout=10)
    _sp.run(["git", "commit", "-m", "Initial commit"], cwd=project_path, capture_output=True, timeout=10)
    entry = add_project(project_path, name)
    entry["initialized"] = True
    entry["stack"] = stack
    return entry


def _stack_gitignore_extras(stack: str) -> list[str]:
    s = stack.lower()
    if "django" in s or "flask" in s or "fastapi" in s or "python" in s:
        return ["*.egg-info/", ".pytest_cache/", ".mypy_cache/"]
    if "node" in s or "react" in s or "next" in s or "vue" in s:
        return ["*.tsbuildinfo", ".turbo/"]
    if "go" in s:
        return ["*.exe", "*.test", "vendor/"]
    if "rust" in s:
        return ["target/"]
    return []


def _path_to_id(path: str) -> str:
    import hashlib
    return hashlib.md5(path.encode()).hexdigest()[:12]


def _detect_git_remote(path: str) -> str:
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=path, capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# File tree
# ---------------------------------------------------------------------------

def read_file_tree(path: str, depth: int = 0) -> list[dict]:
    """Return a recursive file tree for the given directory."""
    if depth > _MAX_TREE_DEPTH:
        return []
    result: list[dict] = []
    try:
        entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            if entry.name.startswith(".") and entry.name != ".env.example":
                if entry.name in {".gitignore", ".env.example", ".editorconfig"}:
                    pass
                else:
                    continue
            if entry.name in _IGNORED_DIRS:
                continue
            _, ext = os.path.splitext(entry.name)
            if ext in _IGNORED_EXTS:
                continue
            node: dict[str, Any] = {
                "name": entry.name,
                "path": entry.path,
                "type": "dir" if entry.is_dir() else "file",
            }
            if entry.is_dir():
                node["children"] = read_file_tree(entry.path, depth + 1)
            else:
                node["size"] = entry.stat().st_size
            result.append(node)
    except PermissionError:
        pass
    return result


def read_file_content(file_path: str, project_root: str = "") -> dict:
    """Read a file's content with size guard and binary detection."""
    abs_path = os.path.abspath(file_path)
    if project_root:
        root = os.path.abspath(project_root)
        if not abs_path.startswith(root):
            return {"ok": False, "error": "Path is outside project root"}
    try:
        size = os.path.getsize(abs_path)
        if size > _MAX_FILE_SIZE:
            return {"ok": False, "error": f"File too large ({size // 1024} KB). Limit is {_MAX_FILE_SIZE // 1024} KB."}
        with open(abs_path, "rb") as fh:
            raw = fh.read()
        try:
            content = raw.decode("utf-8")
            return {"ok": True, "content": content, "encoding": "utf-8", "size": size, "path": abs_path}
        except UnicodeDecodeError:
            return {"ok": False, "error": "Binary file — cannot display as text"}
    except FileNotFoundError:
        return {"ok": False, "error": "File not found"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Shell execution
# ---------------------------------------------------------------------------

def _build_shell_env() -> dict:
    """Build a rich environment for shell commands including all nix/system paths."""
    base = dict(os.environ)
    path_parts = base.get("PATH", "").split(os.pathsep)
    if os.name == "nt":
        extra_paths = [
            r"C:\Windows\System32",
            r"C:\Windows",
            r"C:\Windows\System32\Wbem",
            r"C:\Windows\System32\WindowsPowerShell\v1.0",
        ]
    else:
        extra_paths = [
            "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
            "/nix/var/nix/profiles/default/bin",
        ]
    for p in extra_paths:
        if p and p not in path_parts:
            path_parts.append(p)
    base["PATH"] = os.pathsep.join(p for p in path_parts if p)
    base.setdefault("TERM", "xterm-256color")
    base.setdefault("LANG", "en_US.UTF-8")
    return base


def _shell_args_for_path(shell_path: str, command: str) -> list[str]:
    """Return subprocess arguments for the given shell binary."""
    clean = shell_path.lower()
    command_body = _shell_command_body(clean, command)
    if os.name == "nt":
        if "bash" in clean or clean.endswith("bash.exe"):
            return [shell_path, "-lc", command_body]
        if "powershell" in clean or "pwsh" in clean:
            return [shell_path, "-NoLogo", "-NoProfile", "-Command", command_body]
        return [shell_path, "/d", "/s", "/c", command_body]
    return [shell_path, "-c", command_body]


def _shell_command_body(shell_name: str, command: str) -> str:
    body = str(command or "").strip()
    if not body:
        return body
    if "powershell" in shell_name or "pwsh" in shell_name:
        if body.startswith('"') or body.startswith("'"):
            return f"& {body}"
    return body


def _resolve_shell_args(command: str) -> list[str]:
    """Pick an appropriate shell executable for the running platform."""
    preferred = str(os.environ.get("KENDR_SHELL") or "").strip()
    if preferred:
        shell_path = shutil.which(preferred) or preferred
        return _shell_args_for_path(shell_path, command)
    if os.name == "nt":
        for candidate in ("pwsh", "powershell"):
            shell_path = shutil.which(candidate)
            if shell_path:
                return _shell_args_for_path(shell_path, command)
        candidate = str(os.environ.get("COMSPEC") or "cmd.exe")
        shell_path = shutil.which(candidate) or candidate
        return _shell_args_for_path(shell_path, command)
    shell = os.environ.get("SHELL")
    if shell:
        shell_path = shutil.which(shell)
        if shell_path:
            return _shell_args_for_path(shell_path, command)
    shell_path = shutil.which("bash") or shutil.which("sh") or "/bin/bash"
    return _shell_args_for_path(shell_path, command)


def run_shell(command: str, cwd: str, timeout: int = 60) -> dict:
    """Run a shell command in the given directory via an OS-appropriate shell."""
    cwd = _normalize_path(cwd)
    shell_args = _resolve_shell_args(command)
    started = time.time()
    started_at = _utc_now()
    try:
        result = subprocess.run(
            shell_args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_build_shell_env(),
        )
        completed_at = _utc_now()
        elapsed_ms = max(0, int((time.time() - started) * 1000))
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "command": command,
            "cwd": cwd,
            "shell_argv": shell_args,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": elapsed_ms,
            "duration_label": duration_label(elapsed_ms),
        }
    except subprocess.TimeoutExpired:
        completed_at = _utc_now()
        elapsed_ms = max(0, int((time.time() - started) * 1000))
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "returncode": -1,
            "command": command,
            "cwd": cwd,
            "shell_argv": shell_args,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": elapsed_ms,
            "duration_label": duration_label(elapsed_ms),
        }
    except Exception as exc:
        completed_at = _utc_now()
        elapsed_ms = max(0, int((time.time() - started) * 1000))
        return {
            "ok": False,
            "stdout": "",
            "stderr": str(exc),
            "returncode": -1,
            "command": command,
            "cwd": cwd,
            "shell_argv": shell_args,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": elapsed_ms,
            "duration_label": duration_label(elapsed_ms),
        }


# ---------------------------------------------------------------------------
# Project services
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _service_slug(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in name.strip())
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts) or "service"


def _project_services(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    services = project.get("services")
    if not isinstance(services, dict):
        services = {}
        project["services"] = services
    return services


def _coerce_port(value: Any) -> int | None:
    if value in ("", None):
        return None
    try:
        port = int(value)
    except Exception:
        return None
    if 1 <= port <= 65535:
        return port
    return None


def _pid_is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


def _service_host(service: dict[str, Any]) -> str:
    url = str(service.get("health_url") or "").strip()
    if url:
        parsed = urllib_parse.urlparse(url)
        if parsed.hostname:
            return parsed.hostname
    return "127.0.0.1"


def _port_is_listening(port: int | None, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    if not port:
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def _healthcheck_ok(url: str) -> bool:
    if not url:
        return False
    request = urllib_request.Request(url, headers={"User-Agent": "kendr-project-manager"})
    try:
        with urllib_request.urlopen(request, timeout=0.8) as resp:
            return 200 <= getattr(resp, "status", 200) < 500
    except urllib_error.HTTPError as exc:
        return 200 <= exc.code < 500
    except Exception:
        return False


def _iso_to_epoch(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")))
    except Exception:
        return None


def _service_display_url(service: dict[str, Any]) -> str:
    health_url = str(service.get("health_url") or "").strip()
    if health_url:
        return health_url
    port = _coerce_port(service.get("port"))
    if not port:
        return ""
    host = _service_host(service)
    kind = str(service.get("kind") or "").strip().lower()
    scheme = "tcp" if kind == "database" else "http"
    return f"{scheme}://{host}:{port}"


def _service_log_path(project_path: str, service_id: str) -> str:
    log_dir = Path(project_path) / "logs" / "kendr" / "services"
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_dir / f"{_service_slug(service_id)}.log")


def _service_snapshot(project: dict[str, Any], service: dict[str, Any]) -> dict[str, Any]:
    port = _coerce_port(service.get("port"))
    pid = int(service.get("pid") or 0) or None
    pid_alive = _pid_is_alive(pid)
    host = _service_host(service)
    port_listening = _port_is_listening(port, host=host) if port else False
    health_url = str(service.get("health_url") or "").strip()
    health_ok = _healthcheck_ok(health_url) if health_url else False
    running = bool(pid_alive or port_listening or health_ok)
    status = "running" if running else "stopped"
    if running and health_url and not health_ok:
        status = "degraded"
    started_at = str(service.get("started_at") or service.get("last_started_at") or "").strip()
    start_epoch = _iso_to_epoch(started_at)
    uptime_seconds = max(0.0, time.time() - start_epoch) if (running and start_epoch) else None
    snapshot = dict(service)
    snapshot.update(
        {
            "id": str(service.get("id") or ""),
            "name": str(service.get("name") or ""),
            "kind": str(service.get("kind") or "service"),
            "cwd": str(service.get("cwd") or project.get("path") or ""),
            "port": port,
            "pid": pid,
            "pid_alive": pid_alive,
            "port_listening": port_listening,
            "health_ok": health_ok,
            "running": running,
            "status": status,
            "uptime_seconds": round(uptime_seconds, 1) if uptime_seconds is not None else None,
            "url": _service_display_url(service),
            "log_path": str(service.get("log_path") or ""),
            "project_id": str(project.get("id") or ""),
            "project_name": str(project.get("name") or ""),
            "project_path": str(project.get("path") or ""),
        }
    )
    return snapshot


def _refresh_service_snapshots(store: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    dirty = False
    snapshots: list[dict[str, Any]] = []
    for project in store.get("projects", {}).values():
        services = _project_services(project)
        for service_id, service in services.items():
            if not isinstance(service, dict):
                continue
            service.setdefault("id", service_id)
            snapshot = _service_snapshot(project, service)
            snapshots.append(snapshot)
            if service.get("pid") and not snapshot["pid_alive"] and not snapshot["port_listening"] and not snapshot["health_ok"]:
                service["pid"] = None
                service["updated_at"] = _utc_now()
                dirty = True
    snapshots.sort(key=lambda item: (item.get("project_name", "").lower(), item.get("name", "").lower()))
    return snapshots, dirty


def list_project_services(project_id: str, include_stopped: bool = True) -> list[dict[str, Any]]:
    with _store_lock:
        store = _load_store()
        project = store.get("projects", {}).get(project_id)
        if not project:
            return []
        snapshots, dirty = _refresh_service_snapshots(store)
        if dirty:
            _save_store(store)
    project_services = [svc for svc in snapshots if svc.get("project_id") == project_id]
    if not include_stopped:
        project_services = [svc for svc in project_services if svc.get("running")]
    return project_services


def list_all_project_services(include_stopped: bool = True) -> list[dict[str, Any]]:
    with _store_lock:
        store = _load_store()
        snapshots, dirty = _refresh_service_snapshots(store)
        if dirty:
            _save_store(store)
    if not include_stopped:
        snapshots = [svc for svc in snapshots if svc.get("running")]
    return snapshots


def list_running_project_services() -> list[dict[str, Any]]:
    return list_all_project_services(include_stopped=False)


def get_project_service(project_id: str, service_id: str) -> dict[str, Any] | None:
    services = list_project_services(project_id, include_stopped=True)
    for service in services:
        if service.get("id") == service_id:
            return service
    return None


def _stop_service_process(service: dict[str, Any], timeout: float = 6.0) -> bool:
    pid = int(service.get("pid") or 0) or None
    if not pid or not _pid_is_alive(pid):
        return False
    try:
        if os.name == "nt":
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
            deadline = time.time() + min(timeout, 2.0)
            while time.time() < deadline and _pid_is_alive(pid):
                time.sleep(0.15)
            if _pid_is_alive(pid):
                subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True, check=False)
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                return True
            except Exception:
                os.kill(pid, signal.SIGTERM)
            deadline = time.time() + timeout
            while time.time() < deadline and _pid_is_alive(pid):
                time.sleep(0.2)
            if _pid_is_alive(pid):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except Exception:
                    os.kill(pid, signal.SIGKILL)
    except Exception:
        return False
    return not _pid_is_alive(pid)


def start_project_service(
    project_id: str,
    name: str = "",
    command: str = "",
    *,
    kind: str = "",
    cwd: str = "",
    port: int | None = None,
    health_url: str = "",
    service_id: str = "",
) -> dict[str, Any]:
    command = str(command or "").strip()

    with _store_lock:
        store = _load_store()
        project = store.get("projects", {}).get(project_id)
        if not project:
            raise ValueError("Project not found")
        services = _project_services(project)
        resolved_service_id = _service_slug(service_id or name or command)
        existing = dict(services.get(resolved_service_id) or {})
        existing_pid = int(existing.get("pid") or 0) or None
        if existing_pid and _pid_is_alive(existing_pid):
            raise ValueError(f"Service '{existing.get('name') or resolved_service_id}' is already running")
        project_root = str(project.get("path") or "")
        resolved_cwd = _normalize_path(cwd or existing.get("cwd") or project_root)
        if not os.path.isdir(resolved_cwd):
            raise ValueError(f"Working directory does not exist: {resolved_cwd}")
        resolved_command = command or str(existing.get("command") or "").strip()
        if not resolved_command:
            raise ValueError("command is required")
        resolved_kind = str(kind or existing.get("kind") or "service").strip().lower() or "service"
        resolved_port = _coerce_port(port if port is not None else existing.get("port"))
        resolved_health_url = str(health_url or existing.get("health_url") or "").strip()
        resolved_name = str(name or existing.get("name") or resolved_service_id).strip()
        log_path = _service_log_path(project_root, resolved_service_id)

    log_parent = Path(log_path).parent
    log_parent.mkdir(parents=True, exist_ok=True)
    launched_at = _utc_now()
    shell_args = _resolve_shell_args(resolved_command)
    with open(log_path, "a", encoding="utf-8") as log_fh:
        log_fh.write(f"\n[{launched_at}] starting service {resolved_name}: {resolved_command}\n")
        log_fh.flush()
        proc = subprocess.Popen(
            shell_args,
            cwd=resolved_cwd,
            env=_build_shell_env(),
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=(os.name != "nt"),
        )

    with _store_lock:
        store = _load_store()
        project = store.get("projects", {}).get(project_id)
        if not project:
            try:
                _stop_service_process({"pid": proc.pid})
            except Exception:
                pass
            raise ValueError("Project not found")
        services = _project_services(project)
        created_at = str((services.get(resolved_service_id) or {}).get("created_at") or launched_at)
        services[resolved_service_id] = {
            "id": resolved_service_id,
            "name": resolved_name,
            "kind": resolved_kind,
            "command": resolved_command,
            "shell_argv": shell_args,
            "cwd": resolved_cwd,
            "port": resolved_port,
            "health_url": resolved_health_url,
            "log_path": log_path,
            "pid": proc.pid,
            "created_at": created_at,
            "started_at": launched_at,
            "last_started_at": launched_at,
            "stopped_at": None,
            "updated_at": launched_at,
        }
        _save_store(store)
    time.sleep(0.2)
    snapshot = get_project_service(project_id, resolved_service_id)
    if not snapshot:
        raise ValueError("Service was started but could not be reloaded")
    snapshot["ok"] = True
    return snapshot


def stop_project_service(project_id: str, service_id: str) -> dict[str, Any]:
    with _store_lock:
        store = _load_store()
        project = store.get("projects", {}).get(project_id)
        if not project:
            raise ValueError("Project not found")
        services = _project_services(project)
        service = services.get(service_id)
        if not service:
            raise ValueError("Service not found")
        service_copy = dict(service)

    stopped = _stop_service_process(service_copy)
    now = _utc_now()
    with _store_lock:
        store = _load_store()
        project = store.get("projects", {}).get(project_id)
        if not project:
            raise ValueError("Project not found")
        services = _project_services(project)
        service = services.get(service_id)
        if not service:
            raise ValueError("Service not found")
        service["pid"] = None
        service["stopped_at"] = now
        service["updated_at"] = now
        _save_store(store)
    snapshot = get_project_service(project_id, service_id)
    if not snapshot:
        raise ValueError("Service stopped but snapshot could not be reloaded")
    snapshot["ok"] = True
    snapshot["stopped"] = stopped or not snapshot.get("running")
    return snapshot


def restart_project_service(project_id: str, service_id: str) -> dict[str, Any]:
    existing = get_project_service(project_id, service_id)
    if not existing:
        raise ValueError("Service not found")
    stop_project_service(project_id, service_id)
    return start_project_service(
        project_id,
        name=str(existing.get("name") or service_id),
        command=str(existing.get("command") or ""),
        kind=str(existing.get("kind") or ""),
        cwd=str(existing.get("cwd") or ""),
        port=_coerce_port(existing.get("port")),
        health_url=str(existing.get("health_url") or ""),
        service_id=service_id,
    )


def read_project_service_log(project_id: str, service_id: str, max_bytes: int = 16000) -> dict[str, Any]:
    service = get_project_service(project_id, service_id)
    if not service:
        return {"ok": False, "error": "Service not found"}
    log_path = str(service.get("log_path") or "").strip()
    if not log_path:
        return {"ok": False, "error": "Service log path not found"}
    try:
        with open(log_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size > max_bytes:
                fh.seek(-max_bytes, os.SEEK_END)
            else:
                fh.seek(0)
            raw = fh.read()
        text = raw.decode("utf-8", errors="replace")
        if size > max_bytes:
            newline = text.find("\n")
            if newline != -1:
                text = text[newline + 1:]
        return {"ok": True, "content": text, "log_path": log_path, "truncated": size > max_bytes}
    except FileNotFoundError:
        return {"ok": False, "error": "Log file not found", "log_path": log_path}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "log_path": log_path}


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

def git_status(project_path: str) -> dict:
    """Return a structured git status for the project."""
    project_path = _normalize_path(project_path)

    def _run(cmd: list[str]) -> str:
        try:
            r = subprocess.run(cmd, cwd=project_path, capture_output=True, text=True, timeout=10)
            return r.stdout.strip()
        except Exception:
            return ""

    if not os.path.isdir(project_path):
        return {"ok": False, "error": f"Directory not found: {project_path}", "is_git": False}
    # Also accept worktrees / git repos without a .git dir (submodules use .git files)
    git_dir = os.path.join(project_path, ".git")
    if not os.path.exists(git_dir):
        # Try: git rev-parse to detect any git repo (handles worktrees, submodules)
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=project_path, capture_output=True, text=True, timeout=5
            )
            if r.returncode != 0:
                return {"ok": False, "error": "Not a git repository", "is_git": False}
        except Exception:
            return {"ok": False, "error": "Not a git repository", "is_git": False}
    elif not os.path.isdir(git_dir) and not os.path.isfile(git_dir):
        return {"ok": False, "error": "Not a git repository", "is_git": False}

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    remote = _run(["git", "remote", "get-url", "origin"])
    short_status = _run(["git", "status", "--short"])
    last_commit = _run(["git", "log", "-1", "--oneline"])
    ahead_behind_raw = _run(["git", "rev-list", "--left-right", "--count", f"{branch}...origin/{branch}"])
    ahead, behind = 0, 0
    if "\t" in ahead_behind_raw:
        parts = ahead_behind_raw.split("\t")
        try:
            ahead, behind = int(parts[0]), int(parts[1])
        except Exception:
            pass

    changed: list[str] = []
    staged: list[str] = []
    untracked: list[str] = []
    for line in short_status.splitlines():
        if not line:
            continue
        xy = line[:2]
        fname = line[3:]
        if xy.startswith("?"):
            untracked.append(fname)
        elif xy[0] != " ":
            staged.append(fname)
        elif xy[1] != " ":
            changed.append(fname)

    return {
        "ok": True,
        "is_git": True,
        "branch": branch,
        "remote": remote,
        "last_commit": last_commit,
        "ahead": ahead,
        "behind": behind,
        "changed": changed,
        "staged": staged,
        "untracked": untracked,
        "clean": not changed and not staged and not untracked,
        "raw_status": short_status,
    }


def git_pull(project_path: str) -> dict:
    return run_shell("git pull", project_path, timeout=60)


def git_push(project_path: str, force: bool = False) -> dict:
    cmd = "git push --force" if force else "git push"
    return run_shell(cmd, project_path, timeout=60)


def git_add_all(project_path: str) -> dict:
    return run_shell("git add -A", project_path)


def git_commit(project_path: str, message: str) -> dict:
    safe_msg = message.replace('"', '\\"')
    return run_shell(f'git commit -m "{safe_msg}"', project_path)


def git_commit_and_push(project_path: str, message: str) -> dict:
    add = git_add_all(project_path)
    if not add["ok"] and add["returncode"] != 0:
        return add
    commit = git_commit(project_path, message)
    push = git_push(project_path)
    return {
        "ok": push["ok"],
        "add": add,
        "commit": commit,
        "push": push,
        "stdout": "\n".join([add["stdout"], commit["stdout"], push["stdout"]]).strip(),
        "stderr": "\n".join([add["stderr"], commit["stderr"], push["stderr"]]).strip(),
    }


def git_clone(url: str, dest_parent: str, name: str = "") -> dict:
    dest_parent = _normalize_path(dest_parent)
    os.makedirs(dest_parent, exist_ok=True)
    cmd = f"git clone {url}" + (f" {name}" if name else "")
    result = run_shell(cmd, dest_parent, timeout=120)
    if result["ok"]:
        clone_name = name or url.rstrip("/").split("/")[-1].replace(".git", "")
        cloned_path = os.path.join(dest_parent, clone_name)
        if os.path.isdir(cloned_path):
            entry = add_project(cloned_path)
            result["project"] = entry
    return result


def git_branches(project_path: str) -> dict:
    result = run_shell("git branch -a", project_path)
    branches = [b.strip().lstrip("* ") for b in result["stdout"].splitlines() if b.strip()]
    current = next((b.lstrip("* ") for b in result["stdout"].splitlines() if b.strip().startswith("*")), "")
    return {"ok": result["ok"], "branches": branches, "current": current}


def git_checkout(project_path: str, branch: str) -> dict:
    safe = branch.replace('"', '')
    return run_shell(f'git checkout "{safe}"', project_path)
