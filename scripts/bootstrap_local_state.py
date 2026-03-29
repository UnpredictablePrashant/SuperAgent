#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKDIR = ROOT / "output" / "workspace"
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _ensure_env_file() -> tuple[bool, Path]:
    env_path = ROOT / ".env"
    example_path = ROOT / ".env.example"
    if env_path.exists():
        return False, env_path
    if example_path.exists():
        text = example_path.read_text(encoding="utf-8")
        text = text.replace('KENDR_WORKING_DIR="C:/path/to/your/workdir"', f'KENDR_WORKING_DIR="{DEFAULT_WORKDIR.as_posix()}"')
        text = text.replace('QDRANT_URL="http://qdrant:6333"', f'QDRANT_URL="{DEFAULT_QDRANT_URL}"')
        env_path.write_text(text, encoding="utf-8")
        return True, env_path
    env_path.write_text(
        f'OPENAI_API_KEY=\nKENDR_WORKING_DIR="{DEFAULT_WORKDIR.as_posix()}"\nQDRANT_URL="{DEFAULT_QDRANT_URL}"\nSERP_API_KEY=\n',
        encoding="utf-8",
    )
    return True, env_path


def main() -> int:
    _ensure_dir(ROOT / "output")
    _ensure_dir(ROOT / "logs")
    _ensure_dir(DEFAULT_WORKDIR)
    _ensure_dir(ROOT / "output" / "workspace_memory")
    _ensure_dir(ROOT / ".secrets")

    created_env, env_path = _ensure_env_file()

    if created_env:
        print(f"[bootstrap] created local env file: {env_path}")
        print("[bootstrap] fill in credentials locally before running long/external tasks.")
    else:
        print(f"[bootstrap] local env file already exists: {env_path}")

    print("[bootstrap] ensured local runtime folders: output/, output/workspace/, logs/, output/workspace_memory/, .secrets/")
    print("[bootstrap] reminder: local credential files are ignored by .gitignore/.dockerignore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
