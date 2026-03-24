#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _ensure_env_file() -> tuple[bool, Path]:
    env_path = ROOT / ".env"
    example_path = ROOT / ".env.example"
    if env_path.exists():
        return False, env_path
    if example_path.exists():
        shutil.copyfile(example_path, env_path)
        return True, env_path
    env_path.write_text(
        "OPENAI_API_KEY=\nSERP_API_KEY=\n",
        encoding="utf-8",
    )
    return True, env_path


def main() -> int:
    _ensure_dir(ROOT / "output")
    _ensure_dir(ROOT / "logs")
    _ensure_dir(ROOT / "output" / "workspace_memory")
    _ensure_dir(ROOT / ".secrets")

    created_env, env_path = _ensure_env_file()

    if created_env:
        print(f"[bootstrap] created local env file: {env_path}")
        print("[bootstrap] fill in credentials locally before running long/external tasks.")
    else:
        print(f"[bootstrap] local env file already exists: {env_path}")

    print("[bootstrap] ensured local runtime folders: output/, logs/, output/workspace_memory/, .secrets/")
    print("[bootstrap] reminder: local credential files are ignored by .gitignore/.dockerignore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
