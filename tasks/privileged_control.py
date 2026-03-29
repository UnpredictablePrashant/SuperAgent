from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from kendr.persistence import insert_privileged_audit_event


_SUSPECT_SECRET_PATTERNS = [
    re.compile(r"(OPENAI_API_KEY\s*=\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(AWS_SECRET_ACCESS_KEY\s*=\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(SLACK_BOT_TOKEN\s*=\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(GOOGLE_CLIENT_SECRET\s*=\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(MICROSOFT_CLIENT_SECRET\s*=\s*)([^\s]+)", re.IGNORECASE),
    re.compile(r"(WHATSAPP_ACCESS_TOKEN\s*=\s*)([^\s]+)", re.IGNORECASE),
]

_DESTRUCTIVE_COMMAND_HINTS = [
    "rm -rf",
    "rm -fr",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    "halt",
    "del /f",
    "rd /s /q",
    "format ",
    "diskpart",
    "userdel ",
    "drop database",
    "truncate table",
]

_MUTATING_COMMAND_HINTS = [
    "rm ",
    "mv ",
    "cp ",
    "mkdir ",
    "rmdir ",
    "touch ",
    "sed -i",
    "tee ",
    "apt-get install",
    "yum install",
    "dnf install",
    "pip install",
    "npm install",
    "choco install",
    "winget install",
    "git commit",
    "git push",
]


def _truthy(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _list_from_any(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value).strip()
    if not raw:
        return []
    sep = ";" if ";" in raw else ","
    if os.pathsep in raw and "," not in raw and ";" not in raw:
        sep = os.pathsep
    return [part.strip() for part in raw.split(sep) if part.strip()]


def build_privileged_policy(state: dict) -> dict:
    working_directory = str(state.get("working_directory", "")).strip()
    allowed_paths = _list_from_any(state.get("privileged_allowed_paths") or os.getenv("KENDR_ALLOWED_PATHS", ""))
    if working_directory and working_directory not in allowed_paths:
        allowed_paths.insert(0, working_directory)
    normalized_allowed_paths = []
    for item in allowed_paths:
        try:
            normalized_allowed_paths.append(str(Path(item).expanduser().resolve()))
        except Exception:
            continue

    policy = {
        "privileged_mode": _truthy(state.get("privileged_mode", os.getenv("KENDR_PRIVILEGED_MODE", False))),
        "approved": _truthy(state.get("privileged_approved", False)),
        "approval_note": str(state.get("privileged_approval_note", "")).strip(),
        "require_approvals": _truthy(state.get("privileged_require_approvals", os.getenv("KENDR_REQUIRE_APPROVALS", True))),
        "read_only": _truthy(state.get("privileged_read_only", os.getenv("KENDR_READ_ONLY_MODE", False))),
        "allow_root": _truthy(state.get("privileged_allow_root", os.getenv("KENDR_ALLOW_ROOT", False))),
        "allow_destructive": _truthy(
            state.get("privileged_allow_destructive", os.getenv("KENDR_ALLOW_DESTRUCTIVE", False))
        ),
        "enable_backup": _truthy(state.get("privileged_enable_backup", os.getenv("KENDR_ENABLE_BACKUPS", True))),
        "allowed_paths": normalized_allowed_paths,
        "allowed_domains": _list_from_any(state.get("privileged_allowed_domains") or os.getenv("KENDR_ALLOWED_DOMAINS", "")),
        "kill_switch_file": str(
            state.get("kill_switch_file")
            or os.getenv("KENDR_KILL_SWITCH_FILE", os.path.join("output", "KENDR_STOP"))
        ).strip(),
    }
    return policy


def classify_command(command: str) -> dict:
    lowered = str(command or "").lower()
    root_requested = "sudo " in lowered or lowered.startswith("sudo")
    destructive = any(hint in lowered for hint in _DESTRUCTIVE_COMMAND_HINTS)
    mutating = destructive or any(hint in lowered for hint in _MUTATING_COMMAND_HINTS)
    networking = any(hint in lowered for hint in ["curl ", "wget ", "invoke-webrequest", "http://", "https://", "ssh "])
    return {
        "root_requested": root_requested,
        "destructive": destructive,
        "mutating": mutating,
        "networking": networking,
    }


def extract_path_references(command: str) -> list[str]:
    text = str(command or "")
    refs: set[str] = set()
    unix_matches = re.findall(r"(?:^|\s)(/[A-Za-z0-9._\-/]+)", text)
    win_matches = re.findall(r"([A-Za-z]:\\[^\s\"']+)", text)
    for item in unix_matches + win_matches:
        refs.add(item.strip())
    return sorted(refs)


def path_allowed(path_value: str, allowed_roots: list[str]) -> bool:
    if not allowed_roots:
        return True
    try:
        path_obj = Path(path_value).expanduser().resolve()
    except Exception:
        return False
    for root in allowed_roots:
        try:
            root_obj = Path(root).expanduser().resolve()
        except Exception:
            continue
        if path_obj == root_obj or root_obj in path_obj.parents:
            return True
    return False


def redact_sensitive_text(text: str) -> str:
    redacted = str(text or "")
    for pattern in _SUSPECT_SECRET_PATTERNS:
        redacted = pattern.sub(r"\1********", redacted)
    return redacted


def ensure_command_allowed(command: str, working_directory: str, policy: dict) -> None:
    classification = classify_command(command)
    if policy.get("require_approvals", True):
        if not policy.get("approved", False) or not policy.get("approval_note", ""):
            raise PermissionError("Privileged action requires explicit approval and non-empty privileged_approval_note.")
    if policy.get("read_only", False) and classification["mutating"]:
        raise PermissionError("Read-only privileged mode blocks mutating commands.")
    if classification["root_requested"] and not policy.get("allow_root", False):
        raise PermissionError("Command requests root escalation but privileged_allow_root is false.")
    if classification["destructive"] and not policy.get("allow_destructive", False):
        raise PermissionError("Destructive command blocked: privileged_allow_destructive is false.")
    if not path_allowed(working_directory, policy.get("allowed_paths", [])):
        raise PermissionError("Working directory is outside privileged allowed path scope.")
    for ref in extract_path_references(command):
        if not path_allowed(ref, policy.get("allowed_paths", [])):
            raise PermissionError(f"Command references path outside allowed scope: {ref}")


def create_backup_snapshot(state: dict, *, source_dir: str, reason: str) -> str:
    run_id = str(state.get("run_id", "no-run-id"))
    source = Path(source_dir).expanduser().resolve()
    snapshot_name = f"snapshot_{run_id}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.tar.gz"
    snapshots_dir = Path("output").resolve() / "privileged_snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    target = snapshots_dir / snapshot_name
    with tarfile.open(target, "w:gz") as tar:
        tar.add(source, arcname=source.name)
    _ = reason
    return str(target)


def list_backup_snapshots(limit: int = 50) -> list[str]:
    snapshots_dir = Path("output").resolve() / "privileged_snapshots"
    if not snapshots_dir.exists():
        return []
    files = sorted([p for p in snapshots_dir.glob("snapshot_*.tar.gz")], key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p) for p in files[:limit]]


