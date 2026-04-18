from __future__ import annotations

import io
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from kendr.command_policy import classify_command, ensure_command_allowed
from kendr.desktop_automation_broker import execute_request as execute_desktop_automation_request
from kendr.extension_permissions import ensure_manifest_approval, normalize_permission_manifest, normalize_approval

def _json_safe(value):
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except Exception:
        return str(value)


def _allowed_builtins(*, open_func=None) -> dict[str, object]:
    source = __builtins__
    if isinstance(source, dict):
        builtins_dict = source
    else:
        builtins_dict = getattr(source, "__dict__", {})
    allowed = (
        "print", "len", "range", "enumerate", "zip", "map", "filter",
        "sorted", "reversed", "list", "dict", "set", "tuple", "str",
        "int", "float", "bool", "type", "isinstance", "hasattr",
        "getattr", "min", "max", "sum", "abs", "round",
        "repr", "format", "hex", "oct", "bin", "chr", "ord",
        "any", "all", "next", "iter", "Exception",
        "ValueError", "TypeError", "KeyError", "IndexError", "RuntimeError",
        "PermissionError", "FileNotFoundError",
    )
    payload = {key: builtins_dict.get(key) for key in allowed if key in builtins_dict}
    if open_func is not None:
        payload["open"] = open_func
    return payload


def _manifest_env_keys(manifest: dict) -> list[str]:
    env_manifest = manifest.get("environment", {}) if isinstance(manifest.get("environment"), dict) else {}
    keys: list[str] = []
    for item in env_manifest.get("read", []) if isinstance(env_manifest.get("read", []), list) else []:
        normalized = str(item or "").strip()
        if normalized and normalized not in keys:
            keys.append(normalized)
    return keys


def _path_allowed(path_value: str, allowed_roots: list[str]) -> bool:
    if not allowed_roots:
        return False
    try:
        target = Path(path_value).expanduser().resolve()
    except Exception:
        return False
    for item in allowed_roots:
        try:
            root = Path(item).expanduser().resolve()
        except Exception:
            continue
        if target == root or root in target.parents:
            return True
    return False


def _resolve_user_path(path_value: str | os.PathLike[str], cwd: str) -> str:
    raw = Path(path_value).expanduser()
    if raw.is_absolute():
        return str(raw.resolve())
    base = Path(cwd or os.getcwd()).expanduser().resolve()
    return str((base / raw).resolve())


def _safe_open_factory(manifest: dict, cwd: str):
    read_roots = list(manifest.get("filesystem", {}).get("read", []))
    write_roots = list(manifest.get("filesystem", {}).get("write", []))

    def _safe_open(path, mode="r", *args, **kwargs):
        resolved = _resolve_user_path(path, cwd)
        mutating = any(flag in str(mode or "") for flag in ("w", "a", "x", "+"))
        if mutating:
            if not _path_allowed(resolved, write_roots):
                raise PermissionError(f"Write access denied for path: {resolved}")
        else:
            if not _path_allowed(resolved, read_roots):
                raise PermissionError(f"Read access denied for path: {resolved}")
        return open(resolved, mode, *args, **kwargs)

    return _safe_open


class _RestrictedOs:
    def __init__(self, manifest: dict, cwd: str, *, injected_env: dict[str, str] | None = None):
        env_allow = set(_manifest_env_keys(manifest))
        source_env = injected_env if isinstance(injected_env, dict) else {}
        self.environ = {
            key: value
            for key, value in source_env.items()
            if key in env_allow and str(value).strip()
        }
        self.path = os.path
        self._cwd = str(cwd or os.getcwd())
        self._read_roots = list(manifest.get("filesystem", {}).get("read", []))

    def getenv(self, key: str, default=None):
        return self.environ.get(key, default)

    def getcwd(self) -> str:
        return self._cwd

    def listdir(self, path: str = ".") -> list[str]:
        resolved = _resolve_user_path(path, self._cwd)
        if not _path_allowed(resolved, self._read_roots):
            raise PermissionError(f"Read access denied for path: {resolved}")
        return os.listdir(resolved)

    def stat(self, path: str):
        resolved = _resolve_user_path(path, self._cwd)
        if not _path_allowed(resolved, self._read_roots):
            raise PermissionError(f"Read access denied for path: {resolved}")
        return os.stat(resolved)


def _build_python_globals(manifest: dict, cwd: str, *, injected_env: dict[str, str] | None = None) -> dict[str, object]:
    open_func = _safe_open_factory(manifest, cwd)
    return {
        "__builtins__": _allowed_builtins(open_func=open_func),
        "json": json,
        "os": _RestrictedOs(manifest, cwd, injected_env=injected_env),
    }

