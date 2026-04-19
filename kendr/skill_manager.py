"""Skill Manager — install, uninstall, create, test, and list skills.

Skills are callable tools that agents discover and invoke. Three kinds:
  - catalog  : pre-built system skills (installed from the marketplace)
  - python   : user-defined Python function (code stored in DB, executed sandboxed)
  - prompt   : user-defined prompt template (executed via the LLM)
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from kendr import desktop_automation_broker, extension_sandbox
from kendr.providers import get_google_access_token, get_microsoft_graph_access_token
from kendr.extension_permissions import (
    merge_permissions_into_metadata,
    normalize_approval,
    permission_manifest_hash,
    permission_manifest_from_metadata,
    permission_manifest_items,
    summarize_permission_manifest,
)
from kendr.persistence import (
    consume_approval_grant,
    create_approval_grant,
    create_user_skill,
    delete_user_skill,
    find_matching_approval_grant,
    get_user_skill,
    insert_privileged_audit_event,
    list_approval_grants,
    list_user_skills,
    revoke_approval_grant,
    set_skill_installed,
    update_user_skill,
)
from kendr.skill_catalog import CATALOG_BY_ID, list_catalog_skills, catalog_categories
from kendr.workflow_contract import approval_request_to_text, build_approval_request


# ---------------------------------------------------------------------------
# Marketplace listing
# ---------------------------------------------------------------------------

def get_marketplace(q: str = "", category: str = "") -> dict:
    """Return catalog skills enriched with their installed state."""
    catalog = [
        item
        for item in list_catalog_skills(category=category, q=q)
        if _catalog_skill_is_marketplace_usable(item)
    ]

    # Map slug → installed row
    all_rows = {r["slug"]: r for r in list_user_skills()}
    installed_rows = {slug: row for slug, row in all_rows.items() if bool(row.get("is_installed"))}

    for item in catalog:
        slug = item["id"]
        installed_row = all_rows.get(slug)
        core_row = _build_core_skill_row(slug)
        effective_row = resolve_runtime_skill(skill_id=str(installed_row.get("skill_id", ""))) if installed_row else core_row
        if isinstance(effective_row, dict):
            effective_row = _attach_skill_surface(effective_row) or effective_row
        item["is_core"] = bool(item.get("is_core", False))
        item["is_installed"] = bool(effective_row and effective_row.get("is_installed", True))
        item["skill_id"] = effective_row["skill_id"] if effective_row else (installed_row.get("skill_id") if installed_row else None)
        item["permission_manifest"] = (
            effective_row.get("permission_manifest", {})
            if isinstance(effective_row, dict)
            else permission_manifest_from_metadata({}, skill_type="catalog", catalog_id=slug, cwd=_default_execution_cwd())
        )
        item["sandbox"] = (
            effective_row.get("sandbox", extension_sandbox.describe_skill_sandbox(skill_type="catalog", catalog_id=slug))
            if isinstance(effective_row, dict)
            else extension_sandbox.describe_skill_sandbox(skill_type="catalog", catalog_id=slug)
        )
        if isinstance(effective_row, dict) and isinstance(effective_row.get("desktop_automation"), dict):
            item["desktop_automation"] = effective_row["desktop_automation"]

    # Append custom (python/prompt) skills that are installed
    custom = [
        _attach_skill_surface(r) or r for r in list_user_skills()
        if r["skill_type"] in ("python", "prompt")
    ]

    core_count = sum(1 for item in catalog if bool(item.get("is_core")) and bool(item.get("is_installed")))

    return {
        "catalog": catalog,
        "custom": custom,
        "categories": [name for name in catalog_categories() if any(item.get("category") == name for item in catalog)],
        "installed_count": len(installed_rows) + core_count + len([c for c in custom if c["is_installed"]]),
        "sandbox_runtime": extension_sandbox.describe_runtime_support(),
    }


def _catalog_skill_is_marketplace_usable(item: dict) -> bool:
    catalog_id = str(item.get("id", "") or "").strip()
    if not catalog_id:
        return False
    if catalog_id not in _catalog_handlers():
        return False
    entry = CATALOG_BY_ID.get(catalog_id)
    required_config = tuple(getattr(entry, "requires_config", ()) or ())
    if required_config and any(not str(os.getenv(key, "")).strip() for key in required_config):
        return False
    sandbox = extension_sandbox.describe_skill_sandbox(skill_type="catalog", catalog_id=catalog_id)
    return str(sandbox.get("mode", "") or "").strip().lower() != "blocked"


def _catalog_metadata(entry, *, existing_metadata: dict | None = None) -> dict:
    base = dict(existing_metadata or {})
    raw_permissions = base.pop("permissions", None) if isinstance(base.get("permissions"), dict) else None
    existing_permissions = raw_permissions if isinstance(raw_permissions, dict) and raw_permissions else None
    if bool(getattr(entry, "core", False)):
        # Core catalog permissions are owned by the catalog definition, not
        # persisted rows. Installed rows can carry stale normalized manifests
        # from older versions, which should not override current core policy.
        existing_permissions = None
    if entry.requires_config:
        base.setdefault("requires_config", list(entry.requires_config))
    if getattr(entry, "core", False):
        base.setdefault("core_skill", True)
    return merge_permissions_into_metadata(
        base,
        existing_permissions
        if isinstance(existing_permissions, dict)
        else getattr(entry, "default_permissions", {}) if isinstance(getattr(entry, "default_permissions", {}), dict) else {},
        skill_type="catalog",
        catalog_id=entry.id,
        cwd=_default_execution_cwd(),
    )


def _attach_skill_surface(row: dict | None) -> dict | None:
    if not isinstance(row, dict):
        return None
    enriched = dict(row)
    skill_type = str(enriched.get("skill_type", "") or "").strip()
    catalog_id = str(enriched.get("catalog_id", "") or "").strip()
    permission_manifest = permission_manifest_from_metadata(
        enriched.get("metadata", {}) if isinstance(enriched.get("metadata"), dict) else {},
        skill_type=skill_type,
        catalog_id=catalog_id,
        cwd=_default_execution_cwd(),
    )
    enriched["permission_manifest"] = permission_manifest
    enriched["sandbox"] = extension_sandbox.describe_skill_sandbox(
        skill_type=skill_type,
        catalog_id=catalog_id,
    )
    if skill_type == "catalog" and catalog_id == "desktop-automation":
        enriched["desktop_automation"] = desktop_automation_broker.describe_capability()
    return enriched


def _build_core_skill_row(catalog_id: str) -> dict | None:
    entry = CATALOG_BY_ID.get(catalog_id)
    if not entry or not bool(getattr(entry, "core", False)):
        return None
    return {
        "skill_id": f"core:{entry.id}",
        "name": entry.name,
        "slug": entry.id,
        "description": entry.description,
        "category": entry.category,
        "icon": entry.icon,
        "skill_type": "catalog",
        "catalog_id": entry.id,
        "code": "",
        "input_schema": dict(entry.input_schema),
        "output_schema": dict(entry.output_schema),
        "tags": list(entry.tags),
        "metadata": _catalog_metadata(entry),
        "is_installed": True,
        "status": "active",
    }


def resolve_runtime_skill(*, skill_id: str = "", slug: str = "") -> dict | None:
    row = None
    catalog_id = ""
    if skill_id:
        if skill_id.startswith("core:"):
            return _attach_skill_surface(_build_core_skill_row(skill_id.split("core:", 1)[1].strip()))
        row = get_user_skill(skill_id=skill_id)
    elif slug:
        row = get_user_skill(slug=slug)
    if row:
        if row.get("skill_type") == "catalog":
            catalog_id = str(row.get("catalog_id", "") or str(row.get("slug", ""))).strip()
            entry = CATALOG_BY_ID.get(catalog_id)
            if entry:
                if not bool(row.get("is_installed", False)):
                    return None if bool(getattr(entry, "core", False)) else None
                row = dict(row)
                row["metadata"] = _catalog_metadata(entry, existing_metadata=row.get("metadata", {}))
        return _attach_skill_surface(row)
    if slug:
        return _attach_skill_surface(_build_core_skill_row(slug))
    return None


def list_runtime_skills() -> list[dict]:
    rows = list_user_skills()
    by_slug: dict[str, dict] = {}
    disabled_core_slugs: set[str] = set()
    for row in rows:
        slug = str(row.get("slug", "")).strip()
        if not slug:
            continue
        if not bool(row.get("is_installed", False)):
            if str(row.get("skill_type", "") or "").strip() == "catalog":
                disabled_core_slugs.add(slug)
            continue
        resolved = resolve_runtime_skill(skill_id=str(row.get("skill_id", "")).strip()) or dict(row)
        by_slug[slug] = resolved
    for catalog_id, entry in CATALOG_BY_ID.items():
        if bool(getattr(entry, "core", False)) and catalog_id not in by_slug and catalog_id not in disabled_core_slugs:
            core_row = _build_core_skill_row(catalog_id)
            if core_row:
                by_slug[catalog_id] = _attach_skill_surface(core_row) or core_row
    return sorted(by_slug.values(), key=lambda item: str(item.get("name", item.get("slug", ""))).lower())


# ---------------------------------------------------------------------------
# Install / Uninstall catalog skill
# ---------------------------------------------------------------------------

def install_catalog_skill(catalog_id: str) -> dict:
    """Install a catalog skill — persists as a user_skill row with is_installed=True."""
    entry = CATALOG_BY_ID.get(catalog_id)
    if not entry:
        raise ValueError(f"No catalog skill with id {catalog_id!r}")

    metadata = _catalog_metadata(entry)

    existing = get_user_skill(slug=catalog_id)
    if existing and existing["is_installed"]:
        updated = update_user_skill(existing["skill_id"], metadata=metadata)
        return updated or existing

    if existing:
        update_user_skill(existing["skill_id"], metadata=metadata)
        set_skill_installed(existing["skill_id"], True)
        return get_user_skill(skill_id=existing["skill_id"])  # type: ignore[return-value]

    return create_user_skill(
        name=entry.name,
        slug=entry.id,
        description=entry.description,
        category=entry.category,
        icon=entry.icon,
        skill_type="catalog",
        catalog_id=entry.id,
        code="",
        input_schema=dict(entry.input_schema),
        output_schema=dict(entry.output_schema),
        tags=list(entry.tags),
        metadata=metadata,
        is_installed=True,
        status="active",
    )


def uninstall_catalog_skill(catalog_id: str) -> bool:
    """Mark a catalog skill as uninstalled (does not delete custom skills)."""
    existing = get_user_skill(slug=catalog_id)
    if not existing:
        entry = CATALOG_BY_ID.get(catalog_id)
        if not entry:
            return False
        if not bool(getattr(entry, "core", False)):
            return False
        create_user_skill(
            name=entry.name,
            slug=entry.id,
            description=entry.description,
            category=entry.category,
            icon=entry.icon,
            skill_type="catalog",
            catalog_id=entry.id,
            code="",
            input_schema=dict(entry.input_schema),
            output_schema=dict(entry.output_schema),
            tags=list(entry.tags),
            metadata=_catalog_metadata(entry),
            is_installed=False,
            status="inactive",
        )
        return True
    if existing["skill_type"] != "catalog":
        raise ValueError("Use delete_custom_skill for non-catalog skills.")
    set_skill_installed(existing["skill_id"], False)
    return True


# ---------------------------------------------------------------------------
# Create / Update / Delete custom skills
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "skill"


def _unique_slug(base: str) -> str:
    slug = base
    n = 1
    while get_user_skill(slug=slug):
        slug = f"{base}-{n}"
        n += 1
    return slug


def create_custom_skill(
    *,
    name: str,
    description: str = "",
    category: str = "Custom",
    icon: str = "⚡",
    skill_type: str,     # 'python' | 'prompt'
    code: str,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
    tags: list[str] | None = None,
    metadata: dict | None = None,
    permissions: dict | None = None,
) -> dict:
    if skill_type not in ("python", "prompt"):
        raise ValueError("skill_type must be 'python' or 'prompt'")
    slug = _unique_slug(_slugify(name))
    return create_user_skill(
        name=name,
        slug=slug,
        description=description,
        category=category,
        icon=icon,
        skill_type=skill_type,
        code=code,
        input_schema=input_schema or {},
        output_schema=output_schema or {},
        tags=tags or [],
        metadata=merge_permissions_into_metadata(
            metadata,
            permissions,
            skill_type=skill_type,
            cwd=_default_execution_cwd(),
        ),
        is_installed=True,
        status="active",
    )


def edit_custom_skill(skill_id: str, **kwargs) -> dict | None:
    if "permissions" in kwargs:
        current = resolve_runtime_skill(skill_id=skill_id)
        if current:
            kwargs["metadata"] = merge_permissions_into_metadata(
                kwargs.get("metadata") if isinstance(kwargs.get("metadata"), dict) else current.get("metadata", {}),
                kwargs.pop("permissions"),
                skill_type=str(current.get("skill_type", "") or ""),
                catalog_id=str(current.get("catalog_id", "") or ""),
                cwd=_default_execution_cwd(),
            )
    return update_user_skill(skill_id, **kwargs)


def remove_custom_skill(skill_id: str) -> bool:
    row = resolve_runtime_skill(skill_id=skill_id)
    if not row:
        return False
    if row["skill_type"] == "catalog":
        raise ValueError("Use uninstall_catalog_skill for catalog skills.")
    return delete_user_skill(skill_id)


# ---------------------------------------------------------------------------
# Execution / Testing
# ---------------------------------------------------------------------------

_EXEC_TIMEOUT = 10  # seconds


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_execution_cwd() -> str:
    preferred = str(os.getenv("KENDR_WORKING_DIR", "")).strip()
    return preferred or os.getcwd()


def _contextualize_permission_manifest(row: dict, manifest: dict, inputs: dict) -> dict:
    if str(row.get("skill_type", "") or "").strip() == "catalog" and str(row.get("catalog_id", "") or "").strip() == "desktop-automation":
        return desktop_automation_broker.contextualize_manifest(manifest, inputs)
    return manifest


def _record_permission_event(skill_label: str, *, action: str, status: str, detail: dict) -> None:
    payload = {
        "event_id": f"skill-permission-{uuid.uuid4().hex}",
        "run_id": "",
        "timestamp": _utc_now(),
        "actor": skill_label,
        "action": action,
        "status": status,
        "detail": detail,
        "prev_hash": "",
        "event_hash": "",
    }
    try:
        insert_privileged_audit_event(payload)
    except Exception:
        pass


class SkillApprovalRequired(RuntimeError):
    def __init__(self, payload: dict):
        self.payload = payload
        super().__init__(str(payload.get("error", "approval_required")))


def _skill_subject_id(row: dict) -> str:
    slug = str(row.get("slug", "") or row.get("skill_id", "")).strip()
    return f"skill:{slug}"


def _skill_manifest_hash(manifest: dict) -> str:
    return permission_manifest_hash(manifest)


def _skill_grant_metadata(row: dict, manifest: dict) -> dict:
    return {
        "skill_id": str(row.get("skill_id", "")).strip(),
        "skill_slug": str(row.get("slug", "")).strip(),
        "skill_name": str(row.get("name", "")).strip(),
        "manifest_summary": summarize_permission_manifest(manifest),
    }


def _build_skill_approval_payload(row: dict, manifest: dict, *, session_id: str = "") -> dict:
    summary_items = permission_manifest_items(manifest)
    skill_name = str(row.get("name", row.get("slug", "Skill"))).strip() or "Skill"
    scope = f"skill_permission:{row.get('slug', row.get('skill_id', 'unknown'))}"
    manifest_hash = _skill_manifest_hash(manifest)
    request = build_approval_request(
        scope=scope,
        title=f"Approve skill execution for {skill_name}",
        summary=f"{skill_name} requires approval before execution because it requests elevated permissions.",
        sections=[
            {"title": "Requested permissions", "items": summary_items},
            {"title": "Grant options", "items": ["Allow once", "Allow for this session", "Always allow for this manifest"]},
        ],
        help_text="Create a grant with scope once, session, or always to continue.",
        metadata={
            "approval_mode": "skill_permission_grant",
            "subject_type": "skill",
            "subject_id": _skill_subject_id(row),
            "manifest_hash": manifest_hash,
            "skill_id": str(row.get("skill_id", "")).strip(),
            "skill_slug": str(row.get("slug", "")).strip(),
            "suggested_scopes": ["once", "session", "always"],
            "session_id": str(session_id or "").strip(),
            "permission_summary": summarize_permission_manifest(manifest),
        },
    )
    return {
        "success": False,
        "error_type": "approval_required",
        "error": f"{skill_name} requires explicit approval before execution.",
        "awaiting_user_input": True,
        "pending_user_input_kind": "skill_approval",
        "approval_pending_scope": scope,
        "approval_request": request,
        "pending_user_question": approval_request_to_text(request),
        "skill_id": str(row.get("skill_id", "")).strip(),
        "skill_slug": str(row.get("slug", "")).strip(),
        "manifest_hash": manifest_hash,
        "permission_manifest": manifest,
        "permission_summary": summarize_permission_manifest(manifest),
    }


def grant_skill_approval(
    *,
    skill_id: str = "",
    slug: str = "",
    scope: str,
    note: str,
    actor: str = "user",
    session_id: str = "",
) -> dict:
    row = resolve_runtime_skill(skill_id=skill_id, slug=slug)
    if not row:
        raise ValueError("skill_not_found")
    manifest = permission_manifest_from_metadata(
        row.get("metadata", {}),
        skill_type=str(row.get("skill_type", "") or ""),
        catalog_id=str(row.get("catalog_id", "") or ""),
        cwd=_default_execution_cwd(),
    )
    normalized_scope = str(scope or "once").strip().lower()
    if normalized_scope not in {"once", "session", "always"}:
        raise ValueError("scope must be one of: once, session, always")
    if not str(note or "").strip():
        raise ValueError("approval note is required")
    grant = create_approval_grant(
        subject_type="skill",
        subject_id=_skill_subject_id(row),
        manifest_hash=_skill_manifest_hash(manifest),
        scope=normalized_scope,
        actor=str(actor or "user").strip() or "user",
        note=str(note or "").strip(),
        session_id=str(session_id or "").strip(),
        permissions=manifest,
        metadata=_skill_grant_metadata(row, manifest),
    )
    _record_permission_event(
        f"skill:{row.get('slug', row.get('skill_id', 'unknown'))}",
        action="approval_grant_created",
        status="approved",
        detail={"grant": grant, "scope": normalized_scope},
    )
    return grant


def list_skill_approval_grants(*, skill_id: str = "", slug: str = "", session_id: str = "", status: str = "") -> list[dict]:
    row = resolve_runtime_skill(skill_id=skill_id, slug=slug)
    if not row:
        return []
    return list_approval_grants(
        subject_type="skill",
        subject_id=_skill_subject_id(row),
        session_id=str(session_id or "").strip(),
        status=str(status or "").strip(),
    )


def revoke_skill_approval(*, grant_id: str) -> dict | None:
    grant = revoke_approval_grant(grant_id)
    if grant:
        _record_permission_event(
            str(grant.get("subject_id", "skill")),
            action="approval_grant_revoked",
            status="ok",
            detail={"grant_id": grant_id},
        )
    return grant


def _resolve_skill_execution_approval(row: dict, manifest: dict, approval: dict | None, *, session_id: str = "") -> tuple[dict | None, dict | None]:
    normalized = normalize_approval(approval)
    if not manifest.get("requires_approval", False):
        return normalized if isinstance(approval, dict) else None, None

    if normalized.get("approved", False):
        if not str(normalized.get("note", "") or "").strip():
            raise SkillApprovalRequired(_build_skill_approval_payload(row, manifest, session_id=session_id))
        scope = str((approval or {}).get("scope", "once") or "once").strip().lower()
        grant = create_approval_grant(
            subject_type="skill",
            subject_id=_skill_subject_id(row),
            manifest_hash=_skill_manifest_hash(manifest),
            scope=scope if scope in {"once", "session", "always"} else "once",
            actor=str(normalized.get("actor", "user") or "user").strip() or "user",
            note=str(normalized.get("note", "") or "").strip(),
            session_id=str(session_id or (approval or {}).get("session_id", "") or "").strip(),
            permissions=manifest,
            metadata=_skill_grant_metadata(row, manifest),
        )
        if str(grant.get("scope", "")).strip().lower() == "once":
            grant = consume_approval_grant(grant["grant_id"]) or grant
        approved = {
            "approved": True,
            "note": grant.get("note", ""),
            "actor": grant.get("actor", "user"),
            "scope": grant.get("scope", "once"),
            "grant_id": grant.get("grant_id", ""),
            "grant_source": "explicit",
        }
        return approved, grant

    grant = find_matching_approval_grant(
        subject_type="skill",
        subject_id=_skill_subject_id(row),
        manifest_hash=_skill_manifest_hash(manifest),
        session_id=str(session_id or "").strip(),
    )
    if grant:
        consumed = consume_approval_grant(grant["grant_id"]) or grant
        approved = {
            "approved": True,
            "note": consumed.get("note", ""),
            "actor": consumed.get("actor", "user"),
            "scope": consumed.get("scope", "once"),
            "grant_id": consumed.get("grant_id", ""),
            "grant_source": "stored",
        }
        _record_permission_event(
            f"skill:{row.get('slug', row.get('skill_id', 'unknown'))}",
            action="approval_grant_consumed",
            status="approved",
            detail={"grant_id": consumed.get("grant_id", ""), "scope": consumed.get("scope", "")},
        )
        return approved, consumed

    raise SkillApprovalRequired(_build_skill_approval_payload(row, manifest, session_id=session_id))


def _strip_execution_control(inputs: dict) -> tuple[dict, dict | None]:
    payload = dict(inputs or {})
    approval = payload.pop("_approval", None)
    if approval is None:
        approval = payload.pop("approval", None)
    return payload, approval if isinstance(approval, dict) else None


def _extension_host_env() -> dict[str, str]:
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
        "KENDR_HOME",
        "KENDR_DB_PATH",
    }
    return {
        key: value
        for key, value in os.environ.items()
        if key in allowed and str(value).strip()
    }


def _extension_host_popen_kwargs() -> dict[str, object]:
    if os.name == "nt":
        flag = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": flag} if flag else {}
    return {"start_new_session": True}


def _extension_host_injected_env(payload: dict) -> dict[str, str]:
    permissions = payload.get("permissions") if isinstance(payload.get("permissions"), dict) else {}
    environment = permissions.get("environment", {}) if isinstance(permissions.get("environment"), dict) else {}
    requested = environment.get("read", []) if isinstance(environment.get("read", []), list) else []
    injected: dict[str, str] = {}
    for item in requested:
        key = str(item or "").strip()
        value = str(os.environ.get(key, "") or "").strip()
        if key and value:
            injected[key] = value
    return injected


def _terminate_extension_host(process: subprocess.Popen[str]) -> None:
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


def _run_extension_host(mode: str, payload: dict, *, timeout: int) -> dict:
    host_payload = dict(payload or {})
    injected_env = _extension_host_injected_env(host_payload)
    if injected_env:
        host_payload["injected_env"] = injected_env
    base_env = _extension_host_env()
    sandbox_info = {
        "mode": "process_isolated_only",
        "provider": "none",
        "required": False,
        "available": False,
        "reason": "",
    }
    process: subprocess.Popen[str] | None = None
    with tempfile.TemporaryDirectory(prefix="kendr-extension-launch-") as launch_root:
        launch = extension_sandbox.prepare_extension_host_launch(
            mode=mode,
            payload=host_payload,
            base_command=[sys.executable, "-m", "kendr.extension_host", mode],
            base_env=base_env,
            launch_root=launch_root,
        )
        sandbox_info = dict(launch.sandbox or {})
        if launch.blocked_error:
            return {
                "output": None,
                "stdout": "",
                "stderr": "",
                "success": False,
                "error": launch.blocked_error,
                "sandbox": sandbox_info,
            }
        try:
            process = subprocess.Popen(
                launch.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=launch.env,
                **_extension_host_popen_kwargs(),
            )
            stdout, stderr = process.communicate(
                input=json.dumps(host_payload, ensure_ascii=False),
                timeout=max(1, timeout) + 2,
            )
        except subprocess.TimeoutExpired:
            if process is not None:
                _terminate_extension_host(process)
            try:
                stdout, stderr = process.communicate(timeout=2) if process is not None else ("", "")
            except Exception:
                stdout, stderr = "", ""
            return {
                "output": None,
                "stdout": stdout,
                "stderr": stderr,
                "success": False,
                "error": f"Extension host timed out after {timeout}s",
                "sandbox": sandbox_info,
            }
        except Exception:
            return {"output": None, "stdout": "", "stderr": "", "success": False, "error": traceback.format_exc(), "sandbox": sandbox_info}

    raw_output = stdout.strip()
    if process.returncode != 0:
        return {
            "output": None,
            "stdout": raw_output,
            "stderr": stderr,
            "success": False,
            "error": stderr or f"Extension host exited with code {process.returncode}",
            "sandbox": sandbox_info,
        }
    try:
        payload_out = json.loads(raw_output or "{}")
    except Exception:
        return {
            "output": None,
            "stdout": raw_output,
            "stderr": stderr,
            "success": False,
            "error": "Extension host returned invalid JSON",
            "sandbox": sandbox_info,
        }
    if isinstance(payload_out, dict):
        payload_out.setdefault("sandbox", sandbox_info)
        return payload_out
    return {
        "output": None,
        "stdout": raw_output,
        "stderr": stderr,
        "success": False,
        "error": "Extension host returned an invalid payload",
        "sandbox": sandbox_info,
    }


def _run_python_skill(code: str, inputs: dict, *, permission_manifest: dict | None = None, approval: dict | None = None, skill_label: str = "skill.python") -> dict:
    """Execute python skill code in an isolated extension-host subprocess."""
    effective_manifest = permission_manifest if isinstance(permission_manifest, dict) else {"requires_approval": False}
    result = _run_extension_host(
        "python-skill",
        {
            "code": code,
            "inputs": inputs,
            "timeout": _EXEC_TIMEOUT,
            "permissions": effective_manifest,
            "approval": normalize_approval(approval),
            "workspace_root": _default_execution_cwd(),
        },
        timeout=_EXEC_TIMEOUT,
    )
    if not result.get("success", False):
        _record_permission_event(
            skill_label,
            action="python_skill_execution",
            status="blocked" if "approval" in str(result.get("error", "")).lower() or "access denied" in str(result.get("error", "")).lower() else "error",
            detail={
                "error": str(result.get("error", "") or ""),
                "permissions": summarize_permission_manifest(effective_manifest),
            },
        )
    elif effective_manifest.get("requires_approval", False):
        _record_permission_event(
            skill_label,
            action="python_skill_execution",
            status="approved",
            detail={
                "approval": normalize_approval(approval),
                "permissions": summarize_permission_manifest(effective_manifest),
            },
        )
    return result


def _run_prompt_skill(prompt_template: str, inputs: dict) -> dict:
    """Execute a prompt skill via the LLM (best-effort, may not have LLM available)."""
    try:
        # Interpolate {variable} placeholders from inputs
        rendered = prompt_template
        for k, v in inputs.items():
            rendered = rendered.replace(f"{{{k}}}", str(v))

        # Try to call the LLM if available
        try:
            import openai
            client = openai.OpenAI()
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": rendered}],
                max_tokens=1024,
            )
            text = resp.choices[0].message.content or ""
            return {"output": text, "stdout": text, "stderr": "", "success": True, "error": None}
        except Exception as llm_err:
            # Fall back: return the rendered prompt with a note
            return {
                "output": rendered,
                "stdout": f"[LLM unavailable: {llm_err}]\nRendered prompt:\n{rendered}",
                "stderr": "",
                "success": True,
                "error": None,
            }
    except Exception:
        return {"output": None, "stdout": "", "stderr": "", "success": False, "error": traceback.format_exc()}


def _run_catalog_skill(catalog_id: str, inputs: dict, *, permission_manifest: dict | None = None, approval: dict | None = None) -> dict:
    """Dispatch a catalog skill to its built-in handler."""
    handlers = _catalog_handlers()
    handler = handlers.get(catalog_id)
    if not handler:
        return {
            "output": None,
            "stdout": f"Catalog skill '{catalog_id}' has no built-in handler in this environment.",
            "stderr": "",
            "success": False,
            "error": f"No handler registered for catalog skill '{catalog_id}'",
        }
    try:
        result = handler(inputs, permission_manifest=permission_manifest, approval=approval)
        output_str = json.dumps(result, ensure_ascii=False, indent=2) if not isinstance(result, str) else result
        return {"output": result, "stdout": output_str, "stderr": "", "success": True, "error": None}
    except Exception:
        return {"output": None, "stdout": "", "stderr": "", "success": False, "error": traceback.format_exc()}


def test_skill(skill_id: str, inputs: dict, *, approval: dict | None = None, session_id: str = "") -> dict:
    """Run a skill with the provided inputs and return the execution result."""
    row = resolve_runtime_skill(skill_id=skill_id)
    if not row:
        return {"success": False, "error": f"Skill {skill_id!r} not found."}

    skill_type = row.get("skill_type", "")
    code = row.get("code", "")
    safe_inputs, inline_approval = _strip_execution_control(inputs)
    effective_approval = approval if isinstance(approval, dict) else inline_approval
    permission_manifest = permission_manifest_from_metadata(
        row.get("metadata", {}),
        skill_type=str(skill_type or ""),
        catalog_id=str(row.get("catalog_id", "") or ""),
        cwd=_default_execution_cwd(),
    )
    permission_manifest = _contextualize_permission_manifest(row, permission_manifest, safe_inputs)
    skill_label = f"skill:{row.get('slug', row.get('skill_id', 'unknown'))}"
    try:
        resolved_approval, _grant = _resolve_skill_execution_approval(
            row,
            permission_manifest,
            effective_approval,
            session_id=str(session_id or "").strip(),
        )
    except SkillApprovalRequired as exc:
        _record_permission_event(
            skill_label,
            action="skill_approval_requested",
            status="blocked",
            detail={"approval_request": exc.payload.get("approval_request", {}), "manifest_hash": exc.payload.get("manifest_hash", "")},
        )
        return exc.payload

    if skill_type == "python":
        return _run_python_skill(code, safe_inputs, permission_manifest=permission_manifest, approval=resolved_approval, skill_label=skill_label)
    elif skill_type == "prompt":
        return _run_prompt_skill(code, safe_inputs)
    elif skill_type == "catalog":
        return _run_catalog_skill(
            row.get("catalog_id", ""),
            safe_inputs,
            permission_manifest=permission_manifest,
            approval=resolved_approval,
        )
    else:
        return {"success": False, "error": f"Unknown skill_type: {skill_type!r}"}


test_skill.__test__ = False


def execute_skill_by_slug(slug: str, inputs: dict, *, approval: dict | None = None, session_id: str = "") -> dict:
    """Public API for agents to call a skill by its slug."""
    row = resolve_runtime_skill(slug=slug)
    if not row:
        return {"success": False, "error": f"Skill '{slug}' not found or not installed."}
    if not row.get("is_installed"):
        return {"success": False, "error": f"Skill '{slug}' is not installed."}
    return test_skill(row["skill_id"], inputs, approval=approval, session_id=session_id)


# ---------------------------------------------------------------------------
# Built-in catalog handlers
# ---------------------------------------------------------------------------

def _catalog_handlers() -> dict[str, Any]:
    """Return a dict of catalog_id → handler function (lazily built)."""
    return {
        "web-search": _handle_web_search,
        "desktop-automation": _handle_desktop_automation,
        "pdf-reader": _handle_pdf_reader,
        "file-reader": _handle_file_reader,
        "file-finder": _handle_file_finder,
        "doc-summarizer": _handle_doc_summarizer,
        "spreadsheet-basic": _handle_spreadsheet_basic,
        "email-digest": _handle_email_digest,
        "calendar-agenda": _handle_calendar_agenda,
        "meeting-notes": _handle_meeting_notes,
        "todo-planner": _handle_todo_planner,
        "travel-helper": _handle_travel_helper,
        "message-draft": _handle_message_draft,
    }


def _handle_web_search(inputs: dict, *, permission_manifest: dict | None = None, approval: dict | None = None) -> dict:
    query = str(inputs.get("query", "")).strip()
    num_results = int(inputs.get("num_results", 5))
    if not query:
        raise ValueError("'query' is required")
    result = _run_extension_host(
        "web-search",
        {
            "query": query,
            "num_results": num_results,
            "permissions": permission_manifest or {},
            "approval": normalize_approval(approval),
        },
        timeout=max(10, _EXEC_TIMEOUT),
    )
    if not result.get("success"):
        _record_permission_event(
            "catalog:web-search",
            action="web_search_execution",
            status="blocked" if "network" in str(result.get("error", "")).lower() or "approval" in str(result.get("error", "")).lower() else "error",
            detail={
                "query": query,
                "error": str(result.get("error", "") or ""),
                "permissions": summarize_permission_manifest(permission_manifest or {}),
            },
        )
        raise RuntimeError(str(result.get("error", "Web search execution failed")))
    output = result.get("output")
    return output if isinstance(output, dict) else {"query": query, "results": []}


def _handle_desktop_automation(inputs: dict, *, permission_manifest: dict | None = None, approval: dict | None = None) -> dict:
    access_mode = desktop_automation_broker.normalize_access_mode(str(inputs.get("access_mode", "sandbox") or "sandbox"))
    timeout = max(5, int(inputs.get("timeout", 10) or 10))
    result = _run_extension_host(
        "desktop-automation",
        {
            "inputs": inputs,
            "timeout": timeout,
            "permissions": permission_manifest or {},
            "approval": normalize_approval(approval),
        },
        timeout=timeout,
    )
    if not result.get("success"):
        _record_permission_event(
            "catalog:desktop-automation",
            action="desktop_automation_execution",
            status="blocked" if "approval" in str(result.get("error", "")).lower() else "error",
            detail={
                "access_mode": access_mode,
                "app": str(inputs.get("app", "") or "").strip(),
                "action": str(inputs.get("action", "") or "").strip(),
                "error": str(result.get("error", "") or ""),
                "permissions": summarize_permission_manifest(permission_manifest or {}),
                "sandbox": result.get("sandbox", {}),
            },
        )
        raise RuntimeError(str(result.get("error", "Desktop automation execution failed")))
    output = result.get("output")
    if access_mode == "full_access":
        _record_permission_event(
            "catalog:desktop-automation",
            action="desktop_automation_execution",
            status="approved",
            detail={
                "access_mode": access_mode,
                "app": str(inputs.get("app", "") or "").strip(),
                "action": str(inputs.get("action", "") or "").strip(),
                "approval": normalize_approval(approval),
                "permissions": summarize_permission_manifest(permission_manifest or {}),
                "sandbox": result.get("sandbox", {}),
            },
        )
    else:
        _record_permission_event(
            "catalog:desktop-automation",
            action="desktop_automation_preview",
            status="ok",
            detail={
                "app": str(inputs.get("app", "") or "").strip(),
                "action": str(inputs.get("action", "") or "").strip(),
                "sandbox": result.get("sandbox", {}),
            },
        )
    return output if isinstance(output, dict) else {"access_mode": access_mode, "dispatched": False, "preview_only": access_mode != "full_access"}

def _handle_pdf_reader(inputs: dict, **_kwargs) -> dict:
    file_path = str(inputs.get("file_path", "")).strip()
    doc = _parse_local_document(file_path)
    metadata = doc.get("metadata", {}) if isinstance(doc.get("metadata"), dict) else {}
    return {
        "text": str(doc.get("text", "") or ""),
        "page_count": int(metadata.get("pages", 0) or 0),
        "metadata": metadata,
    }


_TEXT_SEARCH_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".htm",
    ".css",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
}


def _resolve_user_path(path_str: str) -> Path:
    raw = str(path_str or "").strip()
    if not raw:
        raise ValueError("A valid path is required.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(_default_execution_cwd()) / path
    return path.resolve()


def _parse_local_document(file_path: str) -> dict:
    from tasks.research_infra import parse_document

    path = _resolve_user_path(file_path)
    return parse_document(str(path))


def _truncate_text(text: str, limit: int = 12000) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + " ..."


def _llm_text(prompt: str) -> str:
    from tasks.research_infra import llm_text

    return llm_text(prompt).strip()


def _http_json(url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> dict:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _google_gmail_messages(query: str, max_results: int) -> list[dict]:
    access_token = get_google_access_token()
    if not access_token:
        return []
    headers = {"Authorization": f"Bearer {access_token}"}
    list_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages?" + urlencode(
        {"q": query or "is:unread newer_than:7d", "maxResults": max_results}
    )
    listing = _http_json(list_url, headers=headers)
    messages: list[dict] = []
    for item in listing.get("messages", [])[:max_results]:
        msg = _http_json(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date",
            headers=headers,
        )
        header_map = {
            str(header.get("name", "")).lower(): str(header.get("value", "")).strip()
            for header in msg.get("payload", {}).get("headers", []) or []
            if isinstance(header, dict)
        }
        messages.append(
            {
                "provider": "gmail",
                "id": msg.get("id"),
                "subject": header_map.get("subject", ""),
                "from": header_map.get("from", ""),
                "date": header_map.get("date", ""),
                "snippet": msg.get("snippet", ""),
                "label_ids": msg.get("labelIds", []),
            }
        )
    return messages


def _microsoft_messages(max_results: int) -> list[dict]:
    access_token = get_microsoft_graph_access_token()
    if not access_token:
        return []
    headers = {"Authorization": f"Bearer {access_token}"}
    url = (
        "https://graph.microsoft.com/v1.0/me/messages?"
        + urlencode(
            {
                "$top": max_results,
                "$select": "id,subject,receivedDateTime,bodyPreview,isRead,from",
                "$orderby": "receivedDateTime desc",
            }
        )
    )
    payload = _http_json(url, headers=headers)
    messages: list[dict] = []
    for item in payload.get("value", []) or []:
        sender = ((item.get("from") or {}).get("emailAddress") or {}) if isinstance(item.get("from"), dict) else {}
        messages.append(
            {
                "provider": "outlook",
                "id": item.get("id"),
                "subject": item.get("subject", ""),
                "from": sender.get("address", ""),
                "date": item.get("receivedDateTime", ""),
                "snippet": item.get("bodyPreview", ""),
                "is_read": item.get("isRead", False),
            }
        )
    return messages


def _google_calendar_events(window: str) -> list[dict]:
    access_token = get_google_access_token()
    if not access_token:
        return []
    now = datetime.now(timezone.utc)
    end = now + (timedelta(days=7) if window == "week" else timedelta(days=1))
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events?" + urlencode(
        {
            "timeMin": now.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 50,
        }
    )
    payload = _http_json(url, headers={"Authorization": f"Bearer {access_token}"})
    events: list[dict] = []
    for item in payload.get("items", []) or []:
        events.append(
            {
                "provider": "google_calendar",
                "title": item.get("summary", ""),
                "start": (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date", ""),
                "end": (item.get("end") or {}).get("dateTime") or (item.get("end") or {}).get("date", ""),
                "location": item.get("location", ""),
            }
        )
    return events


def _microsoft_calendar_events(window: str) -> list[dict]:
    access_token = get_microsoft_graph_access_token()
    if not access_token:
        return []
    now = datetime.now(timezone.utc)
    end = now + (timedelta(days=7) if window == "week" else timedelta(days=1))
    url = (
        "https://graph.microsoft.com/v1.0/me/calendarView?"
        + urlencode({"startDateTime": now.isoformat(), "endDateTime": end.isoformat(), "$top": 50})
    )
    payload = _http_json(url, headers={"Authorization": f"Bearer {access_token}"})
    events: list[dict] = []
    for item in payload.get("value", []) or []:
        events.append(
            {
                "provider": "outlook_calendar",
                "title": item.get("subject", ""),
                "start": ((item.get("start") or {}).get("dateTime") or ""),
                "end": ((item.get("end") or {}).get("dateTime") or ""),
                "location": ((item.get("location") or {}).get("displayName") or ""),
            }
        )
    return events


def _handle_file_reader(inputs: dict, **_kwargs) -> dict:
    file_path = str(inputs.get("file_path", "")).strip()
    if not file_path:
        raise ValueError("'file_path' is required")
    doc = _parse_local_document(file_path)
    return {
        "path": doc.get("path", ""),
        "text": str(doc.get("text", "") or ""),
        "metadata": doc.get("metadata", {}) if isinstance(doc.get("metadata"), dict) else {},
    }


def _handle_file_finder(inputs: dict, **_kwargs) -> dict:
    query = str(inputs.get("query", "")).strip()
    if not query:
        raise ValueError("'query' is required")
    root = _resolve_user_path(str(inputs.get("root_path", "")).strip() or _default_execution_cwd())
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Search root not found: {root}")
    search_content = bool(inputs.get("search_content", False))
    limit = max(1, min(int(inputs.get("limit", 10) or 10), 50))
    lowered = query.lower()
    matches: list[dict] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = str(path.relative_to(root))
        score = 0
        reasons: list[str] = []
        preview = ""
        if lowered in path.name.lower():
            score += 4
            reasons.append("name")
        if lowered in rel_path.lower():
            score += 2
            reasons.append("path")
        if search_content and path.suffix.lower() in _TEXT_SEARCH_EXTENSIONS:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                content = ""
            content_lower = content.lower()
            if lowered in content_lower:
                score += 1
                reasons.append("content")
                idx = content_lower.find(lowered)
                if idx >= 0:
                    preview = _truncate_text(content[max(0, idx - 120) : idx + 220], limit=240)
        if score:
            matches.append(
                {
                    "path": str(path),
                    "relative_path": rel_path,
                    "score": score,
                    "match_reasons": reasons,
                    "preview": preview,
                }
            )
    matches.sort(key=lambda item: (-int(item.get("score", 0)), str(item.get("relative_path", ""))))
    return {"root_path": str(root), "query": query, "matches": matches[:limit]}


def _handle_doc_summarizer(inputs: dict, **_kwargs) -> dict:
    file_path = str(inputs.get("file_path", "")).strip()
    if not file_path:
        raise ValueError("'file_path' is required")
    style = str(inputs.get("style", "medium") or "medium").strip().lower()
    focus = str(inputs.get("focus", "")).strip()
    doc = _parse_local_document(file_path)
    text = str(doc.get("text", "") or "").strip()
    if not text:
        raise ValueError("The document did not contain readable text.")
    summary = _llm_text(
        f"""You are a document summarization assistant.

