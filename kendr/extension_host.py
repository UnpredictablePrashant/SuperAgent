from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from kendr.extension_permissions import ensure_manifest_approval, normalize_permission_manifest, normalize_approval
from tasks.privileged_control import classify_command, ensure_command_allowed

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
    def __init__(self, manifest: dict, cwd: str):
        env_allow = set(manifest.get("environment", {}).get("read", []))
        child_env = _allowed_child_env()
        self.environ = {key: value for key, value in child_env.items() if not env_allow or key in env_allow}
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


def _build_python_globals(manifest: dict, cwd: str) -> dict[str, object]:
    open_func = _safe_open_factory(manifest, cwd)
    return {
        "__builtins__": _allowed_builtins(open_func=open_func),
        "json": json,
        "os": _RestrictedOs(manifest, cwd),
    }

def _run_python_skill(code: str, inputs: dict, timeout_seconds: int, *, permissions: dict | None = None, approval: dict | None = None, cwd: str = "") -> dict:
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    local_ns: dict[str, Any] = {"input": inputs, "inputs": inputs, "output": None}
    manifest = normalize_permission_manifest(permissions, skill_type="python", cwd=cwd)
    try:
        ensure_manifest_approval(manifest, approval, capability="Python skill")
        safe_globals = _build_python_globals(manifest, cwd)
        import signal

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


def _run_shell_command(command: str, cwd: str | None, timeout_seconds: int, *, permissions: dict | None = None, approval: dict | None = None) -> dict:
    exec_cwd = str(cwd or os.getcwd())
    manifest = normalize_permission_manifest(permissions, skill_type="catalog", catalog_id="shell-command", cwd=exec_cwd)
    normalized_approval = ensure_manifest_approval(manifest, approval, capability="Shell command skill")
    if not manifest.get("shell", {}).get("allow", False):
        raise PermissionError("Shell command execution is disabled by the permission manifest.")
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
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        cwd=exec_cwd or None,
        timeout=timeout_seconds,
        env=_allowed_child_env(),
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
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
    manifest = normalize_permission_manifest(permissions, skill_type="catalog", catalog_id="web-search")
    _ensure_network_allowed(
        manifest,
        approval,
        url="https://api.duckduckgo.com/",
        capability="Web search skill",
    )
    params = urllib_parse.urlencode(
        {
            "q": str(query or "").strip(),
            "format": "json",
            "no_redirect": 1,
        }
    )
    url = f"https://api.duckduckgo.com/?{params}"
    request = urllib_request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib_request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    results = []
    for topic in (payload.get("RelatedTopics") or [])[: max(1, int(num_results or 5))]:
        if isinstance(topic, dict) and topic.get("Text"):
            results.append(
                {
                    "title": topic.get("Text", ""),
                    "url": topic.get("FirstURL", ""),
                    "snippet": topic.get("Text", ""),
                }
            )
    return {"query": str(query or "").strip(), "results": results}


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    mode = args[0] if args else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    if mode == "python-skill":
        result = _run_python_skill(
            str(payload.get("code", "") or ""),
            payload.get("inputs", {}) if isinstance(payload.get("inputs"), dict) else {},
            max(1, int(payload.get("timeout", 10) or 10)),
            permissions=payload.get("permissions") if isinstance(payload.get("permissions"), dict) else None,
            approval=normalize_approval(payload.get("approval") if isinstance(payload.get("approval"), dict) else None),
            cwd=str(payload.get("cwd", "") or "").strip(),
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
                ),
                "stdout": "",
                "stderr": "",
                "success": True,
                "error": None,
            }
        except PermissionError as exc:
            result = {
                "output": None,
                "stdout": "",
                "stderr": "",
                "success": False,
                "error": str(exc),
            }
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