def _coerce_directory(path_value: str, *, fallback: str) -> str:
    candidate = Path(path_value).expanduser()
    try:
        resolved = candidate.resolve()
    except Exception:
        return str(Path(fallback).expanduser().resolve())
    if resolved.is_dir():
        return str(resolved)
    if resolved.exists():
        return str(resolved.parent)
    return str(Path(fallback).expanduser().resolve())


def _manifest_execution_roots(manifest: dict) -> list[str]:
    filesystem = manifest.get("filesystem", {}) if isinstance(manifest.get("filesystem"), dict) else {}
    read_roots = filesystem.get("read", []) if isinstance(filesystem.get("read", []), list) else []
    write_roots = filesystem.get("write", []) if isinstance(filesystem.get("write", []), list) else []
    ordered: list[str] = []
    for item in [*write_roots, *read_roots]:
        normalized = str(item or "").strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _select_execution_cwd(
    manifest: dict,
    *,
    requested_cwd: str = "",
    workspace_root: str = "",
    isolated_root: str,
) -> str:
    allowed_roots = _manifest_execution_roots(manifest)
    resolution_base = workspace_root or isolated_root
    if str(requested_cwd or "").strip():
        resolved = _resolve_user_path(requested_cwd, resolution_base)
        if not _path_allowed(resolved, allowed_roots):
            raise PermissionError(f"Working directory is outside the allowed filesystem scope: {resolved}")
        return _coerce_directory(resolved, fallback=isolated_root)
    if allowed_roots:
        return _coerce_directory(allowed_roots[0], fallback=isolated_root)
    return str(Path(isolated_root).expanduser().resolve())


def _apply_process_resource_limits(timeout_seconds: int, *, memory_limit_mb: int = 0) -> None:
    try:
        import resource
    except Exception:
        return
    if hasattr(resource, "RLIMIT_CPU"):
        try:
            cpu_limit = max(2, int(timeout_seconds or 1) + 1)
            soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
            target_soft = cpu_limit if soft in (-1, resource.RLIM_INFINITY) or soft > cpu_limit else soft
            target_hard = cpu_limit if hard in (-1, resource.RLIM_INFINITY) or hard > cpu_limit else hard
            if target_soft > 0 and target_hard > 0 and target_soft <= target_hard:
                resource.setrlimit(resource.RLIMIT_CPU, (target_soft, target_hard))
        except Exception:
            pass
    if int(memory_limit_mb or 0) > 0 and hasattr(resource, "RLIMIT_AS"):
        try:
            address_limit = int(memory_limit_mb) * 1024 * 1024
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            target_soft = address_limit if soft in (-1, resource.RLIM_INFINITY) or soft > address_limit else soft
            target_hard = address_limit if hard in (-1, resource.RLIM_INFINITY) or hard > address_limit else hard
            if target_soft > 0 and target_hard > 0 and target_soft <= target_hard:
                resource.setrlimit(resource.RLIMIT_AS, (target_soft, target_hard))
        except Exception:
            pass


def _run_python_skill(
    code: str,
    inputs: dict,
    timeout_seconds: int,
    *,
    permissions: dict | None = None,
    approval: dict | None = None,
    cwd: str = "",
    workspace_root: str = "",
    isolated_root: str = "",
    injected_env: dict[str, str] | None = None,
) -> dict:
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    local_ns: dict[str, Any] = {"input": inputs, "inputs": inputs, "output": None}
    manifest = normalize_permission_manifest(
        permissions,
        skill_type="python",
        cwd=str(workspace_root or cwd or "").strip(),
    )
    try:
        ensure_manifest_approval(manifest, approval, capability="Python skill")
        exec_cwd = _select_execution_cwd(
            manifest,
            requested_cwd=cwd,
            workspace_root=workspace_root,
            isolated_root=isolated_root or tempfile.gettempdir(),
        )
        safe_globals = _build_python_globals(manifest, exec_cwd, injected_env=injected_env)
        _apply_process_resource_limits(
            timeout_seconds,
            memory_limit_mb=int(os.getenv("KENDR_EXTENSION_HOST_MAX_MEMORY_MB", "0") or "0"),
        )

        def _timeout_handler(signum, frame):
            raise TimeoutError(f"Skill execution timed out after {timeout_seconds}s")

        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_seconds)

        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(code, safe_globals, local_ns)  # noqa: S102

        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)

        return {
            "output": _json_safe(local_ns.get("output")),
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "success": True,
            "error": None,
        }
    except TimeoutError as exc:
        return {"output": None, "stdout": "", "stderr": "", "success": False, "error": str(exc)}
    except PermissionError as exc:
        return {
            "output": _json_safe(local_ns.get("output")),
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "success": False,
            "error": str(exc),
        }
    except Exception:
        return {
            "output": _json_safe(local_ns.get("output")),
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "success": False,
            "error": traceback.format_exc(),
        }