def restore_backup_snapshot(snapshot_path: str, target_dir: str, *, overwrite: bool = False) -> str:
    archive = Path(snapshot_path).expanduser().resolve()
    if not archive.exists():
        raise FileNotFoundError(f"Snapshot not found: {archive}")
    target = Path(target_dir).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and target.exists():
        shutil.rmtree(target)
    with tarfile.open(archive, "r:gz") as tar:
        destination = target.parent.resolve()
        for member in tar.getmembers():
            member_path = (destination / member.name).resolve()
            if destination not in member_path.parents and member_path != destination:
                raise ValueError(f"Unsafe snapshot entry blocked: {member.name}")
        tar.extractall(path=destination)
    return str(target)


def _last_audit_hash(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        value = str(payload.get("event_hash", "")).strip()
        if value:
            return value
    return ""


def append_privileged_audit_event(state: dict, *, actor: str, action: str, status: str, detail: dict) -> dict:
    event_id = f"audit_{uuid.uuid4().hex}"
    run_id = str(state.get("run_id", ""))
    timestamp = datetime.now(UTC).isoformat()
    run_output_dir = str(state.get("run_output_dir", "")).strip()
    base_dir = Path(run_output_dir).resolve() if run_output_dir else Path("output").resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    log_path = base_dir / "privileged_audit.log"
    prev_hash = str(state.get("privileged_audit_last_hash", "")).strip() or _last_audit_hash(log_path)
    payload = {
        "event_id": event_id,
        "run_id": run_id,
        "timestamp": timestamp,
        "actor": actor,
        "action": action,
        "status": status,
        "detail": detail if isinstance(detail, dict) else {"raw": str(detail)},
        "prev_hash": prev_hash,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    event_hash = hashlib.sha256((prev_hash + serialized).encode("utf-8")).hexdigest()
    payload["event_hash"] = event_hash
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    insert_privileged_audit_event(payload)
    state["privileged_audit_last_hash"] = event_hash
    return payload
