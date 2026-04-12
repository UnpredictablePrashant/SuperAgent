"""Skill Manager — install, uninstall, create, test, and list skills.

Skills are callable tools that agents discover and invoke. Three kinds:
  - catalog  : pre-built system skills (installed from the marketplace)
  - python   : user-defined Python function (code stored in DB, executed sandboxed)
  - prompt   : user-defined prompt template (executed via the LLM)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

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
    catalog = list_catalog_skills(category=category, q=q)

    # Map slug → installed row
    installed_rows = {r["slug"]: r for r in list_user_skills(is_installed=True)}

    for item in catalog:
        slug = item["id"]
        installed_row = installed_rows.get(slug)
        core_row = _build_core_skill_row(slug)
        effective_row = resolve_runtime_skill(skill_id=str(installed_row.get("skill_id", ""))) if installed_row else core_row
        item["is_core"] = bool(item.get("is_core", False))
        item["is_installed"] = installed_row is not None or core_row is not None
        item["skill_id"] = effective_row["skill_id"] if effective_row else None
        item["permission_manifest"] = permission_manifest_from_metadata(
            effective_row.get("metadata", {}) if isinstance(effective_row, dict) else {},
            skill_type="catalog",
            catalog_id=slug,
            cwd=_default_execution_cwd(),
        )

    # Append custom (python/prompt) skills that are installed
    custom = [
        r for r in list_user_skills()
        if r["skill_type"] in ("python", "prompt")
    ]

    core_count = sum(
        1
        for item in catalog
        if bool(item.get("is_core")) and not installed_rows.get(str(item.get("id", "")).strip())
    )

    return {
        "catalog": catalog,
        "custom": custom,
        "categories": catalog_categories(),
        "installed_count": len(installed_rows) + core_count + len([c for c in custom if c["is_installed"]]),
    }


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
            return _build_core_skill_row(skill_id.split("core:", 1)[1].strip())
        row = get_user_skill(skill_id=skill_id)
    elif slug:
        row = get_user_skill(slug=slug)
    if row:
        if row.get("skill_type") == "catalog":
            catalog_id = str(row.get("catalog_id", "") or str(row.get("slug", ""))).strip()
            entry = CATALOG_BY_ID.get(catalog_id)
            if entry:
                if not bool(row.get("is_installed", False)) and bool(getattr(entry, "core", False)):
                    return _build_core_skill_row(catalog_id)
                row = dict(row)
                row["metadata"] = _catalog_metadata(entry, existing_metadata=row.get("metadata", {}))
        return row
    if slug:
        return _build_core_skill_row(slug)
    return None


def list_runtime_skills() -> list[dict]:
    rows = list_user_skills(is_installed=True)
    by_slug: dict[str, dict] = {}
    for row in rows:
        slug = str(row.get("slug", "")).strip()
        if not slug:
            continue
        resolved = resolve_runtime_skill(skill_id=str(row.get("skill_id", "")).strip()) or dict(row)
        by_slug[slug] = resolved
    for catalog_id, entry in CATALOG_BY_ID.items():
        if bool(getattr(entry, "core", False)) and catalog_id not in by_slug:
            core_row = _build_core_skill_row(catalog_id)
            if core_row:
                by_slug[catalog_id] = core_row
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
        return bool(_build_core_skill_row(catalog_id))
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
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "kendr.extension_host", mode],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_extension_host_env(),
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
        return {"output": None, "stdout": stdout, "stderr": stderr, "success": False, "error": f"Extension host timed out after {timeout}s"}
    except Exception:
        return {"output": None, "stdout": "", "stderr": "", "success": False, "error": traceback.format_exc()}

    raw_output = stdout.strip()
    if process.returncode != 0:
        return {
            "output": None,
            "stdout": raw_output,
            "stderr": stderr,
            "success": False,
            "error": stderr or f"Extension host exited with code {process.returncode}",
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
        }
    return payload_out if isinstance(payload_out, dict) else {
        "output": None,
        "stdout": raw_output,
        "stderr": stderr,
        "success": False,
        "error": "Extension host returned an invalid payload",
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
        "code-executor": _handle_code_executor,
        "pdf-reader": _handle_pdf_reader,
        "shell-command": _handle_shell_command,
        "api-caller": _handle_api_caller,
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


def _handle_code_executor(inputs: dict, *, permission_manifest: dict | None = None, approval: dict | None = None) -> dict:
    code = str(inputs.get("code", "")).strip()
    if not code:
        raise ValueError("'code' is required")
    return _run_python_skill(
        code,
        {},
        permission_manifest=permission_manifest,
        approval=approval,
        skill_label="catalog:code-executor",
    )


def _handle_pdf_reader(inputs: dict, **_kwargs) -> dict:
    file_path = str(inputs.get("file_path", "")).strip()
    if not file_path or not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path!r}")
    try:
        import pypdf
        reader = pypdf.PdfReader(file_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return {"text": text, "page_count": len(reader.pages)}
    except ImportError:
        return {"text": "", "page_count": 0, "error": "pypdf not installed. Run: pip install pypdf"}


def _handle_shell_command(inputs: dict, *, permission_manifest: dict | None = None, approval: dict | None = None) -> dict:
    command = str(inputs.get("command", "")).strip()
    cwd = str(inputs.get("cwd", "")).strip() or None
    timeout = int(inputs.get("timeout", 30))
    if not command:
        raise ValueError("'command' is required")
    result = _run_extension_host(
        "shell-command",
        {
            "command": command,
            "cwd": cwd,
            "workspace_root": _default_execution_cwd(),
            "timeout": timeout,
            "permissions": permission_manifest or {},
            "approval": normalize_approval(approval),
        },
        timeout=timeout,
    )
    if not result.get("success"):
        _record_permission_event(
            "catalog:shell-command",
            action="shell_command_execution",
            status="blocked" if "approval" in str(result.get("error", "")).lower() or "disabled" in str(result.get("error", "")).lower() or "outside the allowed scope" in str(result.get("error", "")).lower() else "error",
            detail={
                "command": command,
                "cwd": cwd or _default_execution_cwd(),
                "error": str(result.get("error", "") or ""),
                "permissions": summarize_permission_manifest(permission_manifest or {}),
            },
        )
        raise RuntimeError(str(result.get("error", "Shell command execution failed")))
    if permission_manifest and permission_manifest.get("requires_approval", False):
        _record_permission_event(
            "catalog:shell-command",
            action="shell_command_execution",
            status="approved",
            detail={
                "command": command,
                "cwd": cwd or _default_execution_cwd(),
                "approval": normalize_approval(approval),
                "permissions": summarize_permission_manifest(permission_manifest),
            },
        )
    output = result.get("output")
    return output if isinstance(output, dict) else {"stdout": "", "stderr": "", "returncode": 1}


def _handle_api_caller(inputs: dict, *, permission_manifest: dict | None = None, approval: dict | None = None) -> dict:
    url = str(inputs.get("url", "")).strip()
    method = str(inputs.get("method", "GET")).upper()
    headers = dict(inputs.get("headers") or {})
    body = inputs.get("body")
    if not url:
        raise ValueError("'url' is required")
    result = _run_extension_host(
        "http-request",
        {
            "url": url,
            "method": method,
            "headers": headers,
            "body": body,
            "timeout": int(inputs.get("timeout", 15) or 15),
            "permissions": permission_manifest or {},
            "approval": normalize_approval(approval),
        },
        timeout=max(15, int(inputs.get("timeout", 15) or 15)),
    )
    if not result.get("success"):
        _record_permission_event(
            "catalog:api-caller",
            action="api_request_execution",
            status="blocked" if "network" in str(result.get("error", "")).lower() or "approval" in str(result.get("error", "")).lower() else "error",
            detail={
                "url": url,
                "method": method,
                "error": str(result.get("error", "") or ""),
                "permissions": summarize_permission_manifest(permission_manifest or {}),
            },
        )
        raise RuntimeError(str(result.get("error", "API caller execution failed")))
    if permission_manifest and permission_manifest.get("requires_approval", False):
        _record_permission_event(
            "catalog:api-caller",
            action="api_request_execution",
            status="approved",
            detail={
                "url": url,
                "method": method,
                "approval": normalize_approval(approval),
                "permissions": summarize_permission_manifest(permission_manifest),
            },
        )
    output = result.get("output")
    return output if isinstance(output, dict) else {"status_code": 0, "body": None, "headers": {}}