Style: {style}
Focus: {focus or "General summary"}
File path: {doc.get("path", "")}
Document metadata: {json.dumps(doc.get("metadata", {}), ensure_ascii=False)}

Document text:
{_truncate_text(text, limit=16000)}

Return a concise, practical response. If style is `action_items`, return action items first.
"""
    )
    return {"path": doc.get("path", ""), "summary": summary, "metadata": doc.get("metadata", {})}


def _handle_spreadsheet_basic(inputs: dict, **_kwargs) -> dict:
    from tasks.excel_tasks import _load_workbook_data, _render_workbook_summary, _summarize_sheet

    file_path = str(inputs.get("file_path", "")).strip()
    if not file_path:
        raise ValueError("'file_path' is required")
    question = str(inputs.get("question", "")).strip()
    max_rows = max(1, min(int(inputs.get("max_rows", 5) or 5), 20))
    path = _resolve_user_path(file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        doc = _parse_local_document(str(path))
        text = str(doc.get("text", "") or "")
        lines = [line for line in text.splitlines() if line.strip()]
        workbook_summary = {
            "file_name": path.name,
            "file_path": str(path),
            "sheets": [
                {
                    "sheet_name": "Sheet1",
                    "row_count": max(len(lines) - 1, 0),
                    "column_count": len(lines[0].split(",")) if lines else 0,
                    "columns": [],
                    "sample_records": lines[1 : 1 + max_rows],
                }
            ],
        }
        summary_text = _render_workbook_summary(workbook_summary)
    elif suffix in {".xlsx", ".xlsm"}:
        workbook = _load_workbook_data(path)
        workbook_summary = {
            "file_name": workbook["file_name"],
            "file_path": workbook["file_path"],
            "sheets": [_summarize_sheet(sheet, max_rows=max_rows) for sheet in workbook["sheets"]],
        }
        summary_text = _render_workbook_summary(workbook_summary)
    else:
        raise ValueError("spreadsheet-basic supports .csv, .xlsx, and .xlsm files.")

    analysis = _llm_text(
        f"""You are a spreadsheet analyst.

