from __future__ import annotations

import os
from pathlib import Path


def _string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    raw = str(value).strip()
    return [raw] if raw else []


def _bool_value(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_paths(paths, *, cwd: str = "") -> list[str]:
    resolved: list[str] = []
    base = str(cwd or "").strip()
    base_path = Path(base).expanduser().resolve() if base else None
    for item in _string_list(paths):
        try:
            path_obj = Path(item).expanduser()
            if not path_obj.is_absolute() and base_path is not None:
                path_obj = (base_path / path_obj).resolve()
            else:
                path_obj = path_obj.resolve()
            normalized = str(path_obj)
        except Exception:
            normalized = str(item).strip()
        if normalized and normalized not in resolved:
            resolved.append(normalized)
    return resolved


def default_permission_manifest(*, skill_type: str = "", catalog_id: str = "", cwd: str = "") -> dict:
    manifest = {
        "requires_approval": False,
        "filesystem": {
            "read": [],
            "write": [],
        },
        "environment": {
            "read": [],
        },
        "network": {
            "allow": False,
            "domains": [],
        },
        "shell": {
            "allow": False,
            "allow_root": False,
            "allow_destructive": False,
        },
    }
    kind = str(skill_type or "").strip().lower()
    catalog = str(catalog_id or "").strip().lower()
    if kind == "python":
        manifest["requires_approval"] = True
    elif kind == "catalog" and catalog == "code-executor":
        manifest["requires_approval"] = True
    elif kind == "catalog" and catalog == "web-search":
        manifest["network"]["allow"] = True
        manifest["network"]["domains"] = ["api.duckduckgo.com"]
    elif kind == "catalog" and catalog == "shell-command":
        manifest["requires_approval"] = True
        manifest["shell"]["allow"] = True
        manifest["filesystem"]["read"] = _normalize_paths(["."], cwd=cwd)
        manifest["filesystem"]["write"] = _normalize_paths(["."], cwd=cwd)
    elif kind == "catalog" and catalog == "api-caller":
        manifest["requires_approval"] = True
        manifest["network"]["allow"] = True
    return manifest


def normalize_permission_manifest(
    payload: dict | None,
    *,
    skill_type: str = "",
    catalog_id: str = "",
    cwd: str = "",
) -> dict:
    defaults = default_permission_manifest(skill_type=skill_type, catalog_id=catalog_id, cwd=cwd)
    raw = payload if isinstance(payload, dict) else {}
    raw_fs = raw.get("filesystem", {}) if isinstance(raw.get("filesystem"), dict) else {}
    raw_env = raw.get("environment", {}) if isinstance(raw.get("environment"), dict) else {}
    raw_network = raw.get("network", {}) if isinstance(raw.get("network"), dict) else {}
    raw_shell = raw.get("shell", {}) if isinstance(raw.get("shell"), dict) else {}

    manifest = {
        "requires_approval": _bool_value(raw.get("requires_approval"), bool(defaults.get("requires_approval", False))),
        "filesystem": {
            "read": _normalize_paths(raw_fs.get("read", defaults["filesystem"]["read"]), cwd=cwd),
            "write": _normalize_paths(raw_fs.get("write", defaults["filesystem"]["write"]), cwd=cwd),
        },
        "environment": {
            "read": _string_list(raw_env.get("read", defaults["environment"]["read"])),
        },
        "network": {
            "allow": _bool_value(raw_network.get("allow"), bool(defaults["network"]["allow"])),
            "domains": [item.lower() for item in _string_list(raw_network.get("domains", defaults["network"]["domains"]))],
        },
        "shell": {
            "allow": _bool_value(raw_shell.get("allow"), bool(defaults["shell"]["allow"])),
            "allow_root": _bool_value(raw_shell.get("allow_root"), bool(defaults["shell"]["allow_root"])),
            "allow_destructive": _bool_value(raw_shell.get("allow_destructive"), bool(defaults["shell"]["allow_destructive"])),
        },
    }
    return manifest


def permission_manifest_from_metadata(
    metadata: dict | None,
    *,
    skill_type: str = "",
    catalog_id: str = "",
    cwd: str = "",
) -> dict:
    raw = metadata if isinstance(metadata, dict) else {}
    permissions = raw.get("permissions", {}) if isinstance(raw.get("permissions"), dict) else {}
    return normalize_permission_manifest(permissions, skill_type=skill_type, catalog_id=catalog_id, cwd=cwd)


def normalize_approval(payload: dict | None) -> dict:
    raw = payload if isinstance(payload, dict) else {}
    approved = _bool_value(raw.get("approved"), False)
    note = str(raw.get("note", "") or raw.get("reason", "") or "").strip()
    actor = str(raw.get("actor", "") or "user").strip() or "user"
    scope = str(raw.get("scope", "") or "").strip()
    return {
        "approved": approved,
        "note": note,
        "actor": actor,
        "scope": scope,
    }


def ensure_manifest_approval(manifest: dict, approval: dict | None, *, capability: str) -> dict:
    normalized = normalize_approval(approval)
    if manifest.get("requires_approval", False):
        if not normalized.get("approved", False):
            raise PermissionError(
                f"{capability} requires explicit approval. "
                "Pass approval={'approved': true, 'note': '...'} to execute it."
            )
        if not str(normalized.get("note", "")).strip():
            raise PermissionError(f"{capability} approval must include a non-empty note.")
    return normalized


def merge_permissions_into_metadata(
    metadata: dict | None,
    permissions: dict | None,
    *,
    skill_type: str = "",
    catalog_id: str = "",
    cwd: str = "",
) -> dict:
    merged = dict(metadata or {})
    merged["permissions"] = normalize_permission_manifest(
        permissions if isinstance(permissions, dict) else {},
        skill_type=skill_type,
        catalog_id=catalog_id,
        cwd=cwd,
    )
    return merged


def summarize_permission_manifest(manifest: dict) -> dict:
    fs = manifest.get("filesystem", {}) if isinstance(manifest.get("filesystem"), dict) else {}
    shell = manifest.get("shell", {}) if isinstance(manifest.get("shell"), dict) else {}
    network = manifest.get("network", {}) if isinstance(manifest.get("network"), dict) else {}
    env = manifest.get("environment", {}) if isinstance(manifest.get("environment"), dict) else {}
    return {
        "requires_approval": bool(manifest.get("requires_approval", False)),
        "filesystem_read_roots": len(_string_list(fs.get("read"))),
        "filesystem_write_roots": len(_string_list(fs.get("write"))),
        "environment_keys": _string_list(env.get("read")),
        "shell_allowed": bool(shell.get("allow", False)),
        "network_allowed": bool(network.get("allow", False)),
        "network_domains": _string_list(network.get("domains")),
    }
