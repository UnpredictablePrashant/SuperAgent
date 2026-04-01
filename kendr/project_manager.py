"""Project Manager — kendr project workspace backend.

Stores a registry of known project directories and provides:
  - File tree reading
  - File content access
  - Shell command execution
  - Git operations (status, pull, push, commit, clone, branch)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("kendr.project_manager")


def _normalize_path(path: str) -> str:
    """Expand ~ and resolve to an absolute real path."""
    return str(Path(path).expanduser().resolve())


_DEFAULT_STORE = os.path.join(os.path.expanduser("~"), ".kendr", "projects.json")
_PROJECTS_STORE = os.getenv("KENDR_PROJECTS_STORE", _DEFAULT_STORE)
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

def _load_store() -> dict:
    try:
        os.makedirs(os.path.dirname(_PROJECTS_STORE), exist_ok=True)
        if os.path.isfile(_PROJECTS_STORE):
            with open(_PROJECTS_STORE, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as exc:
        _log.warning("Could not load projects store: %s", exc)
    return {"projects": {}, "active": None}


def _save_store(store: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_PROJECTS_STORE), exist_ok=True)
        with open(_PROJECTS_STORE, "w", encoding="utf-8") as fh:
            json.dump(store, fh, indent=2)
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
    }
    with _store_lock:
        store = _load_store()
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
        if project_id not in store.get("projects", {}):
            return False
        del store["projects"][project_id]
        if store.get("active") == project_id:
            remaining = list(store.get("projects", {}).keys())
            store["active"] = remaining[0] if remaining else None
        _save_store(store)
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
        del store["projects"][project_id]
        if store.get("active") == project_id:
            remaining = list(store.get("projects", {}).keys())
            store["active"] = remaining[0] if remaining else None
        _save_store(store)
    if project_path and os.path.isdir(project_path):
        try:
            _shutil.rmtree(project_path)
            return {"ok": True, "deleted_path": project_path}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "deleted_path": project_path}
    return {"ok": True, "deleted_path": None, "warning": "Directory not found on disk"}


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
    path_parts = base.get("PATH", "").split(":")
    extra_paths = [
        "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
        "/nix/var/nix/profiles/default/bin",
    ]
    for p in extra_paths:
        if p and p not in path_parts:
            path_parts.append(p)
    base["PATH"] = ":".join(p for p in path_parts if p)
    base.setdefault("TERM", "xterm-256color")
    base.setdefault("LANG", "en_US.UTF-8")
    return base


def run_shell(command: str, cwd: str, timeout: int = 60) -> dict:
    """Run a shell command in the given directory via bash. Returns stdout, stderr, exit code."""
    cwd = _normalize_path(cwd)
    try:
        result = subprocess.run(
            ["/bin/bash", "-c", command],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_build_shell_env(),
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "command": command,
            "cwd": cwd,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"Command timed out after {timeout}s", "returncode": -1, "command": command, "cwd": cwd}
    except Exception as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc), "returncode": -1, "command": command, "cwd": cwd}


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