def _allowed_child_env() -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "USERPROFILE",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TMP",
        "TEMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "TERM",
        "PYTHONIOENCODING",
    }
    return {
        key: value
        for key, value in os.environ.items()
        if key in allowed and str(value).strip()
    }


def _build_child_env(manifest: dict, *, isolated_root: str = "", injected_env: dict[str, str] | None = None) -> dict[str, str]:
    child_env = dict(_allowed_child_env())
    source_env = injected_env if isinstance(injected_env, dict) else {}
    for key in _manifest_env_keys(manifest):
        value = str(source_env.get(key, "") or "").strip()
        if value:
            child_env[key] = value
    if str(isolated_root or "").strip():
        child_env["TMPDIR"] = isolated_root
        child_env["TMP"] = isolated_root
        child_env["TEMP"] = isolated_root
    return child_env


def _subprocess_group_kwargs() -> dict[str, object]:
    if os.name == "nt":
        flag = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": flag} if flag else {}
    return {"start_new_session": True}


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/F", "/T"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _extract_network_hosts(command: str) -> list[str]:
    hosts = []
    for match in re.findall(r"https?://([^/\s\"']+)", str(command or "")):
        host = str(match).split("@")[-1].split(":")[0].strip().lower()
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _host_allowed(host: str, allowed_domains: list[str]) -> bool:
    if not allowed_domains:
        return True
    lowered = str(host or "").strip().lower()
    return any(lowered == item or lowered.endswith("." + item) for item in allowed_domains)


def _ensure_network_allowed(manifest: dict, approval: dict | None, *, url: str, capability: str) -> dict:
    normalized_approval = ensure_manifest_approval(manifest, approval, capability=capability)
    network_manifest = manifest.get("network", {}) if isinstance(manifest.get("network"), dict) else {}
    if not network_manifest.get("allow", False):
        raise PermissionError("Network access is disabled by the permission manifest.")
    parsed = urllib_parse.urlparse(str(url or ""))
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        raise PermissionError("A valid network host is required.")
    if not _host_allowed(host, list(network_manifest.get("domains", []))):
        raise PermissionError(f"Network host is outside the allowed domain scope: {host}")
    return normalized_approval


def _run_shell_command(
    command: str,
    cwd: str | None,
    timeout_seconds: int,
    *,
    permissions: dict | None = None,
    approval: dict | None = None,
    workspace_root: str = "",
    isolated_root: str = "",
    injected_env: dict[str, str] | None = None,
) -> dict:
    requested_cwd = str(cwd or "").strip()
    manifest = normalize_permission_manifest(
        permissions,
        skill_type="catalog",
        catalog_id="shell-command",
        cwd=str(workspace_root or requested_cwd or "").strip(),
    )
    normalized_approval = ensure_manifest_approval(manifest, approval, capability="Shell command skill")
    if not manifest.get("shell", {}).get("allow", False):
        raise PermissionError("Shell command execution is disabled by the permission manifest.")
    exec_cwd = _select_execution_cwd(
        manifest,
        requested_cwd=requested_cwd,
        workspace_root=workspace_root,
        isolated_root=isolated_root or tempfile.gettempdir(),
    )
    policy = {
        "approved": normalized_approval.get("approved", False),
        "approval_note": normalized_approval.get("note", ""),
        "auto_approve": False,
        "require_approvals": bool(manifest.get("requires_approval", False)),
        "read_only": False,
        "allow_root": bool(manifest.get("shell", {}).get("allow_root", False)),
        "allow_destructive": bool(manifest.get("shell", {}).get("allow_destructive", False)),
        "allowed_paths": sorted({
            *manifest.get("filesystem", {}).get("read", []),
            *manifest.get("filesystem", {}).get("write", []),
        }),
    }
    ensure_command_allowed(command, exec_cwd, policy)
    classification = classify_command(command)
    network_manifest = manifest.get("network", {})
    if classification.get("networking") and not network_manifest.get("allow", False):
        raise PermissionError("Network access is disabled by the permission manifest.")
    for host in _extract_network_hosts(command):
        if not _host_allowed(host, list(network_manifest.get("domains", []))):
            raise PermissionError(f"Network host is outside the allowed domain scope: {host}")
    proc = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=exec_cwd or None,
        env=_build_child_env(manifest, isolated_root=isolated_root, injected_env=injected_env),
        **_subprocess_group_kwargs(),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=2)
        except Exception:
            stdout, stderr = "", ""
        raise TimeoutError(f"Shell command timed out after {timeout_seconds}s")
    return {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": int(proc.returncode or 0),
        "cwd": exec_cwd,
    }