User question: {question or "Summarize the sheet, highlight totals or trends, and point out anything notable."}

Spreadsheet summary:
{summary_text}

Return a clear answer in plain text.
"""
    )
    return {"path": str(path), "summary": summary_text, "analysis": analysis}


def _handle_email_digest(inputs: dict, **_kwargs) -> dict:
    query = str(inputs.get("query", "")).strip()
    max_results = max(1, min(int(inputs.get("max_results", 10) or 10), 25))
    draft_reply_to = str(inputs.get("draft_reply_to", "")).strip()
    messages = _google_gmail_messages(query, max_results) + _microsoft_messages(max_results)
    if not messages:
        return {
            "summary": "Email digest is not configured. Connect Gmail or Microsoft Graph in Setup so Kendr can read inbox data.",
            "messages": [],
            "configured": False,
        }
    prompt = f"""You are an email assistant.

Summarize the inbox items below. Highlight urgent threads, deadlines, and follow-ups.
{"Also draft a reply suggestion for: " + draft_reply_to if draft_reply_to else ""}

Messages:
{json.dumps(messages[:max_results], indent=2, ensure_ascii=False)}
"""
    return {"summary": _llm_text(prompt), "messages": messages[:max_results], "configured": True}


def _handle_calendar_agenda(inputs: dict, **_kwargs) -> dict:
    window = str(inputs.get("window", "today") or "today").strip().lower()
    if window not in {"today", "week"}:
        raise ValueError("'window' must be 'today' or 'week'")
    events = _google_calendar_events(window) + _microsoft_calendar_events(window)
    if not events:
        return {
            "summary": "Calendar agenda is not configured. Connect Google Calendar or Microsoft Graph in Setup so Kendr can read events.",
            "events": [],
            "configured": False,
        }
    summary = _llm_text(
        f"""You are a calendar assistant.

