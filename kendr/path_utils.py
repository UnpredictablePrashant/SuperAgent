from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_WINDOWS_DRIVE_PATH_RE = re.compile(r"^([a-zA-Z]):[\\/](.*)$")


def normalize_host_path(path_value: str, *, base_dir: str | None = None) -> Path:
    """Return a normalized absolute path for the current host OS.

    On non-Windows hosts, Windows-style absolute paths (for example `D:/repo`
    or `D:\\repo`) are mapped to `/mnt/<drive>/...` to support WSL workflows
    and to prevent accidental creation of literal `D:` directories in the
    current working directory.
    """
    raw = str(path_value or "").strip()
    if not raw:
        base = Path(base_dir).expanduser() if str(base_dir or "").strip() else Path.cwd()
        return base.resolve()

    match = _WINDOWS_DRIVE_PATH_RE.match(raw)
    if match and os.name != "nt":
        drive = match.group(1).lower()
        tail = match.group(2).replace("\\", "/")
        candidate = Path(f"/mnt/{drive}/{tail}")
    else:
        candidate = Path(raw).expanduser()

    if not candidate.is_absolute():
        base = Path(base_dir).expanduser().resolve() if str(base_dir or "").strip() else Path.cwd().resolve()
        candidate = base / candidate

    return candidate.resolve()


def normalize_host_path_str(path_value: str, *, base_dir: str | None = None) -> str:
    return str(normalize_host_path(path_value, base_dir=base_dir))


def application_root() -> Path:
    """Return the repo root in source mode or the unpacked bundle root when frozen."""
    if getattr(sys, "frozen", False):
        bundle_root = str(getattr(sys, "_MEIPASS", "")).strip()
        if bundle_root:
            return Path(bundle_root).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundled_resource_path(*parts: str) -> Path:
    return application_root().joinpath(*parts)