def _perform_http_request(
    *,
    url: str,
    method: str,
    headers: dict,
    body,
    timeout_seconds: int,
    permissions: dict | None = None,
    approval: dict | None = None,
    capability: str,
) -> dict:
    manifest = normalize_permission_manifest(permissions, skill_type="catalog", catalog_id="api-caller")
    _ensure_network_allowed(manifest, approval, url=url, capability=capability)
    body_bytes = None
    request_headers = {str(key): str(value) for key, value in (headers or {}).items()}
    if body is not None:
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib_request.Request(
        str(url or "").strip(),
        data=body_bytes,
        headers=request_headers,
        method=str(method or "GET").upper(),
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
            text = raw.decode("utf-8", errors="replace")
            content_type = str(response.headers.get("Content-Type", "") or "")
            if "json" in content_type.lower():
                try:
                    payload_body = json.loads(text)
                except Exception:
                    payload_body = text
            else:
                try:
                    payload_body = json.loads(text)
                except Exception:
                    payload_body = text
            return {
                "status_code": int(getattr(response, "status", 200) or 200),
                "body": payload_body,
                "headers": dict(response.headers.items()),
            }
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload_body = json.loads(raw)
        except Exception:
            payload_body = raw
        return {
            "status_code": int(exc.code),
            "body": payload_body,
            "headers": dict(exc.headers.items()) if exc.headers else {},
        }


def _run_web_search(query: str, num_results: int, *, permissions: dict | None = None, approval: dict | None = None) -> dict:
    from tasks.research_infra import fetch_search_results

    manifest = normalize_permission_manifest(permissions, skill_type="catalog", catalog_id="web-search")
    _ensure_network_allowed(
        manifest,
        approval,
        url="https://duckduckgo.com/",
        capability="Web search skill",
    )
    payload = fetch_search_results(
        str(query or "").strip(),
        num=max(1, int(num_results or 5)),
        fetch_pages=0,
        provider_hint="duckduckgo",
        focused_brief=str(query or "").strip(),
    )
    return {
        "query": str(query or "").strip(),
        "results": list(payload.get("results", []) or []),
        "provider": str(payload.get("provider", "") or "").strip(),
        "providers_tried": list(payload.get("providers_tried", []) or []),
        "instant_answer": payload.get("instant_answer", {}),
        "query_plan": list(payload.get("query_plan", []) or []),
        "source_surface": (
            "mcp:browser-use/browser_extract_content"
            if str(payload.get("provider", "") or "").strip() == "browser_use_mcp"
            else ("skill:web-search:serpapi" if str(payload.get("provider", "") or "").strip() == "serpapi" else "skill:web-search")
        ),
    }


def _run_desktop_automation(
    inputs: dict,
    *,
    timeout_seconds: int,
    permissions: dict | None = None,
    approval: dict | None = None,
) -> dict:
    manifest = normalize_permission_manifest(permissions, skill_type="catalog", catalog_id="desktop-automation")
    desktop_manifest = manifest.get("desktop", {}) if isinstance(manifest.get("desktop"), dict) else {}
    if not desktop_manifest.get("allow", False):
        raise PermissionError("Desktop automation is disabled by the permission manifest.")
    access_mode = str(desktop_manifest.get("access_mode", "sandbox") or "sandbox").strip().lower()
    if access_mode == "full_access":
        ensure_manifest_approval(manifest, approval, capability="Desktop automation full-access mode")
    return execute_desktop_automation_request(
        inputs if isinstance(inputs, dict) else {},
        access_mode=access_mode,
        timeout_seconds=timeout_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    mode = args[0] if args else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    with tempfile.TemporaryDirectory(prefix="kendr-extension-") as isolated_root:
        if mode == "python-skill":
            result = _run_python_skill(
                str(payload.get("code", "") or ""),
                payload.get("inputs", {}) if isinstance(payload.get("inputs"), dict) else {},
                max(1, int(payload.get("timeout", 10) or 10)),
                permissions=payload.get("permissions") if isinstance(payload.get("permissions"), dict) else None,
                approval=normalize_approval(payload.get("approval") if isinstance(payload.get("approval"), dict) else None),
                cwd=str(payload.get("cwd", "") or "").strip(),
                workspace_root=str(payload.get("workspace_root", "") or "").strip(),
                isolated_root=isolated_root,
                injected_env=payload.get("injected_env") if isinstance(payload.get("injected_env"), dict) else None,
            )
        elif mode == "shell-command":
            try:
                result = {
                    "output": _run_shell_command(
                        str(payload.get("command", "") or ""),
                        str(payload.get("cwd", "") or "").strip() or None,
                        max(1, int(payload.get("timeout", 30) or 30)),
                        permissions=payload.get("permissions") if isinstance(payload.get("permissions"), dict) else None,
                        approval=normalize_approval(payload.get("approval") if isinstance(payload.get("approval"), dict) else None),
                        workspace_root=str(payload.get("workspace_root", "") or "").strip(),
                        isolated_root=isolated_root,
                        injected_env=payload.get("injected_env") if isinstance(payload.get("injected_env"), dict) else None,
                    ),
                    "stdout": "",
                    "stderr": "",
                    "success": True,
                    "error": None,
                }
            except (PermissionError, TimeoutError) as exc:
                result = {
                    "output": None,
                    "stdout": "",
                    "stderr": "",
                    "success": False,
                    "error": str(exc),
                }
            except Exception:
                result = {"output": None, "stdout": "", "stderr": "", "success": False, "error": traceback.format_exc()}
        elif mode == "web-search":
            try:
                result = {
                    "output": _run_web_search(
                        str(payload.get("query", "") or ""),
                        int(payload.get("num_results", 5) or 5),
                        permissions=payload.get("permissions") if isinstance(payload.get("permissions"), dict) else None,
                        approval=normalize_approval(payload.get("approval") if isinstance(payload.get("approval"), dict) else None),
                    ),
                    "stdout": "",
                    "stderr": "",
                    "success": True,
                    "error": None,
                }
            except PermissionError as exc:
                result = {"output": None, "stdout": "", "stderr": "", "success": False, "error": str(exc)}
            except Exception:
                result = {"output": None, "stdout": "", "stderr": "", "success": False, "error": traceback.format_exc()}
        elif mode == "http-request":
            try:
                result = {
                    "output": _perform_http_request(
                        url=str(payload.get("url", "") or ""),
                        method=str(payload.get("method", "GET") or "GET"),
                        headers=payload.get("headers", {}) if isinstance(payload.get("headers"), dict) else {},
                        body=payload.get("body"),
                        timeout_seconds=max(1, int(payload.get("timeout", 15) or 15)),
                        permissions=payload.get("permissions") if isinstance(payload.get("permissions"), dict) else None,
                        approval=normalize_approval(payload.get("approval") if isinstance(payload.get("approval"), dict) else None),
                        capability="API caller skill",
                    ),
                    "stdout": "",
                    "stderr": "",
                    "success": True,
                    "error": None,
                }
            except PermissionError as exc:
                result = {"output": None, "stdout": "", "stderr": "", "success": False, "error": str(exc)}
            except Exception:
                result = {"output": None, "stdout": "", "stderr": "", "success": False, "error": traceback.format_exc()}
        elif mode == "desktop-automation":
            try:
                result = {
                    "output": _run_desktop_automation(
                        payload.get("inputs", {}) if isinstance(payload.get("inputs"), dict) else {},
                        timeout_seconds=max(1, int(payload.get("timeout", 10) or 10)),
                        permissions=payload.get("permissions") if isinstance(payload.get("permissions"), dict) else None,
                        approval=normalize_approval(payload.get("approval") if isinstance(payload.get("approval"), dict) else None),
                    ),
                    "stdout": "",
                    "stderr": "",
                    "success": True,
                    "error": None,
                }
            except PermissionError as exc:
                result = {"output": None, "stdout": "", "stderr": "", "success": False, "error": str(exc)}
            except Exception:
                result = {"output": None, "stdout": "", "stderr": "", "success": False, "error": traceback.format_exc()}
        else:
            result = {
                "output": None,
                "stdout": "",
                "stderr": "",
                "success": False,
                "error": f"Unsupported extension host mode: {mode!r}",
            }

    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