Window: {window}
Events:
{json.dumps(events, indent=2, ensure_ascii=False)}

Summarize the agenda, highlight overlaps, and mention free blocks or preparation needs.
"""
    )
    return {"summary": summary, "events": events, "configured": True}


def _handle_meeting_notes(inputs: dict, **_kwargs) -> dict:
    notes = str(inputs.get("notes", "")).strip()
    if not notes:
        raise ValueError("'notes' is required")
    style = str(inputs.get("style", "summary") or "summary").strip().lower()
    result = _llm_text(
        f"""You are a meeting notes assistant.

Output style: {style}
Raw notes:
{notes}

Return a clean response. If style is action_items, return owners and next steps when possible.
"""
    )
    return {"result": result}


def _handle_todo_planner(inputs: dict, **_kwargs) -> dict:
    tasks = str(inputs.get("tasks", "")).strip()
    if not tasks:
        raise ValueError("'tasks' is required")
    horizon = str(inputs.get("horizon", "today") or "today").strip().lower()
    result = _llm_text(
        f"""You are a practical planning assistant.

Planning horizon: {horizon}
Tasks:
{tasks}

Return a prioritized plan with ordering, grouping, and a realistic sequence.
"""
    )
    return {"plan": result}


def _handle_travel_helper(inputs: dict, **_kwargs) -> dict:
    request = str(inputs.get("request", "")).strip()
    if not request:
        raise ValueError("'request' is required")
    travel_data: dict[str, Any] = {"source": "planner"}
    origin = str(inputs.get("origin", "")).strip()
    destination = str(inputs.get("destination", "")).strip()
    provider = str(inputs.get("provider", "") or "").strip().lower()
    use_serpapi = provider == "serpapi"
    if use_serpapi and os.getenv("SERP_API_KEY", "").strip() and origin and destination:
        try:
            from tasks.travel_tasks import _serpapi_request, _travel_mode_code

            payload = _serpapi_request(
                {
                    "engine": "google_maps_directions",
                    "start_addr": origin,
                    "end_addr": destination,
                    "travel_mode": _travel_mode_code("transit"),
                    "hl": "en",
                },
                timeout=30,
            )
            travel_data = {"source": "serpapi", "route": payload}
        except Exception as exc:
            travel_data = {"source": "planner", "error": str(exc)}
    summary = _llm_text(
        f"""You are a travel planning assistant.

Request: {request}
Origin: {origin or "not provided"}
Destination: {destination or "not provided"}
Date: {str(inputs.get("date", "") or "").strip() or "not provided"}
Travel data:
{json.dumps(travel_data, ensure_ascii=False)[:16000]}

Return a practical travel brief with best option, checklist, and next steps.
"""
    )
    return {"summary": summary, "travel_data": travel_data}


def _handle_message_draft(inputs: dict, **_kwargs) -> dict:
    recipient = str(inputs.get("recipient", "")).strip()
    goal = str(inputs.get("goal", "")).strip()
    if not recipient or not goal:
        raise ValueError("'recipient' and 'goal' are required")
    draft = _llm_text(
        f"""You are a message drafting assistant.

Channel: {str(inputs.get("channel", "email") or "email").strip()}
Recipient: {recipient}
Goal: {goal}
Tone: {str(inputs.get("tone", "clear and polite") or "clear and polite").strip()}
Context:
{str(inputs.get("context", "") or "").strip()}

Write a ready-to-send draft.
"""
    )
    return {"draft": draft}
