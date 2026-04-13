from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_KNOWN_SOFTWARE = {
    "docker": "docker",
    "git": "git",
    "python": "python",
    "python3": "python",
    "node": "node",
    "nodejs": "node",
    "code": "vscode",
    "vscode": "vscode",
    "visual studio code": "vscode",
    "kubectl": "kubectl",
    "terraform": "terraform",
}


def _inventory_path(working_directory: str) -> Path:
    root = Path(str(working_directory or ".")).expanduser().resolve()
    return root / ".kendr" / "software_inventory.json"


def load_inventory_snapshot(working_directory: str) -> dict[str, Any]:
    path = _inventory_path(working_directory)
    if not path.exists():
        return {"last_synced_at": "", "software": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"last_synced_at": "", "software": {}}
    if not isinstance(data, dict):
        return {"last_synced_at": "", "software": {}}
    software = data.get("software", {})
    return {
        "last_synced_at": str(data.get("last_synced_at", "") or ""),
        "software": software if isinstance(software, dict) else {},
    }


def is_inventory_stale(snapshot: dict[str, Any], *, max_age_days: int = 30) -> bool:
    last_synced = str(snapshot.get("last_synced_at", "") or "").strip()
    if not last_synced:
        return True
    try:
        last_dt = datetime.fromisoformat(last_synced.replace("Z", "+00:00"))
    except Exception:
        return True
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last_dt) > timedelta(days=max_age_days)


def _persist_snapshot(working_directory: str, snapshot: dict[str, Any]) -> None:
    path = _inventory_path(working_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")


def _canonical_software_name(raw: str) -> str:
    key = str(raw or "").strip().lower()
    if key in _KNOWN_SOFTWARE:
        return _KNOWN_SOFTWARE[key]
    return key


def _extract_primary_software(command: str) -> str:
    lowered = str(command or "").lower()
    for marker, canonical in _KNOWN_SOFTWARE.items():
        if marker in lowered:
            return canonical
    return ""


def _apply_inventory_record(snapshot: dict[str, Any], software: str, installed: bool, path: str = "") -> None:
    canonical = _canonical_software_name(software)
    if not canonical:
        return
    software_map = snapshot.setdefault("software", {})
    if not isinstance(software_map, dict):
        software_map = {}
        snapshot["software"] = software_map
    software_map[canonical] = {
        "installed": bool(installed),
        "path": str(path or "").strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def update_inventory_from_command_result(
    *,
    working_directory: str,
    command: str,
    stdout: str,
    stderr: str,
    return_code: int | None,
) -> dict[str, Any]:
    snapshot = load_inventory_snapshot(working_directory)
    output = str(stdout or "")
    combined = f"{output}\n{str(stderr or '')}".lower()

    # Bulk inventory sync format: "<tool>|installed|<path>" or "<tool>|missing|"
    updated_any = False
    for line in output.splitlines():
        parts = [part.strip() for part in line.split("|", 2)]
        if len(parts) < 2:
            continue
        name = _canonical_software_name(parts[0])
        status = parts[1].lower()
        if not name or status not in {"installed", "missing"}:
            continue
        path = parts[2] if len(parts) > 2 else ""
        _apply_inventory_record(snapshot, name, status == "installed", path)
        updated_any = True

    primary = _extract_primary_software(command)
    if primary:
        if "not installed" in combined or "missing" in combined:
            _apply_inventory_record(snapshot, primary, False, "")
            updated_any = True
        elif return_code == 0 and ("installed:" in combined or "version" in combined or "usage" in combined):
            path_match = re.search(r"installed:\s*([^\s]+)", output, flags=re.IGNORECASE)
            _apply_inventory_record(snapshot, primary, True, path_match.group(1) if path_match else "")
            updated_any = True
        elif return_code == 0 and re.search(r"\b(install|installed|setup)\b", command.lower()):
            _apply_inventory_record(snapshot, primary, True, "")
            updated_any = True

    if updated_any:
        snapshot["last_synced_at"] = datetime.now(timezone.utc).isoformat()
        _persist_snapshot(working_directory, snapshot)
    return snapshot
