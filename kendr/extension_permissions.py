from __future__ import annotations

import hashlib
import json
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


def _normalize_access_mode(value, default: str = "sandbox") -> str:
    normalized = str(value or default).strip().lower()
    if normalized not in {"sandbox", "full_access"}:
        return str(default or "sandbox").strip().lower() or "sandbox"
    return normalized


def _normalize_desktop_permissions(payload, *, defaults: dict | None = None) -> dict:
    base = defaults if isinstance(defaults, dict) else {}
    raw = payload if isinstance(payload, dict) else {}
    return {
        "allow": _bool_value(raw.get("allow"), bool(base.get("allow", False))),
        "apps": _string_list(raw.get("apps", base.get("apps", []))),
        "access_mode": _normalize_access_mode(raw.get("access_mode"), str(base.get("access_mode", "sandbox") or "sandbox")),
        "warn_on_full_access": _bool_value(raw.get("warn_on_full_access"), bool(base.get("warn_on_full_access", True))),
    }


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
        "desktop": {
            "allow": False,
            "apps": [],
            "access_mode": "sandbox",
            "warn_on_full_access": True,
        },
    }
    kind = str(skill_type or "").strip().lower()
    catalog = str(catalog_id or "").strip().lower()
    if kind == "python":
        manifest["requires_approval"] = True
    elif kind == "catalog" and catalog == "web-search":
        manifest["network"]["allow"] = True
        manifest["network"]["domains"] = ["duckduckgo.com"]
    elif kind == "catalog" and catalog == "desktop-automation":
        manifest["desktop"] = {
            "allow": True,
            "apps": [
                "generic",
                "whatsapp",
                "telegram",
                "microsoft_365",
            ],
            "access_mode": "sandbox",
            "warn_on_full_access": True,
        }
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
    raw_desktop = raw.get("desktop", {}) if isinstance(raw.get("desktop"), dict) else {}

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
        "desktop": _normalize_desktop_permissions(raw_desktop, defaults=defaults.get("desktop", {})),
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
        "desktop_allowed": bool((manifest.get("desktop", {}) or {}).get("allow", False)),
        "desktop_apps": _string_list((manifest.get("desktop", {}) or {}).get("apps")),
        "desktop_access_mode": _normalize_access_mode((manifest.get("desktop", {}) or {}).get("access_mode"), "sandbox"),
        "desktop_warn_on_full_access": bool((manifest.get("desktop", {}) or {}).get("warn_on_full_access", True)),
    }


def permission_manifest_hash(manifest: dict) -> str:
    serialized = json.dumps(normalize_permission_manifest(manifest), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def permission_manifest_items(manifest: dict) -> list[str]:
    summary = summarize_permission_manifest(manifest)
    items: list[str] = []
    if summary.get("filesystem_read_roots"):
        items.append(f"Filesystem read roots: {summary['filesystem_read_roots']}")
    if summary.get("filesystem_write_roots"):
        items.append(f"Filesystem write roots: {summary['filesystem_write_roots']}")
    env_keys = summary.get("environment_keys", []) or []
    if env_keys:
        items.append("Environment keys: " + ", ".join(env_keys))
    if summary.get("shell_allowed"):
        items.append("Shell execution enabled")
    if summary.get("network_allowed"):
        domains = summary.get("network_domains", []) or []
        items.append("Network domains: " + (", ".join(domains) if domains else "any"))
    if summary.get("desktop_allowed"):
        desktop_apps = summary.get("desktop_apps", []) or []
        desktop_mode = str(summary.get("desktop_access_mode", "sandbox") or "sandbox")
        items.append(
            "Desktop automation: "
            + ("full local access" if desktop_mode == "full_access" else "sandbox preview")
            + (" for " + ", ".join(desktop_apps) if desktop_apps else "")
        )
        if desktop_mode == "full_access" and summary.get("desktop_warn_on_full_access"):
            items.append("Warning: full access can launch or hand off to native applications outside the OS sandbox")
    if not items:
        items.append("No elevated permissions declared")
    return items
